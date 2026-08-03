from __future__ import annotations

import json
import socket

import pytest

from content_agent.models import Article
from content_agent.ollama_client import (
    OllamaClient,
    OllamaTimeoutError,
    _decode_rewrite_payload,
)
from content_agent.rewriter import rewrite_article, rewrite_article_with_fallback


RUSSIAN_SAMPLE = """Туск призвал Навроцкого прервать молчание и остановить насилие
Премьер-министр Польши публично обратился к президенту, призвав его перестать молчать о нападениях на украинцев. По словам Туска, политики, оправдывающие радикалов, несут свою долю ответственности за рост насилия.
Он также обратился к Ярославу Качиньскому с призывом прекратить призывы к созданию боевых групп. По словам Туска, нападения на украинцев — это проявление бандитизма и агрессивной уличной патологии, которая почувствовала безнаказанность благодаря политическому покровительству.
«Каждый, кто избивает украинок на польских улицах, поддерживает худший образ мышления — в Польше, Украине и во всём мире. Мы должны объявить решительную войну этому насилию», — заявил Туск."""


def test_plain_marker_decoder_accepts_newsroom_output() -> None:
    value = _decode_rewrite_payload(
        "ЗАГОЛОВОК: Туск закликав зупинити насильство\n"
        "ТЕКСТ:\n"
        "Прем'єр Польщі Дональд Туск звернувся до президента.\n\n"
        "Він закликав припинити політичне виправдання нападів на українців."
    )
    assert value["headline"] == "Туск закликав зупинити насильство"
    assert "Дональд Туск" in str(value["rewrite"])
    assert value["fact_card"]


def test_plain_decoder_keeps_legacy_json_compatibility() -> None:
    value = _decode_rewrite_payload(
        json.dumps({"headline": "H", "fact_card": "F", "rewrite": "R"}, ensure_ascii=False)
    )
    assert value == {"headline": "H", "fact_card": "F", "rewrite": "R"}


class _PlainClient:
    def __init__(self) -> None:
        self.prompt = ""

    def generate_json(self, _model: str, prompt: str, _schema: dict[str, object]) -> dict[str, object]:
        self.prompt = prompt
        return {
            "headline": "Туск закликав президента Польщі відреагувати на напади на українців",
            "rewrite": (
                "Прем'єр-міністр Польщі Дональд Туск закликав президента Кароля Навроцького "
                "публічно засудити напади на українців і не мовчати про зростання насильства.\n\n"
                "Туск також звернувся до Ярослава Качинського із вимогою припинити заклики до "
                "створення бойових груп. За його словами, політичне виправдання радикалів сприяє "
                "відчуттю безкарності та поширенню вуличної агресії."
            ),
        }


def test_user_sample_uses_one_compact_prompt_and_local_fact_card() -> None:
    client = _PlainClient()
    article = Article(1, 1, "Туск призвал Навроцкого", "https://example.com", RUSSIAN_SAMPLE, "new")
    result = rewrite_article(client, "qwen3:4b", article)  # type: ignore[arg-type]
    assert "без JSON" in client.prompt
    assert RUSSIAN_SAMPLE[:300] in client.prompt
    assert result.fact_card
    assert 350 <= len(result.rewrite) <= 1000
    assert len(set(result.platform_texts.values())) == 1


def test_timeout_launches_different_same_size_fallback() -> None:
    class _Client:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def generate_json(self, model: str, _prompt: str, _schema: dict[str, object]) -> dict[str, object]:
            self.calls.append(model)
            if model == "qwen3:4b":
                raise OllamaTimeoutError("too slow")
            return {"headline": "H", "fact_card": "F", "rewrite": "R"}

    client = _Client()
    article = Article(1, 1, "Title", "https://example.com", "Text", "new")
    result, model, used = rewrite_article_with_fallback(
        client, "qwen3:4b", "gemma3:4b", article  # type: ignore[arg-type]
    )
    assert result.rewrite == "R"
    assert model == "gemma3:4b"
    assert used is True
    assert client.calls == ["qwen3:4b", "gemma3:4b"]


def test_smaller_fallback_is_allowed_after_timeout() -> None:
    class _Client:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def generate_json(self, model: str, _prompt: str, _schema: dict[str, object]) -> dict[str, object]:
            self.calls.append(model)
            if model == "qwen3:4b":
                raise OllamaTimeoutError("too slow")
            return {"headline": "H", "fact_card": "F", "rewrite": "R"}

    client = _Client()
    article = Article(1, 1, "Title", "https://example.com", "Text", "new")
    result, model, used = rewrite_article_with_fallback(
        client, "qwen3:4b", "qwen3:1.7b", article  # type: ignore[arg-type]
    )
    assert result.rewrite == "R"
    assert model == "qwen3:1.7b"
    assert used is True
    assert client.calls == ["qwen3:4b", "qwen3:1.7b"]


def test_nonstream_timeout_is_reported_once(monkeypatch) -> None:
    def fake_urlopen(*_args, **_kwargs):
        raise socket.timeout()

    monkeypatch.setattr("content_agent.ollama_client.urlopen", fake_urlopen)
    client = OllamaClient("http://127.0.0.1:11434", timeout=33)
    monkeypatch.setattr(client, "preload_model", lambda _model: None)
    with pytest.raises(OllamaTimeoutError, match="33 секунд"):
        client.generate_json("qwen3:4b", "prompt", {})
