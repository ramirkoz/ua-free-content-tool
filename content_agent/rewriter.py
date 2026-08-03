from __future__ import annotations

import re

from .editorial_memory import EditorialExample, format_examples_for_prompt
from .models import Article, NewsGroup, RewriteResult
from .ollama_client import OllamaClient, OllamaError, OllamaTimeoutError
from .publication_text import EDITORIAL_TEXT_LIMIT, core_limit

_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "fact_card": {"type": "string"},
        "rewrite": {"type": "string"},
    },
    "required": ["headline", "fact_card", "rewrite"],
    "additionalProperties": False,
}

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")

_RUSSIAN_UNIQUE_CHARS = frozenset("ыэъёЫЭЪЁ")
_RUSSIAN_WORDS = re.compile(
    r"(?iu)\b(?:что|это|этот|эта|эти|котор(?:ый|ая|ое|ые|ого|ой|ому|ым|ых)|"
    r"также|после|перед|между|был|была|были|будет|должен|должны|"
    r"свою|свои|его|ее|ещ[её]|только|однако|если|чтобы|поскольку|поэтому|"
    r"такая|такой|такое|такие|какая|какой|какие|нада|премьер|"
    r"украинск(?:ий|ая|ие|ого|их)|российск(?:ий|ая|ие|ого|их)|"
    r"военн(?:ый|ая|ые|ого|ых)|солдат(?:ы|ов)?|сообщает|заявил|отметил|призвал|"
    r"выразил|учени(?:я|ях)|ограничени(?:я|й)|использовани(?:е|ю)|выглядели)\b"
)
_UKRAINIAN_WORDS = re.compile(
    r"(?iu)\b(?:що|це|цей|ця|ці|який|яка|яке|які|також|після|між|"
    r"був|була|були|буде|повинен|повинні|мають|свою|свої|його|її|їх|"
    r"вже|ще|лише|однак|якщо|щоб|оскільки|тому|українськ(?:ий|а|і|ого|их)|"
    r"російськ(?:ий|а|і|ого|их)|військов(?:ий|а|і|ого|их)|повідомляє|"
    r"заявив|наголосив|закликав|навчань|обмежень|використання)\b"
)
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_LATIN_RE = re.compile(r"[A-Za-z]")
_CYRILLIC_RE = re.compile(r"[А-Яа-яІіЇїЄєҐґ]")
_ENGLISH_WORDS = re.compile(
    r"(?iu)\b(?:the|and|that|this|these|those|with|from|for|into|about|"
    r"according|sources?|could|would|should|might|likely|appears?|seems?|"
    r"however|therefore|although|while|because|suggests?|indicates?|"
    r"development|military|government|country|reportedly|unclear)\b"
)
_SPECULATIVE_PATTERNS = re.compile(
    r"(?iu)(?:"
    r"\baccording to (?:some|several|alternative) sources?\b|"
    r"\bthis (?:may|might|could) (?:suggest|indicate|mean)\b|"
    r"\bit (?:is|remains) (?:possible|likely|unclear)\b|"
    r"\bperhaps\b|\bseems? to\b|\bwe can assume\b|"
    r"\bможливо\b|\bймовірно\b|\bсхоже,? що\b|"
    r"\bце може свідчити\b|\bможна припустити\b|"
    r"\bважко сказати\b|\bпотребує уточнення\b|"
    r"\bза альтернативними джерелами\b|\bна мою думку\b|"
    r"\bвозможно\b|\bвероятно\b|\bпохоже,? что\b|"
    r"\bэто может свидетельствовать\b|\bможно предположить\b"
    r")"
)
_TOKEN_RE = re.compile(r"(?iu)\b[А-Яа-яІіЇїЄєҐґ'’\-]{4,}\b")
_STOPWORDS = frozenset({
    "який", "яка", "яке", "які", "цього", "також", "після", "перед", "через",
    "було", "була", "були", "буде", "свої", "свою", "його", "вона", "вони",
    "щоб", "тому", "однак", "лише", "може", "мають", "повідомив", "повідомила",
    "которий", "которая", "которое", "которые", "этого", "также", "после", "перед",
    "через", "было", "была", "были", "будет", "свои", "свою", "чтобы", "однако",
    "только", "может", "сообщил", "сообщила",
})


def _ukrainian_language_issue(*values: str) -> str:
    """Return a diagnostic when generated newsroom copy is not Ukrainian.

    The source may be Russian, so a prompt-only instruction is insufficient: small
    local models sometimes mirror the source language. We therefore fail closed
    before anything can be saved or queued. Quotes are checked too because the
    product requirement is an entirely Ukrainian publication.
    """

    text = "\n".join(str(value or "") for value in values).strip()
    text = _URL_RE.sub(" ", text)
    if not text:
        return "Модель повернула порожній текст."

    latin_count = len(_LATIN_RE.findall(text))
    cyrillic_count = len(_CYRILLIC_RE.findall(text))
    english_hits = len(_ENGLISH_WORDS.findall(text))
    # Brand names such as GPS, DTEK or NATO are valid. A sentence or paragraph
    # written mainly in Latin script is not. FIX29 only looked for Russian
    # markers, so a fully English essay slipped through as if it were Ukrainian.
    if english_hits >= 3 or (latin_count >= 24 and latin_count > cyrillic_count):
        return f"виявлено англійський текст або перевагу латиниці ({latin_count} латинських літер)"

    unique = sorted({char for char in text if char in _RUSSIAN_UNIQUE_CHARS})
    if unique:
        return "виявлено російські літери: " + ", ".join(unique)

    russian_hits = len(_RUSSIAN_WORDS.findall(text))
    ukrainian_hits = len(_UKRAINIAN_WORDS.findall(text))
    ukrainian_letters = sum(text.count(char) for char in "іїєґІЇЄҐ")

    if russian_hits >= 2 and russian_hits > ukrainian_hits:
        return f"виявлено російські мовні маркери ({russian_hits})"
    if len(text) >= 180 and russian_hits >= 1 and ukrainian_letters == 0:
        return "текст не містить українських літер і має російські мовні маркери"
    return ""


def _normalize_cyrillic_token(value: str) -> str:
    table = str.maketrans({
        "э": "е", "ё": "е", "ы": "и", "ъ": "",
        "і": "и", "ї": "и", "є": "е", "ґ": "г",
    })
    return value.lower().translate(table).replace("’", "'")


def _content_stems(value: str) -> set[str]:
    stems: set[str] = set()
    for raw in _TOKEN_RE.findall(str(value or "")):
        token = _normalize_cyrillic_token(raw).strip("-' ")
        if len(token) < 4 or token in _STOPWORDS:
            continue
        stems.add(token[:6])
    return stems


def _rewrite_quality_issue(headline: str, rewrite: str, source_text: str) -> str:
    language_issue = _ukrainian_language_issue(headline, rewrite)
    if language_issue:
        return language_issue

    source_plain = " ".join(str(source_text or "").split())
    output_plain = " ".join(f"{headline} {rewrite}".split())
    speculative = _SPECULATIVE_PATTERNS.search(output_plain)
    if speculative and speculative.group(0).lower() not in source_plain.lower():
        return f"виявлено аналітичні домисли замість новинного рерайту: «{speculative.group(0)}»"

    source_stems = _content_stems(source_plain)
    output_stems = _content_stems(output_plain)
    if len(source_stems) >= 4 and len(output_stems) >= 4:
        overlap = len(source_stems & output_stems)
        # This is deliberately conservative. It only rejects an answer that has
        # almost no lexical connection to the supplied facts, not a normal
        # Ukrainian translation of a Russian source.
        if overlap < 2 and overlap / max(1, min(len(source_stems), len(output_stems))) < 0.10:
            return "текст майже не спирається на слова й факти вихідних матеріалів"
    return ""


def _language_repair_prompt(
    title: str,
    source_text: str,
    total_sources: int,
    issue: str,
) -> str:
    return f"""
Попередня відповідь непридатна: {issue}. Не перекладай і не редагуй її.
Заново створи коротку новину ТІЛЬКИ з вихідних матеріалів нижче.

ВИХІДНА МОВА: ВИКЛЮЧНО УКРАЇНСЬКА. Переклади ВЕСЬ текст українською.
Це новинний рерайт, а не аналіз і не міркування. Заборонено додавати
припущення, оцінки, висновки, пояснення від себе, «можливо», «ймовірно»,
«це може свідчити», «за альтернативними джерелами» та подібні фрази,
якщо їх немає у джерелі. Не вигадуй фактів.

Максимум {EDITORIAL_TEXT_LIMIT} символів разом із пробілами. Максимум фактів,
мінімум води. Збережи імена, назви, дати, числа, місця, причини й наслідки.

Поверни лише формат без JSON і markdown:
ЗАГОЛОВОК: нейтральний український заголовок
ФАКТИ: використано джерел {total_sources} із {total_sources}; коротко про уточнення
ТЕКСТ:
1–4 короткі абзаци українською

ПОЧАТКОВИЙ ЗАГОЛОВОК: {title}
МАТЕРІАЛИ ВСІХ ДЖЕРЕЛ:
{source_text}
""".strip()

_PROMO_LINE = re.compile(
    r"(?iu)^(?:insider\s*ua|прислать\s+контент|надіслати\s+контент|"
    r"підписатися|подписаться|реклама|наш\s+бот|джерело\s*:|источник\s*:).*$"
)


def _clean_source_text(value: str) -> str:
    lines: list[str] = []
    for raw_line in str(value or "").splitlines():
        line = " ".join(raw_line.split()).strip()
        if not line or _PROMO_LINE.match(line):
            continue
        lines.append(line)
    return "\n".join(lines)


def _compact_source_excerpt(value: str, limit: int) -> str:
    """Keep the factual core of one source while preserving every source in a block."""

    text = _clean_source_text(value)
    if len(text) <= limit:
        return text
    sentences = [part.strip() for part in _SENTENCE_SPLIT.split(text) if part.strip()]
    if not sentences:
        return _truncate_at_word(text, limit)

    selected_indexes: set[int] = {0}
    for index, sentence in enumerate(sentences):
        has_number = any(char.isdigit() for char in sentence)
        has_quote = '«' in sentence or '"' in sentence
        has_named_detail = len(re.findall(r"(?u)\b[А-ЯІЇЄҐ][а-яіїєґ'’-]{3,}", sentence)) >= 2
        if has_number or has_quote or has_named_detail:
            selected_indexes.add(index)

    selected: list[str] = []
    for index in sorted(selected_indexes):
        sentence = sentences[index]
        candidate = " ".join([*selected, sentence]).strip()
        if len(candidate) <= limit:
            selected.append(sentence)
    if not selected:
        return _truncate_at_word(text, limit)

    # Fill remaining room with untouched sentences in source order.
    for index, sentence in enumerate(sentences):
        if index in selected_indexes:
            continue
        candidate_parts = []
        for original_index, original_sentence in enumerate(sentences):
            if original_index in selected_indexes or original_index == index:
                candidate_parts.append(original_sentence)
        candidate = " ".join(candidate_parts).strip()
        if len(candidate) <= limit:
            selected_indexes.add(index)
    result = " ".join(
        sentence for index, sentence in enumerate(sentences) if index in selected_indexes
    ).strip()
    return result if len(result) <= limit else _truncate_at_word(result, limit)


def _source_payload(item: Article | NewsGroup) -> tuple[str, str, str, bool]:
    if isinstance(item, NewsGroup):
        articles = list(item.articles)
        total = len(articles)
        if not articles:
            return item.canonical_title, item.primary_url, "", item.include_source_link

        # Every source must reach the model, but a local 4B model must not receive
        # an ever-growing wall of copied Telegram text. Build one bounded dossier
        # that keeps a factual excerpt from every article instead of silently
        # dropping article 5 and everything after it.
        maximum_payload = 6_000

        def build_payload(body_budget: int, *, compact_headers: bool = False) -> str:
            blocks: list[str] = [f"У БЛОЦІ ДЖЕРЕЛ: {total}. ВИКОРИСТАТИ ВСІ {total}."]
            for index, article in enumerate(articles, start=1):
                body = _compact_source_excerpt(article.raw_text, body_budget)
                source_name = (article.source_name or "без назви").strip()
                title = article.title.strip()
                if compact_headers:
                    source_name = _truncate_at_word(source_name, 42)
                    title = _truncate_at_word(title, 105)
                    header = f"[{index}/{total}] {source_name} | {title}"
                else:
                    header = (
                        f"ДЖЕРЕЛО {index} ІЗ {total}: {source_name}\n"
                        f"ЗАГОЛОВОК: {title}\n"
                        f"ЧАС: {article.published_at or 'не визначено'}"
                    )
                blocks.append(f"{header}\nТЕКСТ: {body}")
            return "\n\n---\n\n".join(blocks)

        # Start with a fair per-source budget, then shrink all excerpts together.
        # This preserves representation of every source and keeps the whole prompt
        # inside the context window used by qwen3:4b/gemma3:4b.
        body_budget = max(120, min(1_100, 4_700 // max(1, total)))
        payload = build_payload(body_budget)
        while len(payload) > maximum_payload and body_budget > 90:
            over = len(payload) - maximum_payload
            body_budget = max(90, body_budget - max(20, over // max(1, total) + 8))
            payload = build_payload(body_budget)
        if len(payload) > maximum_payload:
            payload = build_payload(70, compact_headers=True)
        if len(payload) > maximum_payload:
            # Extremely large blocks are rare. The final pass still lists every
            # source and its title; source bodies are reduced to tiny factual leads.
            payload = build_payload(35, compact_headers=True)
        return (
            item.canonical_title,
            item.primary_url,
            payload,
            item.include_source_link,
        )
    return item.title, item.url, _clean_source_text(item.raw_text)[:8_000], False


def _source_count(item: Article | NewsGroup) -> int:
    return max(1, len(item.articles)) if isinstance(item, NewsGroup) else 1

def _truncate_at_word(text: str, limit: int) -> str:
    value = " ".join(text.split())
    if len(value) <= limit:
        return value
    if limit <= 1:
        return value[:limit]
    cut = value.rfind(" ", 0, limit)
    if cut < max(20, limit // 2):
        cut = limit - 1
    return value[:cut].rstrip(" ,;:-") + "…"


def fit_text_to_limit(text: str, limit: int) -> str:
    """Fit a base newsroom text locally without a second LLM request.

    Complete sentences are preferred. Only when the first sentence itself is too
    long do we cut at a word boundary. This is intentionally deterministic so
    manual edits in the base text propagate identically to every platform.
    """

    value = text.strip()
    if len(value) <= limit:
        return value
    sentences = [part.strip() for part in _SENTENCE_SPLIT.split(value) if part.strip()]
    selected: list[str] = []
    for sentence in sentences:
        candidate = " ".join([*selected, sentence]).strip()
        if len(candidate) <= limit:
            selected.append(sentence)
            continue
        break
    if selected:
        result = " ".join(selected).strip()
        # Prefer a complete sentence even if some platform capacity remains unused.
        return result[:limit]
    return _truncate_at_word(value, limit)


def fit_factual_text_to_limit(text: str, limit: int) -> str:
    """Keep the densest complete sentences when a model ignores the limit.

    This is the last-resort path after one dedicated Ollama compression request.
    It never invents text. The lead is retained, then sentences containing numbers,
    named entities, quotations and causal markers receive priority. Selected
    sentences are returned in their original order so the result remains readable.
    """

    value = " ".join(str(text or "").split()).strip()
    if len(value) <= limit:
        return value
    sentences = [part.strip() for part in _SENTENCE_SPLIT.split(value) if part.strip()]
    if not sentences:
        return _truncate_at_word(value, limit)
    if len(sentences[0]) > limit:
        return _truncate_at_word(sentences[0], limit)

    def score(index: int, sentence: str) -> float:
        points = 100.0 if index == 0 else max(0.0, 12.0 - index * 0.4)
        points += 8.0 * len(re.findall(r"\b\d+(?:[.,]\d+)?%?\b", sentence))
        points += 5.0 * len(re.findall(r"(?u)\b[А-ЯІЇЄҐ][а-яіїєґ'’-]{3,}", sentence))
        points += 6.0 if ('«' in sentence or '"' in sentence) else 0.0
        points += 5.0 if re.search(r"(?iu)\b(?:через|тому|внаслідок|щоб|допоможе|зможе|за даними|повідомив)\b", sentence) else 0.0
        return points

    selected: set[int] = {0}
    used = len(sentences[0])
    ranked = sorted(
        range(1, len(sentences)),
        key=lambda idx: (-score(idx, sentences[idx]), idx),
    )
    for index in ranked:
        addition = len(sentences[index]) + 1
        if used + addition <= limit:
            selected.add(index)
            used += addition
    result = " ".join(sentence for index, sentence in enumerate(sentences) if index in selected).strip()
    return result if result else _truncate_at_word(value, limit)


def platform_texts_from_base(
    base_text: str,
    *,
    include_source_link: bool,
    source_url: str,
) -> dict[str, str]:
    del include_source_link, source_url
    value = base_text.strip()
    # FIX28 keeps one canonical editorial message. Threads adaptation happens in
    # the publisher as a reply chain, never by truncating the stored text.
    return {platform: value for platform in ("facebook", "threads", "linkedin", "telegram")}


def _fact_card_from_rewrite(text: str, limit: int = 600) -> str:
    value = " ".join(text.split())
    if len(value) <= limit:
        return value
    sentences = [part.strip() for part in _SENTENCE_SPLIT.split(value) if part.strip()]
    selected: list[str] = []
    for sentence in sentences:
        candidate = " ".join([*selected, sentence]).strip()
        if len(candidate) > limit:
            break
        selected.append(sentence)
        if len(candidate) >= 220:
            break
    return " ".join(selected).strip() or _truncate_at_word(value, limit)




def _generate_payload(
    client: OllamaClient,
    model: str,
    prompt: str,
    *,
    num_predict: int,
    temperature: float,
) -> dict[str, object]:
    """Call the modern client while remaining compatible with tiny test/legacy clients."""

    try:
        return client.generate_json(
            model,
            prompt,
            _SCHEMA,
            num_predict=num_predict,
            temperature=temperature,
        )
    except TypeError as exc:
        message = str(exc)
        if "unexpected keyword argument" not in message:
            raise
        return client.generate_json(model, prompt, _SCHEMA)

def _compression_prompt(headline: str, rewrite: str, limit: int) -> str:
    target = max(520, limit - 60)
    return f"""
Стисни вже готову українську новину до максимум {target} символів разом із пробілами.
Це не новий рерайт. Не додавай жодного факту. Збережи всі імена, посади,
дати, числа, місця, причини, наслідки та ключові уточнення. Прибери лише
повтори, вступну воду й стилістичні прикраси. Не залишай російських слів.

Поверни лише формат:
ЗАГОЛОВОК: короткий український заголовок
ТЕКСТ:
стислий текст

ЗАГОЛОВОК: {headline}
ТЕКСТ ДЛЯ СТИСНЕННЯ:
{rewrite}
""".strip()


def _compact_generated_text(
    client: OllamaClient,
    model: str,
    headline: str,
    rewrite: str,
) -> tuple[str, str, bool]:
    if len(rewrite) <= EDITORIAL_TEXT_LIMIT:
        return headline, rewrite, False
    try:
        compacted = _generate_payload(
            client,
            model,
            _compression_prompt(headline, rewrite, EDITORIAL_TEXT_LIMIT),
            num_predict=220,
            temperature=0.02,
        )
        compact_headline = str(compacted.get("headline") or "").strip() or headline
        compact_text = str(compacted.get("rewrite") or "").strip()
        if compact_text and not _ukrainian_language_issue(compact_headline, compact_text):
            if len(compact_text) <= EDITORIAL_TEXT_LIMIT:
                return compact_headline, compact_text, True
            rewrite = compact_text
            headline = compact_headline
    except OllamaError:
        # A length violation must not turn a short, factually usable story into a
        # complete failure. The deterministic sentence-safe fallback is visible
        # to the editor and never invents content.
        pass
    return headline, fit_factual_text_to_limit(rewrite, EDITORIAL_TEXT_LIMIT), True

def rewrite_article(
    client: OllamaClient,
    model: str,
    article: Article | NewsGroup,
    *,
    editorial_examples: list[EditorialExample] | None = None,
) -> RewriteResult:
    title, source_url, source_text, include_source_link = _source_payload(article)
    total_sources = _source_count(article)
    memory_block = format_examples_for_prompt(editorial_examples or [])
    memory_instruction = ""
    if memory_block:
        memory_instruction = f"""

РЕДАКЦІЙНА ПАМ'ЯТЬ. Нижче наведено схожі матеріали, які редактор уже
виправив і схвалив. Наслідуй щільність фактів, порядок викладу та відсутність
води, але не перенось факти з прикладів у нову новину:

{memory_block}
"""
    prompt = f"""
ВИХІДНА МОВА: ВИКЛЮЧНО УКРАЇНСЬКА. Навіть якщо джерела російською,
переклади українською весь текст, включно з цитатами й підписами.
Не залишай російських слів або літер.

Створи одну збірну новину UA FREE за ВСІМА {total_sources} джерелами блока.
Не вважай перше джерело головним автоматично. Зістав усі матеріали, візьми
унікальні факти з кожного, прибери дублікати. Якщо джерела суперечать одне
одному, не вигадуй компроміс: використовуй обережне формулювання і коротко
зазнач суперечність у ФАКТАХ.

Створи ОДИН спільний текст для Facebook, Threads, LinkedIn і Telegram.
Не створюй окремі тексти для соцмереж.
Максимальна довжина тексту: {EDITORIAL_TEXT_LIMIT} символів разом із пробілами.
Збережи максимум перевірених фактів: імена, посади, дати, місця, числа,
цитати та причинно-наслідкові зв'язки. Мінімум води. Не додавай посилань,
хештегів, донатних закликів або пояснень. Коротку новину не роздувай.
Це новинний рерайт, а не аналітика. Не додавай припущень, оцінок, висновків
чи міркувань від себе. Не пиши «можливо», «ймовірно», «це може свідчити»,
«за альтернативними джерелами» та подібне, якщо цього немає у матеріалах.
{memory_instruction}

Поверни лише такий формат, без JSON і markdown:
ЗАГОЛОВОК: нейтральний український заголовок до 180 символів
ФАКТИ: використано джерел {total_sources} із {total_sources}; ключові уточнення або суперечності
ТЕКСТ:
1–4 короткі абзаци українською, не більше {EDITORIAL_TEXT_LIMIT} символів.

ПОЧАТКОВИЙ ЗАГОЛОВОК: {title}
ДЖЕРЕЛО-ПОСИЛАННЯ: {source_url}
МАТЕРІАЛИ ВСІХ ДЖЕРЕЛ:
{source_text}

НАГАДУВАННЯ: використай усі {total_sources} джерел, відповідь українською, текст не довший за {EDITORIAL_TEXT_LIMIT} символів.
""".strip()
    payload = _generate_payload(
        client, model, prompt, num_predict=300, temperature=0.08
    )
    headline = str(payload.get("headline", "")).strip() or title
    rewrite = str(payload.get("rewrite", "")).strip()
    if not rewrite:
        raise OllamaError("Модель повернула порожній рерайт.")

    quality_issue = _rewrite_quality_issue(headline, rewrite, source_text)
    if quality_issue:
        repaired = _generate_payload(
            client,
            model,
            _language_repair_prompt(title, source_text, total_sources, quality_issue),
            num_predict=300,
            temperature=0.02,
        )
        repaired_headline = str(repaired.get("headline", "")).strip()
        repaired_rewrite = str(repaired.get("rewrite", "")).strip()
        if repaired_headline:
            headline = repaired_headline
        rewrite = repaired_rewrite
        second_issue = _rewrite_quality_issue(headline, rewrite, source_text)
        if not rewrite or second_issue:
            detail = second_issue or "модель повернула порожній текст після повторного рерайту"
            raise OllamaError(
                "Ollama двічі повернула непридатний рерайт: "
                f"{detail}. Текст не збережено і не передано в чергу."
            )

    headline, rewrite, auto_compacted = _compact_generated_text(
        client, model, headline, rewrite
    )
    final_quality_issue = _rewrite_quality_issue(headline, rewrite, source_text)
    if final_quality_issue:
        raise OllamaError(
            "Після автоматичного стискання рерайт не пройшов перевірку якості: "
            f"{final_quality_issue}."
        )

    model_fact_card = str(payload.get("fact_card") or "").strip()
    fact_card = model_fact_card or _fact_card_from_rewrite(rewrite)
    source_note = f"Передано моделі джерел: {total_sources} із {total_sources}."
    if not fact_card.startswith(source_note):
        fact_card = f"{source_note}\n{fact_card}".strip()
    return RewriteResult(
        headline=headline,
        fact_card=fact_card,
        rewrite=rewrite,
        platform_texts=platform_texts_from_base(
            rewrite,
            include_source_link=include_source_link,
            source_url=source_url,
        ),
        source_count_used=total_sources,
        source_count_total=total_sources,
        auto_compacted=auto_compacted,
    )


def _model_size_billions(name: str) -> float | None:
    match = re.search(r"(?i)(\d+(?:\.\d+)?)b(?:$|[-_:])", str(name or ""))
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def rewrite_article_with_fallback(
    client: OllamaClient,
    primary_model: str,
    fallback_model: str,
    article: Article | NewsGroup,
    *,
    fallback_client: OllamaClient | None = None,
    editorial_examples: list[EditorialExample] | None = None,
) -> tuple[RewriteResult, str, bool]:
    primary = primary_model.strip()
    fallback = fallback_model.strip()
    if not primary:
        raise OllamaError("Спочатку оберіть установлену модель Ollama.")
    primary_error_text = ""
    try:
        return rewrite_article(client, primary, article, editorial_examples=editorial_examples), primary, False
    except OllamaTimeoutError as primary_timeout:
        # A different fallback may succeed even when it has the same nominal
        # parameter size. FIX25 skipped that attempt and produced a false final
        # failure after 80 seconds, although the second manual try often worked.
        if not fallback or fallback == primary:
            raise
        primary_error_text = str(primary_timeout)
    except OllamaError as primary_error:
        if not fallback or fallback == primary:
            raise
        primary_error_text = str(primary_error)
    try:
        return rewrite_article(
            fallback_client or client,
            fallback,
            article,
            editorial_examples=editorial_examples,
        ), fallback, True
    except OllamaError as fallback_error:
        raise OllamaError(
            f"Основна модель «{primary}» не впоралася: {primary_error_text}\n"
            f"Запасна модель «{fallback}» також не впоралася: {fallback_error}"
        ) from fallback_error

