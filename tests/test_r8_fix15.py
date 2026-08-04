from __future__ import annotations

import json
from pathlib import Path

from content_agent.models import Article
from content_agent.ollama_client import OllamaClient
from content_agent.rewriter import (
    fit_text_to_limit,
    platform_texts_from_base,
    rewrite_article,
)


class _SingleRewriteClient:
    def __init__(self) -> None:
        self.calls = 0
        self.schema: dict[str, object] | None = None
        self.prompt = ""

    def generate_json(self, model: str, prompt: str, schema: dict[str, object]) -> dict[str, object]:
        assert model == "fast-model"
        self.calls += 1
        self.schema = schema
        self.prompt = prompt
        return {
            "headline": "Заголовок",
            "fact_card": "Хто, що, де і коли.",
            "rewrite": "Короткий базовий текст, який повинен бути однаковим для всіх платформ.",
        }


def _article(text: str = "Source text") -> Article:
    return Article(1, 1, "Title", "https://example.com", text, "new")


def test_rewriter_asks_ollama_for_one_base_text_only() -> None:
    client = _SingleRewriteClient()
    result = rewrite_article(client, "fast-model", _article())  # type: ignore[arg-type]
    assert client.calls == 1
    assert set(client.schema["properties"]) == {"headline", "fact_card", "rewrite"}  # type: ignore[index]
    assert "Не створюй окремі тексти для соцмереж" in client.prompt
    assert len(set(result.platform_texts.values())) == 1


def test_platform_texts_are_identical_until_a_real_limit_is_reached() -> None:
    short = "Коротка новина без зайвих слів."
    values = platform_texts_from_base(short, include_source_link=False, source_url="")
    assert values == {platform: short for platform in ("facebook", "threads", "linkedin", "telegram")}

    long = "Перше речення містить головний факт. " + "Друге речення додає важливі деталі. " * 30
    values = platform_texts_from_base(long, include_source_link=False, source_url="")
    assert values["facebook"] == long.strip()
    assert values["linkedin"] == long.strip()
    assert values["telegram"] == long.strip()
    assert len(values["threads"]) < len(long)
    assert values["threads"].startswith("Перше речення містить головний факт.")


def test_local_fitting_never_calls_a_model_and_respects_word_boundaries() -> None:
    result = fit_text_to_limit("слово " * 100, 80)
    assert len(result) <= 80
    assert result.endswith("…")
    assert not result.endswith(" …")


def test_ollama_nonstream_request_uses_keep_alive_and_plain_output(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit: int) -> bytes:
            body = {
                "response": "ЗАГОЛОВОК: H\nТЕКСТ:\nR",
                "done": True,
            }
            return json.dumps(body, ensure_ascii=False).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _Response()

    monkeypatch.setattr("content_agent.ollama_client.urlopen", fake_urlopen)
    client = OllamaClient("http://127.0.0.1:11434", timeout=45)
    monkeypatch.setattr(client, "preload_model", lambda _model: None)
    value = client.generate_json(
        "model",
        "short prompt",
        {"type": "object", "properties": {}, "additionalProperties": True},
    )
    assert value["headline"] == "H"
    assert value["rewrite"] == "R"
    payload = captured["payload"]
    assert payload["stream"] is False
    assert "format" not in payload
    assert payload["keep_alive"] == "30m"
    assert payload["think"] is False
    assert payload["options"]["num_predict"] == 384
    assert payload["options"]["num_ctx"] == 2048


def test_fix17_ui_defaults_to_base_text_sync_and_has_hard_timeout() -> None:
    source = Path("content_agent/ui/main_window.py").read_text(encoding="utf-8")
    assert 'root.title("UA FREE Content Tool — v1.1.0")' in source
    assert "self.same_text_var = tk.BooleanVar(value=True)" in source
    assert "self._on_base_rewrite_changed" in source
    assert "timeout_seconds=170" not in source
    assert "timeout=240, load_timeout=120" in source
    assert "timeout=180, load_timeout=120" in source
    assert "_prewarm_ollama_model_async" in source
