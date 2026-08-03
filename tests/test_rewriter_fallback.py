from __future__ import annotations

import pytest

from content_agent.models import Article
from content_agent.ollama_client import OllamaError
from content_agent.rewriter import rewrite_article_with_fallback


class FakeClient:
    def __init__(self):
        self.models: list[str] = []

    def generate_json(self, model: str, _prompt: str, _schema: dict[str, object]) -> dict[str, object]:
        self.models.append(model)
        if model == "primary":
            raise OllamaError("primary unavailable")
        return {
            "headline": "Заголовок",
            "fact_card": "Факти",
            "rewrite": "Рерайт",
            "facebook": "FB",
            "threads": "TH",
            "linkedin": "LI",
            "telegram": "TG",
        }


def article() -> Article:
    return Article(1, 1, "Title", "https://example.com", "Text", "new")


def test_rewriter_uses_fallback_model_after_primary_error() -> None:
    client = FakeClient()
    result, model, used_fallback = rewrite_article_with_fallback(client, "primary", "fallback", article())  # type: ignore[arg-type]
    assert result.rewrite == "Рерайт"
    assert model == "fallback"
    assert used_fallback is True
    assert client.models == ["primary", "fallback"]


def test_rewriter_does_not_retry_same_model() -> None:
    client = FakeClient()
    with pytest.raises(OllamaError):
        rewrite_article_with_fallback(client, "primary", "primary", article())  # type: ignore[arg-type]
    assert client.models == ["primary"]


class AlwaysFailClient:
    def __init__(self) -> None:
        self.models: list[str] = []

    def generate_json(self, model: str, _prompt: str, _schema: dict[str, object]) -> dict[str, object]:
        self.models.append(model)
        raise OllamaError(f"{model} timed out")


def test_rewriter_reports_both_model_errors_without_unboundlocalerror() -> None:
    client = AlwaysFailClient()
    with pytest.raises(OllamaError) as captured:
        rewrite_article_with_fallback(client, "primary", "fallback", article())  # type: ignore[arg-type]
    message = str(captured.value)
    assert "Основна модель «primary» не впоралася: primary timed out" in message
    assert "Запасна модель «fallback» також не впоралася: fallback timed out" in message
    assert "primary_error" not in message
    assert client.models == ["primary", "fallback"]
