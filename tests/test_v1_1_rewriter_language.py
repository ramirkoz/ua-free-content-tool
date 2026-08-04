from __future__ import annotations

from content_agent.models import Article
from content_agent.rewriter import rewrite_article


class FakeClient:
    def __init__(self, payload: dict[str, str]):
        self.payload = payload
        self.prompts: list[str] = []

    def generate_json(self, model, prompt, schema, **kwargs):  # type: ignore[no-untyped-def]
        self.prompts.append(prompt)
        return dict(self.payload)


def article() -> Article:
    return Article(
        id=1, source_id=1, title="Заголовок", url="https://example.com",
        raw_text="Українське джерело повідомляє про подію у Києві 4 серпня.", status="new",
    )


def test_english_mode_changes_prompt_and_accepts_english_output() -> None:
    client = FakeClient({
        "headline": "Kyiv event",
        "fact_card": "One source used.",
        "rewrite": "Officials reported the event in Kyiv on 4 August.",
    })
    result = rewrite_article(client, "model", article(), language="en")
    assert result.rewrite.startswith("Officials")
    assert "ENGLISH ONLY" in client.prompts[0]


def test_ukrainian_mode_keeps_ukrainian_instruction() -> None:
    client = FakeClient({
        "headline": "Подія у Києві",
        "fact_card": "Використано одне джерело.",
        "rewrite": "Посадовці повідомили про подію у Києві 4 серпня.",
    })
    result = rewrite_article(client, "model", article(), language="uk")
    assert result.rewrite.startswith("Посадовці")
    assert "ВИКЛЮЧНО УКРАЇНСЬКА" in client.prompts[0]
