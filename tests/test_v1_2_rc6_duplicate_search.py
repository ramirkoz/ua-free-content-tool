from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from content_agent import global_duplicates_v1_2_2_rc6 as dup
from content_agent.models import Article, NewsGroup


def _group(group_id: int, title: str, text: str, minute: int = 0) -> NewsGroup:
    article = Article(
        id=group_id,
        source_id=group_id,
        title=title,
        url=f"https://example.com/{group_id}",
        raw_text=text,
        status="new",
        published_at=f"2026-08-17T09:{minute % 60:02d}:00+03:00",
        source_name="test",
    )
    return NewsGroup(
        id=group_id,
        canonical_title=title,
        status="new",
        created_at="2026-08-17T09:00:00+03:00",
        updated_at="2026-08-17T09:00:00+03:00",
        source_count=1,
        include_source_link=True,
        articles=[article],
    )


def test_fast_prefilter_handles_large_inbox_without_all_pairs_router(monkeypatch: pytest.MonkeyPatch) -> None:
    groups = [
        _group(i, f"Різна новина {i}", f"Унікальний матеріал номер {i} про окрему подію.", i)
        for i in range(1, 1001)
    ]
    groups[500] = _group(501, "У Києві відкрили новий міст 17 серпня", "У Києві 17 серпня відкрили новий міст через Дніпро.")
    groups[700] = _group(701, "Новий міст у Києві відкрили 17 серпня", "17 серпня у Києві відкрили новий міст через Дніпро.")

    monkeypatch.setattr(dup, "run_ai", lambda *a, **k: (_ for _ in ()).throw(dup.AIRouterError("offline")))
    result = dup.find_global_duplicate_clusters(groups, deadline_seconds=20)
    assert any({501, 701} <= set(cluster.group_ids) for cluster in result)
    assert dup.last_duplicate_search_label() == "локальні кандидати без AI"


def test_duplicate_router_is_one_bounded_call_and_skips_codex(monkeypatch: pytest.MonkeyPatch) -> None:
    groups = [
        _group(1, "Ракета влучила у склад у місті", "Ракета влучила у склад о 10:00, пожежу локалізували."),
        _group(2, "У місті ракета влучила у склад", "О 10:00 ракета влучила у той самий склад, пожежу локалізували."),
        _group(3, "Інша спортивна новина", "Команда виграла матч."),
    ]
    seen: dict[str, object] = {}

    def fake_run_ai(prompt: str, **kwargs):
        seen.update(kwargs)
        raw = "MERGE 1,2 | 96 | та сама конкретна подія"
        kwargs["validator"](raw)
        return SimpleNamespace(text=raw)

    monkeypatch.setattr(dup, "run_ai", fake_run_ai)
    result = dup.find_global_duplicate_clusters(groups, deadline_seconds=20)
    assert result[0].group_ids == (1, 2)
    assert seen["cloud_timeout_seconds"] == 6
    assert seen["local_timeout_seconds"] == 12
    assert seen["suppress_provider_on_quota"] is True
    assert seen["skip_providers"] == {"codex"}
    assert int(seen["task_timeout_seconds"]) <= 28


def test_duplicate_search_can_be_cancelled_before_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    groups = [
        _group(1, "Одна подія 123", "Одна подія 123 сталася сьогодні."),
        _group(2, "Одна подія 123", "Одна подія 123 сталася сьогодні."),
    ]
    event = threading.Event()
    event.set()
    called = False

    def fake_run_ai(*args, **kwargs):
        nonlocal called
        called = True
        return SimpleNamespace(text="NONE")

    monkeypatch.setattr(dup, "run_ai", fake_run_ai)
    with pytest.raises(dup.DuplicateSearchCancelled):
        dup.find_global_duplicate_clusters(groups, cancel_event=event, deadline_seconds=20)
    assert called is False


def test_duplicate_search_cancelled_while_ai_result_is_returning(monkeypatch: pytest.MonkeyPatch) -> None:
    groups = [
        _group(1, "Одна подія 123", "Одна подія 123 сталася сьогодні."),
        _group(2, "Одна подія 123", "Одна подія 123 сталася сьогодні."),
    ]
    event = threading.Event()

    def fake_run_ai(*args, **kwargs):
        event.set()
        return SimpleNamespace(text="MERGE 1,2 | 95 | та сама подія")

    monkeypatch.setattr(dup, "run_ai", fake_run_ai)
    with pytest.raises(dup.DuplicateSearchCancelled):
        dup.find_global_duplicate_clusters(groups, cancel_event=event, deadline_seconds=20)


def test_ai_workflow_has_hard_ui_timeout_and_cancel_button() -> None:
    from pathlib import Path
    source = Path("content_agent/ui/ai_workflow_v1_3_rc6.py").read_text(encoding="utf-8")
    assert "timeout_seconds=90" in source
    assert 'text="Скасувати пошук"' in source
    assert "deadline_seconds=72" in source
