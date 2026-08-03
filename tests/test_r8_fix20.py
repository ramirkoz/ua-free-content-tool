from __future__ import annotations

import pytest

from content_agent.models import Article
from content_agent.ollama_client import OllamaError
from content_agent.rewriter import _ukrainian_language_issue, rewrite_article


SOURCE = """Украинские военные испытали «культурный шок» на учениях с НАТО
После совместных учений с НАТО в Швеции в 2025 году ВСУ усомнились в готовности альянса к современной войне, сообщает Welt. По словам одного из украинских военнослужащих, западные армии «не имели бы ни единого шанса на поле боя».
Как рассказали собеседники издания, солдаты НАТО постоянно устраивали перерывы на кофе. Украинцев также удивили ограничения по использованию беспилотников.
«Такая НАТА нам не нада», — сказал один из участников."""

RUSSIAN_OUTPUT = """Украинские военные, участвовавшие в совместных учениях с НАТО в Швеции в 2025 году, выразили удивление и определенную досаду по поводу организации и подхода западных союзников.

По словам одного из украинских военнослужащих, западные армии не продемонстрировали достаточной готовности к современной войне и не имели бы ни единого шанса на поле боя. Солдаты НАТО часто устраивали перерывы на кофе.

«Такая НАТА нам не нада», — поделился один из участников учений."""

UKRAINIAN_OUTPUT = """Українські військові, які брали участь у спільних навчаннях із НАТО у Швеції 2025 року, були здивовані організацією та підходами західних союзників.

За словами одного з українських військовослужбовців, армії країн НАТО не продемонстрували достатньої готовності до сучасної війни. Учасників також здивували часті перерви на каву та численні обмеження щодо використання безпілотників.

Під час навчань українські підрозділи виконували роль противника й перемогли сили НАТО. Один з учасників підсумував це словами: «Таке НАТО нам не потрібне»."""


def _article() -> Article:
    return Article(1, 1, "Украинские военные испытали культурный шок", "https://example.com/nato", SOURCE, "new")


def test_language_detector_rejects_exact_russian_case_and_quote() -> None:
    issue = _ukrainian_language_issue("Украинские военные испытали шок", RUSSIAN_OUTPUT)
    assert issue
    assert "росій" in issue


def test_language_detector_accepts_ukrainian_newsroom_copy() -> None:
    assert _ukrainian_language_issue("Українські військові оцінили навчання НАТО", UKRAINIAN_OUTPUT) == ""


def test_russian_first_answer_is_repaired_once_and_never_saved() -> None:
    class Client:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def generate_json(self, _model: str, prompt: str, _schema: dict[str, object]) -> dict[str, object]:
            self.calls.append(prompt)
            if len(self.calls) == 1:
                return {
                    "headline": "Украинские военные удивились учениям НАТО",
                    "rewrite": RUSSIAN_OUTPUT,
                }
            return {
                "headline": "Українські військові здивувалися підходам НАТО на навчаннях",
                "rewrite": UKRAINIAN_OUTPUT,
            }

    client = Client()
    result = rewrite_article(client, "qwen3:4b", _article())  # type: ignore[arg-type]
    assert len(client.calls) == 2
    assert "ВИХІДНА МОВА: ВИКЛЮЧНО УКРАЇНСЬКА" in client.calls[0]
    assert "Переклади ВЕСЬ текст українською" in client.calls[1]
    assert result.rewrite == UKRAINIAN_OUTPUT
    assert all("Украинские" not in text for text in result.platform_texts.values())
    assert "Таке НАТО нам не потрібне" in result.rewrite


def test_second_russian_answer_fails_closed_before_queue() -> None:
    class Client:
        def __init__(self) -> None:
            self.calls = 0

        def generate_json(self, _model: str, _prompt: str, _schema: dict[str, object]) -> dict[str, object]:
            self.calls += 1
            return {
                "headline": "Украинские военные удивились учениям НАТО",
                "rewrite": RUSSIAN_OUTPUT,
            }

    client = Client()
    with pytest.raises(OllamaError, match="Текст не збережено і не передано в чергу"):
        rewrite_article(client, "qwen3:4b", _article())  # type: ignore[arg-type]
    assert client.calls == 2
