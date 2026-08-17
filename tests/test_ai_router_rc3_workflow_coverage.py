from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from content_agent import global_duplicates_v1_2_2_rc5 as global_duplicates
from content_agent.models import Article, NewsGroup
from content_agent.ui import queue_migration_codex_v1_3 as queue_migration


def _group(group_id: int, text: str) -> NewsGroup:
    article = Article(
        id=group_id,
        source_id=1,
        title=f"Матеріал {group_id}",
        url=f"https://example.com/{group_id}",
        raw_text=text,
        status="new",
    )
    return NewsGroup(
        id=group_id,
        canonical_title=f"Блок {group_id}",
        status="new",
        created_at="2026-08-16T09:00:00+00:00",
        updated_at="2026-08-16T09:00:00+00:00",
        source_count=1,
        articles=[article],
    )


def test_global_duplicate_search_uses_ai_router(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    raw = '{"clusters":[{"group_ids":[1,2],"confidence":93,"reason":"та сама подія"}]}'

    def fake_run_ai(prompt: str, *, validator=None, max_output_tokens=4096):
        calls.append(prompt)
        assert validator is not None
        assert max_output_tokens <= 900
        validator(raw)
        return SimpleNamespace(text=raw)

    monkeypatch.setattr(global_duplicates, "run_ai", fake_run_ai)
    result = global_duplicates.find_global_duplicate_clusters(
        [_group(1, "Одна подія."), _group(2, "Уточнення тієї самої події.")]
    )
    assert calls
    assert len(result) == 1
    assert result[0].group_ids == (1, 2)


def test_queue_migration_production_path_uses_router_validator(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_run_ai(prompt: str, *, validator=None, max_output_tokens=4096):
        calls.append(prompt)
        assert validator is not None
        value = "Короткий текст."
        validator(value)
        return SimpleNamespace(text=value)

    monkeypatch.setattr(queue_migration, "run_ai", fake_run_ai)
    assert queue_migration.run_codex is queue_migration._ROUTER_RUN_CODEX
    result = queue_migration.CodexQueueMigrationDialog._compress_with_codex(
        "Довгий схвалений текст.", 100, "uk"
    )
    assert result == "Короткий текст."
    assert calls


def test_active_rc6_ai_workflows_do_not_import_codex_engine_directly() -> None:
    for module in (global_duplicates, queue_migration):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "codex_engine_v1_3" not in source


def test_global_duplicate_local_profile_is_compact(monkeypatch: pytest.MonkeyPatch) -> None:
    groups = [
        _group(1, "Компанія Alpha повідомила про інцидент 17 серпня. " * 80),
        _group(2, "Нові подробиці інциденту компанії Alpha 17 серпня. " * 80),
    ]
    raw = '{"clusters":[{"group_ids":[1,2],"confidence":90,"reason":"same event"}]}'
    seen: dict[str, object] = {}

    def fake_run_ai(prompt: str, **kwargs):
        seen.update(kwargs)
        assert len(str(kwargs["local_prompt"])) <= 3600
        assert kwargs["local_max_output_tokens"] == 220
        assert kwargs["local_timeout_seconds"] == 90
        kwargs["validator"](raw)
        return SimpleNamespace(text=raw)

    monkeypatch.setattr(global_duplicates, "run_ai", fake_run_ai)
    result = global_duplicates.find_global_duplicate_clusters(groups)
    assert result and result[0].group_ids == (1, 2)


def test_global_duplicate_parser_accepts_line_protocol() -> None:
    rows = global_duplicates.parse_duplicate_clusters(
        "MERGE 11,12 | 94 | та сама конкретна подія\nMERGE 20,21,22 | 83 | пряме уточнення",
        {11, 12, 20, 21, 22},
    )
    assert [item.group_ids for item in rows] == [(11, 12), (20, 21, 22)]


def test_global_duplicate_parser_accepts_none_protocol() -> None:
    assert global_duplicates.parse_duplicate_clusters("NONE", {1, 2}) == []


def test_global_duplicate_ai_total_failure_falls_back_to_local_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    groups = [
        _group(1, "ТЦК передали поліції понад 1,5 млн звернень про розшук у 2026 році."),
        _group(2, "Понад 1,5 млн звернень про розшук ТЦК передали поліції лише за 2026 рік."),
    ]

    def failed_router(*args, **kwargs):
        raise global_duplicates.AIRouterError("all providers failed")

    monkeypatch.setattr(global_duplicates, "run_ai", failed_router)
    rows = global_duplicates.find_global_duplicate_clusters(groups)
    assert rows
    assert rows[0].group_ids == (1, 2)
    assert rows[0].confidence >= 55
    assert global_duplicates.last_duplicate_search_label() == "локальні кандидати без AI"


def test_global_duplicate_prompt_uses_compact_line_protocol() -> None:
    groups = [
        _group(1, "Company Alpha incident details " * 50),
        _group(2, "Company Alpha incident update " * 50),
    ]
    prompt = global_duplicates.build_global_duplicate_prompt(groups)
    assert len(prompt) <= 4500
    assert "MERGE 12,18" in prompt
    assert "JSON" in prompt
