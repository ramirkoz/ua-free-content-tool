from __future__ import annotations

from content_agent.ai_router_v1_2_1 import AIResult
from content_agent.evidence_pack import EvidencePack
from content_agent.evidence_pack_v1_4_rc27 import build_evidence_pack_rc27
from content_agent.models import Article, NewsGroup
from content_agent import rewrite_pipeline_v1_3 as base
from content_agent import rewrite_pipeline_v1_4_rc27 as rc27


def _article(i: int, text: str, *, source: str | None = None) -> Article:
    return Article(
        id=i,
        source_id=i,
        title=f"Подія {i}",
        url=f"https://example.com/{i}",
        raw_text=text,
        status="new",
        published_at="2026-09-07T10:00:00+00:00",
        source_name=source or f"Джерело {i}",
    )


def _group(articles: list[Article]) -> NewsGroup:
    return NewsGroup(
        id=27,
        canonical_title="Зведена подія",
        status="new",
        created_at="2026-09-07T10:00:00+00:00",
        updated_at="2026-09-07T10:00:00+00:00",
        source_count=len(articles),
        articles=articles,
    )


def test_rc27_cuts_service_sections_after_public_text() -> None:
    raw = (
        "ЗАГОЛОВОК: Крапля води створює високий електричний потенціал\n"
        "ТЕКСТ: Дослідники показали, що крапля води під час ковзання поверхнею може накопичувати електричний заряд. "
        "Ефект пов’язують із руйнуванням захисного шару на металі.\n\n"
        "АНАЛІЗ: тут службове пояснення моделі, яке не можна публікувати\n"
        "ФАКТИ: ще одна службова секція"
    )
    payload = rc27.decode_payload_rc27(raw)
    assert payload["headline"] == "Крапля води створює високий електричний потенціал"
    rewrite = str(payload["rewrite"])
    assert "Дослідники показали" in rewrite
    assert "АНАЛІЗ:" not in rewrite
    assert "ФАКТИ:" not in rewrite


def test_rc27_uses_last_complete_public_pair() -> None:
    raw = (
        "ЗАГОЛОВОК: Чернетка\nТЕКСТ: Це перша чернетка тексту, яку не треба брати.\n"
        "АНАЛІЗ: модель вирішила переписати\n"
        "ЗАГОЛОВОК: Фінальний заголовок\n"
        "ТЕКСТ: Це фінальний публічний текст, який треба використати без службового хвоста.\n"
        "ПОЯСНЕННЯ: службовий хвіст"
    )
    payload = rc27.decode_payload_rc27(raw)
    assert payload["headline"] == "Фінальний заголовок"
    assert payload["rewrite"] == "Це фінальний публічний текст, який треба використати без службового хвоста."


def test_rc27_sanitizes_service_tail_inside_json_rewrite() -> None:
    raw = (
        '{"headline":"Фінальний заголовок","rewrite":"Публічний текст достатньої довжини для нормального рерайту.\\n'
        'ANALYSIS: internal service text"}'
    )
    payload = rc27.decode_payload_rc27(raw)
    assert payload["headline"] == "Фінальний заголовок"
    assert payload["rewrite"] == "Публічний текст достатньої довжини для нормального рерайту."


def test_rc27_recoverable_service_tail_does_not_trigger_format_repair(monkeypatch) -> None:
    calls: list[str] = []

    def fake_router_call(prompt: str, local_prompt: str, **kwargs: object) -> AIResult:
        del local_prompt, kwargs
        calls.append(prompt)
        return AIResult(
            "ЗАГОЛОВОК: У місті відкрили центр\n"
            "ТЕКСТ: У місті відкрили центр допомоги. Він працюватиме щодня для мешканців громади.\n"
            "АНАЛІЗ: службова секція моделі",
            "groq",
            "qwen",
            "Qwen / Groq",
            5,
            ("Qwen / Groq",),
        )

    monkeypatch.setattr(base, "_router_call", fake_router_call)
    base._decode_payload = rc27.decode_payload_rc27
    evidence = EvidencePack(
        text="У місті відкрили центр допомоги. Він працюватиме щодня для мешканців громади.",
        source_count=1,
        selected_sentences=2,
        total_sentences=2,
        truncated=False,
    )
    candidate = rc27.candidate_after_router_rc27("PROMPT", "LOCAL", evidence, language="uk", max_candidates=2)
    assert candidate.guard.allowed is True
    assert len(calls) == 1


def test_rc27_multi_source_prompt_explicitly_requires_synthesis() -> None:
    evidence = EvidencePack(
        text="ДЖЕРЕЛО 1\nТЕКСТ:\nФакт А\n---\nДЖЕРЕЛО 2\nТЕКСТ:\nФакт Б",
        source_count=2,
        selected_sentences=2,
        total_sentences=2,
        truncated=False,
    )
    prompt = rc27.cloud_prompt_rc27(_group([_article(1, "Факт А."), _article(2, "Факт Б.")]), evidence, [], "", language="uk")
    assert "Не переписуй одне джерело" in prompt
    assert "деталей з інших джерел" in prompt


def test_rc27_large_group_pack_covers_many_sources_not_one() -> None:
    articles: list[Article] = []
    source1 = " ".join(
        f"У першому джерелі деталь A{i} з числом {1000+i} і важливою назвою ModelX{i}."
        for i in range(12)
    )
    articles.append(_article(1, source1, source="Перший"))
    for i in range(2, 21):
        articles.append(
            _article(
                i,
                f"Унікальна деталь SOURCEWORD{i} підтверджує інший аспект цієї самої події без суперечностей.",
                source=f"Джерело {i}",
            )
        )

    pack = build_evidence_pack_rc27(_group(articles), max_chars=2600)
    represented = sum(1 for i in range(2, 21) if f"SOURCEWORD{i}" in pack.text)
    assert pack.source_count == 20
    assert represented >= 8
    assert len(pack.text) <= 2600


def test_rc27_runtime_install_is_idempotent_and_local_prompt_does_not_recurse() -> None:
    evidence = EvidencePack(
        text="ДЖЕРЕЛО 1\nТЕКСТ:\nФакт А\n---\nДЖЕРЕЛО 2\nТЕКСТ:\nФакт Б",
        source_count=2,
        selected_sentences=2,
        total_sentences=2,
        truncated=False,
    )
    rc27.install_runtime()
    rc27.install_runtime()
    prompt = base._local_prompt(evidence, language="uk")
    assert "Не переписуй одне джерело" in prompt
    assert "ПОТОЧНІ ДОКАЗИ:" in prompt
