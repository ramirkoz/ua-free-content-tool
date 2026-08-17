from __future__ import annotations

import json
import re
from collections.abc import Sequence

from .ai_router_v1_2_2 import AIRouterError, run_ai
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


def _json_object_candidates(raw: str) -> list[str]:
    """Return balanced JSON-object candidates from model output.

    Small local models often wrap otherwise valid JSON in one sentence or a
    markdown fence. We accept only syntactically balanced object candidates and
    still validate their fields afterwards, so this is tolerance, not guessing.
    """

    text = _clean_json_text(raw)
    candidates: list[str] = []
    if text.startswith("{") and text.endswith("}"):
        candidates.append(text)

    in_string = False
    escaped = False
    depth = 0
    start = -1
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0 and start >= 0:
                candidate = text[start : index + 1].strip()
                if candidate and candidate not in candidates:
                    candidates.append(candidate)
                start = -1
    return candidates


def _extract_jsonish_string(raw: str, key: str) -> str:
    """Recover a quoted string field from slightly malformed/truncated JSON."""

    text = _clean_json_text(raw)
    match = re.search(rf'(?is)["\']{re.escape(key)}["\']\s*:\s*"', text)
    if not match:
        return ""
    chars: list[str] = []
    escaped = False
    for char in text[match.end() :]:
        if escaped:
            chars.append("\\" + char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            break
        chars.append(char)
    value = "".join(chars)
    encoded = value.replace("\r", "\\r").replace("\n", "\\n")
    try:
        return str(json.loads('"' + encoded + '"')).strip()
    except json.JSONDecodeError:
        return (
            value.replace("\\n", "\n")
            .replace("\\r", "\r")
            .replace("\\t", "\t")
            .replace('\\"', '"')
            .replace("\\\\", "\\")
            .strip()
        )


def _decode_rewrite_payload(raw: str, *, allow_marker_protocol: bool = True) -> dict[str, object]:
    text = _clean_json_text(raw)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        return payload

    for candidate in _json_object_candidates(raw):
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload

    headline = _extract_jsonish_string(raw, "headline")
    fact_card = _extract_jsonish_string(raw, "fact_card")
    rewrite = _extract_jsonish_string(raw, "rewrite")
    if headline and rewrite:
        return {"headline": headline, "fact_card": fact_card, "rewrite": rewrite}

    # Emergency Ollama uses a deliberately cheap marker protocol. Requiring a
    # grammar-constrained JSON object from a CPU-only 4B model was the reason a
    # healthy local model kept timing out after the cloud providers were exhausted.
    marker_headline = re.search(r"(?im)^\s*(?:ЗАГОЛОВОК|HEADLINE)\s*:\s*(.+?)\s*$", text)
    marker_rewrite = re.search(r"(?ims)^\s*(?:ТЕКСТ|РЕРАЙТ|TEXT|ARTICLE)\s*:\s*(.+)\Z", text)
    if allow_marker_protocol and marker_rewrite:
        rewrite = marker_rewrite.group(1).strip()
        headline = marker_headline.group(1).strip() if marker_headline else ""
        if not headline:
            first_line = rewrite.splitlines()[0].strip() if rewrite.splitlines() else ""
            headline = first_line[:180].rstrip(" .!?…")
        if headline and rewrite:
            return {
                "headline": headline,
                "fact_card": _fact_card_from_rewrite(rewrite),
                "rewrite": rewrite,
            }

    raise AIRouterError("AI повернув рерайт не у валідному або відновлюваному форматі.")


def _source_prose(group: NewsGroup) -> str:
    blocks: list[str] = []
    for index, article in enumerate(group.articles, start=1):
        blocks.append(
            f"ДЖЕРЕЛО {index}\nНазва джерела: {article.source_name or 'невідомо'}\n"
            f"Заголовок: {article.title}\nЧас: {article.published_at or 'не визначено'}\n"
            f"URL: {article.url}\nТекст:\n{article.raw_text.strip()}"
        )
    return "\n\n---\n\n".join(blocks)


def _fact_card_from_rewrite(text: str, limit: int = 520) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    cut = max(value.rfind(". ", 0, limit), value.rfind("! ", 0, limit), value.rfind("? ", 0, limit))
    if cut >= 80:
        return value[: cut + 1].strip()
    cut = value.rfind(" ", 0, limit - 1)
    if cut < 80:
        cut = limit - 1
    return value[:cut].rstrip(" ,;:-") + "…"


def _local_source_prose(group: NewsGroup, max_chars: int = 4600) -> str:
    """Compact factual input for the emergency CPU model.

    Cloud models still receive the full editorial prompt and memory. Ollama gets
    every source title plus the most useful source text, but no URLs, graph dump
    or approved-example payload that would waste minutes on a 4B CPU model.
    """

    articles = list(group.articles)
    if not articles:
        return ""
    share = max(650, min(3200, (max_chars - 220) // max(1, len(articles))))
    rows: list[str] = []
    for index, article in enumerate(articles, start=1):
        text = " ".join(str(article.raw_text or "").split())
        rows.append(
            f"ДЖЕРЕЛО {index}: {article.source_name or 'невідомо'}\n"
            f"ЗАГОЛОВОК: {' '.join(str(article.title or '').split())[:260]}\n"
            f"ТЕКСТ: {text[:share]}"
        )
    compact = "\n\n---\n\n".join(rows)
    return compact[:max_chars]


def build_local_rewrite_prompt(group: NewsGroup) -> str:
    source = _local_source_prose(group)
    plain_length = sum(len(str(item.raw_text or "").strip()) for item in group.articles)
    length_rule = (
        "Рерайт: 1 коротке речення, максимум 2."
        if plain_length <= 420
        else "Рерайт: 1–4 короткі абзаци, максимум 900 символів."
    )
    return f"""
Зроби точний новинний рерайт українською. Використовуй ТІЛЬКИ факти з матеріалів нижче.
Не вигадуй причин, оцінок, цитат чи наслідків. {length_rule}

Поверни РІВНО дві секції без JSON, markdown і пояснень:
ЗАГОЛОВОК: короткий нейтральний заголовок
ТЕКСТ: готовий публічний текст

МАТЕРІАЛИ:
{source}
""".strip()


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


def _parse_rewrite_json(raw: str, *, allow_marker_protocol: bool = True) -> dict[str, object]:
    payload = _decode_rewrite_payload(raw, allow_marker_protocol=allow_marker_protocol)
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


def _run_router_with_local_profile(prompt: str, local_prompt: str, *, validator, cloud_tokens: int, local_tokens: int, local_timeout: int):
    try:
        return run_ai(
            prompt,
            validator=validator,
            max_output_tokens=cloud_tokens,
            local_prompt=local_prompt,
            local_max_output_tokens=local_tokens,
            local_timeout_seconds=local_timeout,
            local_repair=False,
        )
    except TypeError as exc:
        # Compatibility for regression/recovery hooks that monkeypatch the older
        # run_ai signature. Production always takes the profiled branch above.
        if "unexpected keyword argument" not in str(exc):
            raise
        return run_ai(prompt, validator=validator, max_output_tokens=cloud_tokens)


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
            payload = _parse_rewrite_json(raw, allow_marker_protocol=False)
        except AIRouterError as exc:
            raise CodexEngineError(str(exc)) from exc
    else:
        local_prompt = build_local_rewrite_prompt(group)
        routed = _run_router_with_local_profile(
            prompt,
            local_prompt,
            validator=_validate_rewrite_json,
            cloud_tokens=1200,
            local_tokens=320,
            local_timeout=120,
        )
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


def _local_topic_prompt(prompt: str, max_chars: int = 4400) -> str:
    text = str(prompt or "").strip()
    if len(text) <= max_chars:
        return text
    marker = "\nКАНДИДАТИ:\n" if "\nКАНДИДАТИ:\n" in text else "\nCANDIDATES:\n"
    if marker not in text:
        return text[:max_chars]
    head, candidates = text.split(marker, 1)
    blocks = candidates.split("\n\n---\n\n")
    kept: list[str] = []
    budget = max(1200, max_chars - min(len(head), 1800) - len(marker) - 160)
    used = 0
    for block in blocks[:10]:
        compact = "\n".join(line[:360] for line in block.splitlines()[:3]).strip()
        if not compact:
            continue
        if kept and used + len(compact) + 7 > budget:
            break
        kept.append(compact)
        used += len(compact) + 7
    local_head = head[:1800].rstrip()
    return (local_head + marker + "\n\n---\n\n".join(kept)).strip()


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
    local_reinforced = _local_topic_prompt(reinforced)
    routed = _run_router_with_local_profile(
        reinforced,
        local_reinforced,
        validator=_validate_topic_output,
        cloud_tokens=900,
        local_tokens=260,
        local_timeout=90,
    )
    if routed.text.strip().casefold() == "none":
        return {}
    return parse_topic_matches(routed.text)
