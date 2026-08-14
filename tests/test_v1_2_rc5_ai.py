from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from content_agent import codex_news_v1_3, rowboat_bridge_v1_3
from content_agent.codex_engine_v1_3 import CodexEngineError
from content_agent.codex_news_v1_3 import build_rewrite_prompt, rewrite_group_with_codex
from content_agent.models import Article, NewsGroup
from content_agent.paths import reset_path_cache_for_tests
from content_agent.rowboat_bridge_v1_3 import memory_context, memory_root, rowboat_workdir, sync_editorial_memory
from content_agent.ui import queue_migration_codex_v1_3
from content_agent.ui.ai_engine_v1_3 import AIEngineV13Mixin
from content_agent.ui.queue_migration_codex_v1_3 import CodexQueueMigrationDialog


def _group(*texts: str) -> NewsGroup:
    articles = [
        Article(
            id=index,
            source_id=index,
            title=f"Матеріал {index}",
            url=f"https://example.com/{index}",
            raw_text=text,
            status="new",
            published_at="2026-08-14T08:00:00+03:00",
            source_name=f"Джерело {index}",
        )
        for index, text in enumerate(texts, start=1)
    ]
    return NewsGroup(
        id=11,
        canonical_title="Тестова подія",
        status="draft",
        created_at="2026-08-14T08:00:00+03:00",
        updated_at="2026-08-14T08:00:00+03:00",
        source_count=len(articles),
        include_source_link=True,
        articles=articles,
    )


def test_codex_prompt_contains_every_source_and_graph_memory() -> None:
    group = _group("Перший факт про відкриття простору.", "Другий матеріал уточнює дату 14 серпня.")
    prompt = build_rewrite_prompt(group, [], graph_memory="Попередній стиль редактора")
    assert "Перший факт про відкриття простору." in prompt
    assert "Другий матеріал уточнює дату 14 серпня." in prompt
    assert "Попередній стиль редактора" in prompt
    assert "НЕ є джерелом нових фактів" in prompt


def test_short_news_prompt_forbids_inflation() -> None:
    prompt = build_rewrite_prompt(_group("У місті відкрили новий простір."), [])
    assert "1 речення" in prompt
    assert "Не роздувай" in prompt


def test_codex_rewrite_accepts_strict_json(monkeypatch: pytest.MonkeyPatch) -> None:
    group = _group("У місті відкрили новий громадський простір 14 серпня.")
    monkeypatch.setattr(
        codex_news_v1_3,
        "run_codex",
        lambda _prompt: '{"headline":"Новий простір","fact_card":"Одне джерело","rewrite":"У місті 14 серпня відкрили новий громадський простір."}',
    )
    result = rewrite_group_with_codex(group, [])
    assert result.headline == "Новий простір"
    assert result.source_count_used == 1
    assert result.platform_texts["telegram"] == result.rewrite
    assert group.primary_url not in result.platform_texts["telegram"]


def test_codex_rewrite_rejects_invalid_protocol(monkeypatch: pytest.MonkeyPatch) -> None:
    group = _group("У місті відкрили новий громадський простір.")
    monkeypatch.setattr(codex_news_v1_3, "run_codex", lambda _prompt: "ЗАГОЛОВОК: тест\nТЕКСТ: щось")
    with pytest.raises(CodexEngineError):
        rewrite_group_with_codex(group, [])


def test_rowboat_memory_graph_exports_and_retrieves(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UA_FREE_CONTENT_DATA", str(tmp_path))
    reset_path_cache_for_tests()

    class FakeDatabase:
        def list_editorial_examples(self, *, language: str):
            assert language == "uk"
            return [
                {
                    "id": 7,
                    "source_text": "У громаді відкрили молодіжний простір 14 серпня.",
                    "final_text": "У громаді 14 серпня відкрили молодіжний простір.",
                    "headline": "Молодіжний простір",
                }
            ]

        def list_topic_feedback(self, *, language: str):
            assert language == "uk"
            return [
                {
                    "decision": "merged",
                    "anchor_text": "Відкриття молодіжного простору",
                    "candidate_text": "Новий простір для молоді відкрили сьогодні",
                }
            ]

    counts = sync_editorial_memory(FakeDatabase())
    root = memory_root()
    assert counts == {"examples": 1, "decisions": 1}
    assert root == rowboat_workdir() / "knowledge" / "ua-free"
    assert (root / "editorial-examples" / "example-7.md").is_file()
    context = memory_context("молодіжний простір відкрили 14 серпня")
    assert "молодіжний простір" in context.casefold()
    reset_path_cache_for_tests()


def test_rowboat_release_matcher_accepts_versioned_windows_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "assets": [
            {
                "name": "Rowboat-win32-x64-0.8.7-setup.exe",
                "browser_download_url": "https://github.com/rowboatlabs/rowboat/releases/download/v0.8.7/Rowboat-win32-x64-0.8.7-setup.exe",
                "digest": "sha256:abc123",
            }
        ]
    }

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.close()
            return False

    monkeypatch.setattr(
        rowboat_bridge_v1_3.urllib.request,
        "urlopen",
        lambda _request, timeout=45: FakeResponse(json.dumps(payload).encode("utf-8")),
    )
    name, url, digest = rowboat_bridge_v1_3._latest_windows_asset()
    assert name == "Rowboat-win32-x64-0.8.7-setup.exe"
    assert url.endswith("Rowboat-win32-x64-0.8.7-setup.exe")
    assert digest == "sha256:abc123"


def test_queue_migration_uses_codex_and_respects_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queue_migration_codex_v1_3, "run_codex", lambda _prompt: "Короткий схвалений текст.")
    result = CodexQueueMigrationDialog._compress_with_codex("Довгий схвалений текст.", 100, "uk")
    assert result == "Короткий схвалений текст."


def test_queue_migration_rejects_codex_over_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queue_migration_codex_v1_3, "run_codex", lambda _prompt: "x" * 101)
    with pytest.raises(RuntimeError):
        CodexQueueMigrationDialog._compress_with_codex("Довгий текст.", 100, "uk")


def test_ollama_prewarm_is_disabled_in_rc5() -> None:
    instance = object.__new__(AIEngineV13Mixin)
    assert instance._prewarm_ollama_model_async("legacy-model") is None
