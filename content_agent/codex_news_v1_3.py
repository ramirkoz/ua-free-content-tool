from __future__ import annotations

import json
import re
from collections.abc import Sequence

from .ai_router_v1_2_1 import AIRouterError, run_ai
from .codex_engine_v1_3 import CodexEngineError, run_codex as _legacy_run_codex
from .editorial_memory import EditorialExample, format_examples_for_prompt
from .models import NewsGroup, RewriteResult
from .publication_text import validate_editorial_text
from .rewriter import platform_texts_from_base
from .topic_search import parse_topic_matches

# Compatibility hook for older regression tests and recovery tooling that
# monkeypatches codex_news_v1_3.run_codex directly. Production uses AI Router.
run_codex = _legacy_run_codex

_CODE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_FORBIDDEN_LINE = re.compile(
    r"(?im)^\s*(?:ЗАГОЛОВОК|HEADLINE|ФАКТИ|FACTS|FACT CARD|АНАЛІЗ|ANALYSIS|ПОЯСНЕННЯ|EXPLANATION)\s*:"
)


def _clean_json_text(raw: str) -> str:
    return _CODE_FENCE.sub("", str(raw or "").strip()).strip()


def _source_prose(group: NewsGroup) -> str:
    blocks: list[str] = []
    for index, article in enumerate(group.articles, start=1):
        blocks.append(
            f"ДЖЕРЕЛО {index}\nНазва джерела: {article.source_name or 'невідомо'}\n"
            f"Заголовок: {article.title}\nЧас: {article.published_at or 'не визначено'}\n"
            f"URL: {article.url}\nТекст:\n{article.raw_text.strip()}"
        )
    return "\n\n---\n\n".join(blocks)


def build_rewrite_prompt(
    group: NewsGroup,
    examples: Sequence[EditorialExample],
    *,
    graph_memory: str = "",
) -> str:
    source = _source_prose(group)
    plain_length = sum(len(str(item.raw_text or "").strip()) for item in group.articles)
    short_rule = (
        "Це дуже коротка новина. Фінальний rewrite має бути 1 речення, максимум 2, якщо інакше губиться важливий факт. Не роздувай повідомлення."
        if plain_length <= 420
        else "Фінальний rewrite має бути 1–4 короткі абзаци, максимум 900 символів."
    )
    examples_text = format_examples_for_prompt(examples, language="uk")
    memory_parts: list[str] = []
    if examples_text:
        memory_parts.append("СХОЖІ СХВАЛЕНІ РЕДАКТОРОМ ПРИКЛАДИ:\n" + examples_text)
    if graph_memory:
        memory_parts.append("РЕЛЕВАНТНИЙ ЛОКАЛЬНИЙ ГРАФ РЕДАКЦІЙНОЇ ПАМ'ЯТІ:\n" + graph_memory)
    memory_block = "\n\n" + "\n\n".join(memory_parts) if memory_parts else ""
    return f"""
Ти виконуєш редакційний рерайт новини для UA FREE.

ПРАВИЛА:
1. Використай факти з УСІХ джерел блока нижче. Не ігноруй уточнення пізніших джерел.
2. Не вигадуй фактів, причин, оцінок, наслідків або цитат, яких немає у вихідних матеріалах.
3. Весь публічний текст виключно українською. Імена, бренди, абревіатури та офіційні назви можна лишати в оригіналі, якщо це потрібно.
4. Максимум фактів, мінімум води. Не додавай вступних міркувань, висновків від себе чи фраз типу «можливо», якщо цього немає у джерелах.
5. {short_rule}
6. Не включай URL, донатний блок, назви службових секцій або пояснення моделі в rewrite.
7. headline має бути коротким нейтральним заголовком.
8. fact_card є короткою службовою довідкою для редактора, а не частиною rewrite.
9. Редакційна пам'ять показує стиль і попередні рішення, але НЕ є джерелом нових фактів для поточної новини.

Поверни РІВНО один JSON-об'єкт без markdown і без тексту до/після нього:
{{"headline":"...","fact_card":"...","rewrite":"..."}}
{memory_block}

МАТЕРІАЛИ БЛОКА:
{source}
""".strip()


def _parse_rewrite_json(raw: str) -> dict[str, object]:
    try:
        payload = json.loads(_clean_json_text(raw))
    except json.JSONDecodeError as exc:
        raise AIRouterError("AI повернув рерайт не у валідному JSON.") from exc
    if not isinstance(payload, dict):
        raise AIRouterError("AI повернув неправильну структуру рерайту.")
    headline = str(payload.get("headline") or "").strip()
    rewrite = str(payload.get("rewrite") or "").strip()
    if not headline or not rewrite:
        raise AIRouterError("AI не повернув заголовок або текст рерайту.")
    if _FORBIDDEN_LINE.search(rewrite) or rewrite.startswith(("{", "[")):
        raise AIRouterError("AI змішав службові секції з публічним текстом.")
    validate_editorial_text(rewrite)
    return payload


def _validate_rewrite_json(raw: str) -> None:
    _parse_rewrite_json(raw)


def rewrite_group_with_codex(
    group: NewsGroup,
    examples: Sequence[EditorialExample],
    *,
    graph_memory: str = "",
) -> RewriteResult:
    prompt = build_rewrite_prompt(group, examples, graph_memory=graph_memory)
    if run_codex is not _legacy_run_codex:
        try:
            raw = run_codex(prompt)
            payload = _parse_rewrite_json(raw)
        except AIRouterError as exc:
            raise CodexEngineError(str(exc)) from exc
    else:
        routed = run_ai(prompt, validator=_validate_rewrite_json)
        payload = _parse_rewrite_json(routed.text)
    headline = str(payload.get("headline") or "").strip()
    fact_card = str(payload.get("fact_card") or "").strip()
    rewrite = str(payload.get("rewrite") or "").strip()
    return RewriteResult(
        headline=headline,
        fact_card=fact_card,
        rewrite=rewrite,
        platform_texts=platform_texts_from_base(
            rewrite,
            include_source_link=bool(group.include_source_link),
            source_url=group.primary_url,
        ),
        source_count_used=len(group.articles),
        source_count_total=len(group.articles),
        auto_compacted=False,
    )


def _validate_topic_output(raw: str) -> None:
    text = str(raw or "").strip()
    if not text:
        raise AIRouterError("AI повернув порожню відповідь для пошуку схожих.")
    parsed = parse_topic_matches(text)
    if parsed:
        return
    lowered = text.casefold()
    if lowered in {"none", "немає", "no matches", "no_match", "0"}:
        return
    raise AIRouterError("AI повернув пошук схожих у неправильному форматі.")


def run_topic_prompt_with_codex(prompt: str, *, graph_memory: str = "") -> dict[int, object]:
    memory = (
        "\n\nПОПЕРЕДНІ РЕДАКЦІЙНІ РІШЕННЯ З ЛОКАЛЬНОЇ ПАМ'ЯТІ:\n"
        + graph_memory
        + "\nВикористовуй їх лише як приклади правил об'єднання, а не як факти поточних кандидатів."
        if graph_memory
        else ""
    )
    reinforced = (
        prompt
        + memory
        + "\n\nПоверни тільки рядки у форматі ID|SCORE|same_event/related/other|коротка причина. "
        "Якщо збігів немає, поверни рівно NONE. Не додавай markdown, вступ або підсумок."
    )
    routed = run_ai(reinforced, validator=_validate_topic_output)
    if routed.text.strip().casefold() == "none":
        return {}
    return parse_topic_matches(routed.text)
