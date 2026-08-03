from __future__ import annotations

import json
from pathlib import Path

from content_agent.models import Article, NewsGroup
from content_agent.ollama_client import OllamaClient
from content_agent.rewriter import _source_payload


def test_preload_uses_empty_generation_and_disables_thinking(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit: int) -> bytes:
            return b'{"done":true}'

    def fake_urlopen(request, timeout):
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _Response()

    monkeypatch.setattr("content_agent.ollama_client.urlopen", fake_urlopen)
    client = OllamaClient("http://127.0.0.1:11434", timeout=45, load_timeout=73)
    monkeypatch.setattr(client, "is_model_loaded", lambda _model: False)
    client.preload_model("qwen3:4b")
    payload = captured["payload"]
    assert captured["timeout"] == 73
    assert payload["model"] == "qwen3:4b"
    assert payload["stream"] is False
    assert payload["think"] is False
    assert payload["keep_alive"] == "30m"
    assert payload["prompt"] == ""


def test_loaded_model_skips_preload_request(monkeypatch) -> None:
    client = OllamaClient("http://127.0.0.1:11434")
    monkeypatch.setattr(client, "is_model_loaded", lambda _model: True)
    monkeypatch.setattr(
        "content_agent.ollama_client.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network must not be used")),
    )
    client.preload_model("gemma3:4b")


def test_rewrite_source_payload_is_bounded_for_small_local_models() -> None:
    articles = [
        Article(
            id=index,
            source_id=index,
            title=f"Title {index}",
            url=f"https://example.com/{index}",
            raw_text="x" * 5000,
            status="new",
            source_name=f"Source {index}",
        )
        for index in range(1, 10)
    ]
    group = NewsGroup(
        id=1,
        canonical_title="Title",
        status="draft",
        created_at="2026-07-28T00:00:00+03:00",
        updated_at="2026-07-28T00:00:00+03:00",
        source_count=len(articles),
        articles=articles,
    )
    _title, _url, payload, _include = _source_payload(group)
    assert len(payload) <= 6000
    assert "ДЖЕРЕЛО 4" in payload
    assert all(f"ДЖЕРЕЛО {index}" in payload for index in range(1, 10))


def test_fix17_ui_has_background_prewarm_and_separate_load_budget() -> None:
    source = Path("content_agent/ui/main_window.py").read_text(encoding="utf-8")
    assert 'root.title("UA FREE Content Tool — R8 FIX30")' in source
    assert "Підготовка моделі" in source
    assert "Модель {selected} готова до швидкого рерайту" in source
    assert "load_timeout=120" in source
    assert "event.wait(timeout=120)" in source
