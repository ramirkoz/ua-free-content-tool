from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from content_agent import global_duplicates_v1_3_rc6 as global_duplicates
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

    def fake_run_ai(prompt: str, *, validator=None):
        calls.append(prompt)
        assert validator is not None
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

    def fake_run_ai(prompt: str, *, validator=None):
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
