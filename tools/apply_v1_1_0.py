from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    (ROOT / path).write_text(content, encoding="utf-8", newline="\n")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one replacement, found {count}: {old[:100]!r}")
    write(path, text.replace(old, new, 1))


def replace_regex(path: str, pattern: str, replacement: str) -> None:
    text = read(path)
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.S | re.M)
    if count != 1:
        raise RuntimeError(f"{path}: regex replacement count={count}: {pattern[:120]!r}")
    write(path, updated)


# ---------------------------------------------------------------------------
# Config: bilingual behavior, learning controls, independent Meta apps.
# ---------------------------------------------------------------------------
replace_once(
    "content_agent/config.py",
    '    ollama_fallback_model: str = ""\n    meta_app_id: str = ""\n',
    '    ollama_fallback_model: str = ""\n'
    '    ui_language: str = "uk"\n'
    '    learning_enabled: bool = True\n'
    '    learning_examples_limit: int = 3\n'
    '    facebook_app_id: str = ""\n'
    '    facebook_app_secret: str = field(default="", repr=False)\n'
    '    threads_app_id: str = ""\n'
    '    threads_app_secret: str = field(default="", repr=False)\n'
    '    # Legacy shared fields are retained for encrypted-config compatibility.\n'
    '    meta_app_id: str = ""\n',
)
replace_once(
    "content_agent/config.py",
    '    meta_graph_version: str = "v24.0"\n',
    '    meta_graph_version: str = "v26.0"\n',
)
replace_once(
    "content_agent/config.py",
    '    def validate(self) -> None:\n        parts = urlsplit(self.ollama_base_url)\n',
    '    def validate(self) -> None:\n'
    '        if self.ui_language not in {"uk", "en"}:\n'
    '            raise ConfigError("Application language must be uk or en.")\n'
    '        if not (1 <= int(self.learning_examples_limit) <= 12):\n'
    '            raise ConfigError("Learning examples limit must be between 1 and 12.")\n'
    '        parts = urlsplit(self.ollama_base_url)\n',
)
replace_once(
    "content_agent/config.py",
    '        result = cls(**payload)\n        if not result.facebook_pages:\n',
    '        result = cls(**payload)\n'
    '        # Migrate the v1.0 shared Meta application into independent slots.\n'
    '        if not result.facebook_app_id:\n'
    '            result.facebook_app_id = result.meta_app_id\n'
    '        if not result.facebook_app_secret:\n'
    '            result.facebook_app_secret = result.meta_app_secret\n'
    '        if not result.threads_app_id:\n'
    '            result.threads_app_id = result.meta_app_id\n'
    '        if not result.threads_app_secret:\n'
    '            result.threads_app_secret = result.meta_app_secret\n'
    '        result.meta_app_id = result.facebook_app_id or result.threads_app_id or result.meta_app_id\n'
    '        result.meta_app_secret = (\n'
    '            result.facebook_app_secret or result.threads_app_secret or result.meta_app_secret\n'
    '        )\n'
    '        if not result.facebook_pages:\n',
)
replace_once(
    "content_agent/config.py",
    '            result.meta_graph_version = "v24.0"\n',
    '            result.meta_graph_version = "v26.0"\n',
)

# ---------------------------------------------------------------------------
# Editorial retrieval: language-separated examples and bilingual prompt blocks.
# ---------------------------------------------------------------------------
replace_once(
    "content_agent/editorial_memory.py",
    'from typing import Iterable, Mapping, Sequence\n',
    'from typing import Iterable, Mapping, Sequence\n\nfrom .i18n import normalize_language\n',
)
replace_once(
    "content_agent/editorial_memory.py",
    '    "заявив", "заявила", "повідомив", "повідомила", "повідомляє", "йдеться",\n}',
    '    "заявив", "заявила", "повідомив", "повідомила", "повідомляє", "йдеться",\n'
    '    "the", "and", "for", "from", "with", "that", "this", "these", "those",\n'
    '    "was", "were", "will", "have", "has", "had", "said", "reported", "about",\n'
    '}',
)
replace_once(
    "content_agent/editorial_memory.py",
    '    headline: str = ""\n    similarity: float = 0.0\n',
    '    headline: str = ""\n    language: str = "uk"\n    similarity: float = 0.0\n',
)
replace_once(
    "content_agent/editorial_memory.py",
    '                headline=str(row.get("headline") or ""),\n                similarity=score,\n',
    '                headline=str(row.get("headline") or ""),\n'
    '                language=normalize_language(str(row.get("language") or "uk")),\n'
    '                similarity=score,\n',
)
replace_once(
    "content_agent/editorial_memory.py",
    'def rank_topic_candidates(\n    anchor_text: str,\n    candidates: Iterable[Mapping[str, object]],\n    *,\n    feedback: Sequence[Mapping[str, object]] = (),\n    limit: int = 24,\n) -> list[TopicCandidate]:\n',
    'def rank_topic_candidates(\n'
    '    anchor_text: str,\n'
    '    candidates: Iterable[Mapping[str, object]],\n'
    '    *,\n'
    '    feedback: Sequence[Mapping[str, object]] = (),\n'
    '    limit: int = 24,\n'
    '    language: str = "uk",\n'
    ') -> list[TopicCandidate]:\n'
    '    language = normalize_language(language)\n',
)
replace_once(
    "content_agent/editorial_memory.py",
    '        reason = "збіг фактів, назв або учасників"\n        if learned > 0.03:\n            reason = "схоже на ваші попередні ручні об’єднання"\n',
    '        reason = (\n'
    '            "matching facts, names or participants"\n'
    '            if language == "en"\n'
    '            else "збіг фактів, назв або учасників"\n'
    '        )\n'
    '        if learned > 0.03:\n'
    '            reason = (\n'
    '                "similar to your previous manual merges"\n'
    '                if language == "en"\n'
    '                else "схоже на ваші попередні ручні об’єднання"\n'
    '            )\n',
)
replace_regex(
    "content_agent/editorial_memory.py",
    r'def format_examples_for_prompt\(examples: Sequence\[EditorialExample\]\) -> str:\n.*?\n\ndef exclusion_similarity',
    '''def format_examples_for_prompt(\n    examples: Sequence[EditorialExample],\n    *,\n    language: str = "uk",\n) -> str:\n    if not examples:\n        return ""\n    language = normalize_language(language)\n    blocks: list[str] = []\n    for index, item in enumerate(examples, start=1):\n        source = " ".join(item.source_text.split())[:900]\n        final = item.final_text.strip()[:900]\n        if language == "en":\n            blocks.append(\n                f"EXAMPLE {index} (similarity {item.similarity:.2f})\\n"\n                f"SOURCE FACTS: {source}\\n"\n                f"EDITOR'S FINAL TEXT: {final}"\n            )\n        else:\n            blocks.append(\n                f"ПРИКЛАД {index} (схожість {item.similarity:.2f})\\n"\n                f"ВИХІДНІ ФАКТИ: {source}\\n"\n                f"ФІНАЛЬНИЙ ТЕКСТ РЕДАКТОРА: {final}"\n            )\n    return "\\n\\n".join(blocks)\n\n\ndef exclusion_similarity''',
)

# ---------------------------------------------------------------------------
# Topic-search prompt becomes language-aware.
# ---------------------------------------------------------------------------
replace_once(
    "content_agent/topic_search.py",
    'from .editorial_memory import TopicCandidate\n',
    'from .editorial_memory import TopicCandidate\nfrom .i18n import normalize_language\n',
)
replace_regex(
    "content_agent/topic_search.py",
    r'def build_topic_prompt\(.*?\n\ndef parse_topic_matches',
    '''def build_topic_prompt(\n    anchor_title: str,\n    anchor_text: str,\n    candidates: Iterable[Mapping[str, object]],\n    *,\n    feedback: Iterable[Mapping[str, object]] = (),\n    language: str = "uk",\n) -> str:\n    language = normalize_language(language)\n    blocks: list[str] = []\n    for row in candidates:\n        group_id = int(row.get("group_id") or row.get("id") or 0)\n        title = str(row.get("title") or "")\n        text = " ".join(str(row.get("text") or "").split())[:750]\n        if group_id:\n            if language == "en":\n                blocks.append(f"ID {group_id}\\nHEADLINE: {title}\\nTEXT: {text}")\n            else:\n                blocks.append(f"ID {group_id}\\nЗАГОЛОВОК: {title}\\nТЕКСТ: {text}")\n    candidate_block = "\\n\\n---\\n\\n".join(blocks)\n    learned_blocks: list[str] = []\n    for index, row in enumerate(feedback, start=1):\n        if index > 6:\n            break\n        if str(row.get("decision") or "merged") != "merged":\n            continue\n        left = " ".join(str(row.get("anchor_text") or "").split())[:550]\n        right = " ".join(str(row.get("candidate_text") or "").split())[:550]\n        if language == "en":\n            learned_blocks.append(\n                f"LEARNING EXAMPLE {index}: the editor merged these materials as one event.\\n"\n                f"A: {left}\\nB: {right}"\n            )\n        else:\n            learned_blocks.append(\n                f"НАВЧАЛЬНИЙ ПРИКЛАД {index}: редактор об'єднав ці матеріали як одну подію.\\n"\n                f"A: {left}\\nB: {right}"\n            )\n    if language == "en":\n        learned_block = "\\n\\n".join(learned_blocks) or "There are no learning examples yet."\n        return f"""\nYou help an editor find reports about one specific news event.\nDo not merge or rewrite anything. Classify each candidate as:\n- same_event: the same event, a direct update, consequence, or reaction to it;\n- related: a close topic but a different event;\n- other: unrelated to this event.\n\nThe 0–100 score is confidence that the candidate is same_event. Do not inflate\nthe score because of generic shared words. Consider date, place, participants,\nnumbers, object, and causal connection. Previous manual merges are examples of\ngrouping logic only; never copy facts from them.\n\nPREVIOUS MANUAL MERGES:\n{learned_block}\n\nReturn ONLY one line per candidate:\nID|SCORE|same_event/related/other|short reason\n\nANCHOR STORY:\nHEADLINE: {anchor_title}\nTEXT: {" ".join(anchor_text.split())[:1800]}\n\nCANDIDATES:\n{candidate_block}\n""".strip()\n    learned_block = "\\n\\n".join(learned_blocks) or "Навчальних прикладів ще немає."\n    return f"""\nТи допомагаєш редактору знайти матеріали про одну конкретну новинну подію.\nНе об'єднуй самостійно і не переписуй тексти. Для кожного кандидата визнач:\n- same_event: та сама подія, уточнення, наслідки або реакція саме на неї;\n- related: близька тема, але інша подія;\n- other: не стосується цієї події.\n\nОцінка 0–100 має показувати впевненість, що це same_event. Не завищуй оцінку\nлише через однакові загальні слова. Враховуй дату, місце, учасників, числа,\nоб'єкт і причинно-наслідковий зв'язок. Попередні ручні об'єднання є лише\nприкладами логіки групування; не перенось із них факти.\n\nПОПЕРЕДНІ РУЧНІ ОБ'ЄДНАННЯ:\n{learned_block}\n\nПоверни ТІЛЬКИ по одному рядку на кандидата:\nID|ОЦІНКА|same_event/related/other|коротка причина\n\nОПОРНА НОВИНА:\nЗАГОЛОВОК: {anchor_title}\nТЕКСТ: {" ".join(anchor_text.split())[:1800]}\n\nКАНДИДАТИ:\n{candidate_block}\n""".strip()\n\n\ndef parse_topic_matches''',
)

# ---------------------------------------------------------------------------
# Rewriter: append compatible v1.1 implementations that override v1.0 functions.
# ---------------------------------------------------------------------------
rewriter = read("content_agent/rewriter.py")
if "# v1.1 bilingual rewrite implementation" not in rewriter:
    rewriter += r'''

# v1.1 bilingual rewrite implementation. These definitions intentionally appear
# last so legacy callers keep the same public API while gaining a language option.
from .i18n import normalize_language, output_language_instruction, prompt_labels


def _english_language_issue(*values: str) -> str:
    text = _URL_RE.sub(" ", "\n".join(str(value or "") for value in values).strip())
    if not text:
        return "the model returned empty text"
    latin_count = len(_LATIN_RE.findall(text))
    cyrillic_count = len(_CYRILLIC_RE.findall(text))
    if cyrillic_count >= 30 and cyrillic_count > latin_count:
        return f"Cyrillic prose detected ({cyrillic_count} Cyrillic letters)"
    return ""


def _language_issue(language: str, *values: str) -> str:
    return _english_language_issue(*values) if normalize_language(language) == "en" else _ukrainian_language_issue(*values)


def _rewrite_quality_issue_v11(
    headline: str,
    rewrite: str,
    source_text: str,
    language: str,
) -> str:
    language_issue = _language_issue(language, headline, rewrite)
    if language_issue:
        return language_issue
    source_plain = " ".join(str(source_text or "").split())
    output_plain = " ".join(f"{headline} {rewrite}".split())
    speculative = _SPECULATIVE_PATTERNS.search(output_plain)
    if speculative and speculative.group(0).lower() not in source_plain.lower():
        return f"unsupported analysis or speculation detected: {speculative.group(0)}"
    # Lexical overlap validation is reliable for Ukrainian/Russian source pairs.
    # English output may be a full translation, so language mode uses the stricter
    # no-speculation and no-empty checks without a false cross-language rejection.
    if normalize_language(language) == "uk":
        source_stems = _content_stems(source_plain)
        output_stems = _content_stems(output_plain)
        if len(source_stems) >= 4 and len(output_stems) >= 4:
            overlap = len(source_stems & output_stems)
            if overlap < 2 and overlap / max(1, min(len(source_stems), len(output_stems))) < 0.10:
                return "текст майже не спирається на слова й факти вихідних матеріалів"
    return ""


def _language_repair_prompt_v11(
    title: str,
    source_text: str,
    total_sources: int,
    issue: str,
    language: str,
) -> str:
    labels = prompt_labels(language)
    if normalize_language(language) == "en":
        return f"""
The previous answer is unusable: {issue}. Do not edit or translate it. Start again
from the source materials below. Write a concise factual news rewrite in ENGLISH
ONLY. Do not add assumptions, analysis, explanations, or facts that are absent
from the sources. Maximum {EDITORIAL_TEXT_LIMIT} characters including spaces.
Preserve names, titles, dates, numbers, places, causes, and consequences.

Return only this structure:
{labels['headline']}: neutral English headline
{labels['facts']}: used {total_sources} of {total_sources} sources; brief conflicts or clarifications
{labels['text']}:
1–4 short English paragraphs

{labels['source_title']}: {title}
{labels['materials']}:
{source_text}
""".strip()
    return _language_repair_prompt(title, source_text, total_sources, issue)


def _compression_prompt_v11(headline: str, rewrite: str, limit: int, language: str) -> str:
    target = max(520, limit - 60)
    if normalize_language(language) == "en":
        return f"""
Shorten this finished English news story to at most {target} characters including
spaces. Do not add facts. Preserve names, positions, dates, numbers, places,
causes, consequences, and key clarifications. Remove only repetition and filler.
Return JSON fields headline, fact_card, rewrite.

HEADLINE: {headline}
TEXT TO SHORTEN:
{rewrite}
""".strip()
    return _compression_prompt(headline, rewrite, limit)


def _compact_generated_text_v11(
    client: OllamaClient,
    model: str,
    headline: str,
    rewrite: str,
    language: str,
) -> tuple[str, str, bool]:
    if len(rewrite) <= EDITORIAL_TEXT_LIMIT:
        return headline, rewrite, False
    try:
        compacted = _generate_payload(
            client,
            model,
            _compression_prompt_v11(headline, rewrite, EDITORIAL_TEXT_LIMIT, language),
            num_predict=220,
            temperature=0.02,
        )
        compact_headline = str(compacted.get("headline") or "").strip() or headline
        compact_text = str(compacted.get("rewrite") or "").strip()
        if compact_text and not _language_issue(language, compact_headline, compact_text):
            if len(compact_text) <= EDITORIAL_TEXT_LIMIT:
                return compact_headline, compact_text, True
            rewrite = compact_text
            headline = compact_headline
    except OllamaError:
        pass
    return headline, fit_factual_text_to_limit(rewrite, EDITORIAL_TEXT_LIMIT), True


def rewrite_article(
    client: OllamaClient,
    model: str,
    article: Article | NewsGroup,
    *,
    editorial_examples: list[EditorialExample] | None = None,
    language: str = "uk",
) -> RewriteResult:
    language = normalize_language(language)
    title, source_url, source_text, include_source_link = _source_payload(article)
    total_sources = _source_count(article)
    labels = prompt_labels(language)
    memory_block = format_examples_for_prompt(editorial_examples or [], language=language)
    if language == "en":
        memory_instruction = (
            "\n\nEDITORIAL MEMORY. Follow the factual density, ordering, and lack of filler "
            "in these editor-approved examples. Never copy their facts into the new story:\n\n"
            + memory_block
            if memory_block
            else ""
        )
        instructions = f"""
{output_language_instruction(language)}
Create one consolidated UA FREE news story from ALL {total_sources} sources in the
block. Compare them, keep unique facts from each, remove duplicates, and mention
real source conflicts briefly in FACTS. Do not invent a compromise.

Create ONE shared text for Facebook, Threads, LinkedIn, and Telegram. Maximum
{EDITORIAL_TEXT_LIMIT} characters including spaces. Preserve verified names,
positions, dates, places, numbers, quotations, causes, and consequences. No URLs,
hashtags, fundraising calls, analysis, guesses, conclusions, or filler.
{memory_instruction}

Return JSON with exactly headline, fact_card, rewrite. The rewrite must contain
1–4 short English paragraphs. fact_card must state that {total_sources} of
{total_sources} sources were used and note important clarifications or conflicts.

{labels['source_title']}: {title}
SOURCE URL: {source_url}
{labels['materials']}:
{source_text}
""".strip()
    else:
        memory_instruction = (
            "\n\nРЕДАКЦІЙНА ПАМ'ЯТЬ. Наслідуй щільність фактів, порядок викладу та "
            "відсутність води у схвалених прикладах. Не перенось їхні факти:\n\n"
            + memory_block
            if memory_block
            else ""
        )
        instructions = f"""
{output_language_instruction(language)} Не залишай російських слів або літер.
Створи одну збірну новину UA FREE за ВСІМА {total_sources} джерелами блока.
Зістав усі матеріали, візьми унікальні факти з кожного та прибери дублікати.
Реальні суперечності коротко зазнач у ФАКТАХ, нічого не вигадуючи.

Створи ОДИН спільний текст для Facebook, Threads, LinkedIn і Telegram до
{EDITORIAL_TEXT_LIMIT} символів разом із пробілами. Збережи перевірені імена,
посади, дати, місця, числа, цитати, причини й наслідки. Без посилань, хештегів,
донатних закликів, домислів, оцінок, висновків або води.
{memory_instruction}

Поверни JSON лише з полями headline, fact_card, rewrite. rewrite має містити
1–4 короткі абзаци українською. fact_card має вказати, що використано
{total_sources} із {total_sources} джерел, і назвати важливі уточнення чи суперечності.

{labels['source_title']}: {title}
ДЖЕРЕЛО-ПОСИЛАННЯ: {source_url}
{labels['materials']}:
{source_text}
""".strip()

    payload = _generate_payload(client, model, instructions, num_predict=300, temperature=0.08)
    headline = str(payload.get("headline") or "").strip() or title
    rewrite = str(payload.get("rewrite") or "").strip()
    if not rewrite:
        raise OllamaError("The model returned an empty rewrite." if language == "en" else "Модель повернула порожній рерайт.")
    issue = _rewrite_quality_issue_v11(headline, rewrite, source_text, language)
    if issue:
        repaired = _generate_payload(
            client,
            model,
            _language_repair_prompt_v11(title, source_text, total_sources, issue, language),
            num_predict=300,
            temperature=0.02,
        )
        headline = str(repaired.get("headline") or "").strip() or headline
        rewrite = str(repaired.get("rewrite") or "").strip()
        second_issue = _rewrite_quality_issue_v11(headline, rewrite, source_text, language)
        if not rewrite or second_issue:
            detail = second_issue or ("empty text after repair" if language == "en" else "порожній текст після повтору")
            raise OllamaError(
                f"Ollama returned an unusable rewrite twice: {detail}." if language == "en"
                else f"Ollama двічі повернула непридатний рерайт: {detail}."
            )
    headline, rewrite, auto_compacted = _compact_generated_text_v11(
        client, model, headline, rewrite, language
    )
    final_issue = _rewrite_quality_issue_v11(headline, rewrite, source_text, language)
    if final_issue:
        raise OllamaError(
            f"The compacted rewrite failed quality validation: {final_issue}." if language == "en"
            else f"Після стискання рерайт не пройшов перевірку: {final_issue}."
        )
    model_fact_card = str(payload.get("fact_card") or "").strip()
    fact_card = model_fact_card or _fact_card_from_rewrite(rewrite)
    source_note = (
        f"Sources provided to the model: {total_sources} of {total_sources}."
        if language == "en"
        else f"Передано моделі джерел: {total_sources} із {total_sources}."
    )
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


def rewrite_article_with_fallback(
    client: OllamaClient,
    primary_model: str,
    fallback_model: str,
    article: Article | NewsGroup,
    *,
    fallback_client: OllamaClient | None = None,
    editorial_examples: list[EditorialExample] | None = None,
    language: str = "uk",
) -> tuple[RewriteResult, str, bool]:
    primary = primary_model.strip()
    fallback = fallback_model.strip()
    language = normalize_language(language)
    if not primary:
        raise OllamaError(
            "Select an installed Ollama model first." if language == "en"
            else "Спочатку оберіть установлену модель Ollama."
        )
    primary_error_text = ""
    try:
        return (
            rewrite_article(
                client,
                primary,
                article,
                editorial_examples=editorial_examples,
                language=language,
            ),
            primary,
            False,
        )
    except OllamaError as primary_error:
        if not fallback or fallback == primary:
            raise
        primary_error_text = str(primary_error)
    try:
        return (
            rewrite_article(
                fallback_client or client,
                fallback,
                article,
                editorial_examples=editorial_examples,
                language=language,
            ),
            fallback,
            True,
        )
    except OllamaError as fallback_error:
        if language == "en":
            raise OllamaError(
                f"Primary model {primary!r} failed: {primary_error_text}\n"
                f"Fallback model {fallback!r} also failed: {fallback_error}"
            ) from fallback_error
        raise OllamaError(
            f"Основна модель «{primary}» не впоралася: {primary_error_text}\n"
            f"Запасна модель «{fallback}» також не впоралася: {fallback_error}"
        ) from fallback_error
'''
    write("content_agent/rewriter.py", rewriter)

# ---------------------------------------------------------------------------
# Database schema v8 and explicit learning connectors.
# ---------------------------------------------------------------------------
replace_once(
    "content_agent/database.py",
    'DATABASE_SCHEMA_VERSION = 7\n',
    'DATABASE_SCHEMA_VERSION = 8\n',
)
replace_once(
    "content_agent/database.py",
    "                    headline TEXT NOT NULL DEFAULT '',\n                    created_at TEXT NOT NULL,\n                    UNIQUE(source_fingerprint, final_text)\n",
    "                    headline TEXT NOT NULL DEFAULT '',\n"
    "                    language TEXT NOT NULL DEFAULT 'uk' CHECK(language IN ('uk','en')),\n"
    "                    created_at TEXT NOT NULL,\n"
    "                    UNIQUE(source_fingerprint, final_text, language)\n",
)
replace_once(
    "content_agent/database.py",
    "                    candidate_text TEXT NOT NULL,\n                    created_at TEXT NOT NULL,\n                    UNIQUE(anchor_signature, candidate_signature, decision)\n",
    "                    candidate_text TEXT NOT NULL,\n"
    "                    language TEXT NOT NULL DEFAULT 'uk' CHECK(language IN ('uk','en')),\n"
    "                    created_at TEXT NOT NULL,\n"
    "                    UNIQUE(anchor_signature, candidate_signature, decision, language)\n",
)
replace_once(
    "content_agent/database.py",
    "                CREATE INDEX IF NOT EXISTS idx_content_exclusions_active\n                    ON content_exclusions(active, updated_at DESC, id DESC);\n\n                CREATE TABLE IF NOT EXISTS queue_text_migrations (\n",
    "                CREATE INDEX IF NOT EXISTS idx_content_exclusions_active\n"
    "                    ON content_exclusions(active, updated_at DESC, id DESC);\n\n"
    "                CREATE TABLE IF NOT EXISTS learning_events (\n"
    "                    id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
    "                    event_type TEXT NOT NULL,\n"
    "                    language TEXT NOT NULL DEFAULT 'uk' CHECK(language IN ('uk','en')),\n"
    "                    group_id INTEGER,\n"
    "                    anchor_group_id INTEGER,\n"
    "                    payload_json TEXT NOT NULL DEFAULT '{}',\n"
    "                    created_at TEXT NOT NULL\n"
    "                );\n"
    "                CREATE INDEX IF NOT EXISTS idx_learning_events_lookup\n"
    "                    ON learning_events(language,event_type,created_at DESC,id DESC);\n\n"
    "                CREATE TABLE IF NOT EXISTS queue_text_migrations (\n",
)
replace_once(
    "content_agent/database.py",
    '            batch_columns = self._columns(db, "publication_batches")\n',
    '            editorial_columns = self._columns(db, "editorial_examples")\n'
    '            if "language" not in editorial_columns:\n'
    '                db.execute("ALTER TABLE editorial_examples ADD COLUMN language TEXT NOT NULL DEFAULT \'uk\'")\n'
    '            topic_columns = self._columns(db, "topic_merge_feedback")\n'
    '            if "language" not in topic_columns:\n'
    '                db.execute("ALTER TABLE topic_merge_feedback ADD COLUMN language TEXT NOT NULL DEFAULT \'uk\'")\n'
    '            batch_columns = self._columns(db, "publication_batches")\n',
)
replace_regex(
    "content_agent/database.py",
    r'def list_editorial_examples\(self, limit: int = 500\).*?return cursor\.rowcount == 1\n',
    '''def list_editorial_examples(\n        self,\n        limit: int = 500,\n        *,\n        language: str | None = None,\n    ) -> list[dict[str, object]]:\n        query = (\n            "SELECT id,group_id,source_text,ai_draft_text,final_text,headline,language,created_at "\n            "FROM editorial_examples"\n        )\n        params: list[object] = []\n        if language is not None:\n            query += " WHERE language=?"\n            params.append("en" if str(language).lower() == "en" else "uk")\n        query += " ORDER BY id DESC LIMIT ?"\n        params.append(max(1, int(limit)))\n        with self.connect() as db:\n            rows = db.execute(query, params).fetchall()\n        return [dict(row) for row in rows]\n\n    def editorial_example_count(self, *, language: str | None = None) -> int:\n        with self.connect() as db:\n            if language is None:\n                row = db.execute("SELECT COUNT(*) FROM editorial_examples").fetchone()\n            else:\n                row = db.execute(\n                    "SELECT COUNT(*) FROM editorial_examples WHERE language=?",\n                    ("en" if str(language).lower() == "en" else "uk",),\n                ).fetchone()\n        return int(row[0] or 0)\n\n    def record_editorial_example(\n        self,\n        group_id: int,\n        *,\n        final_text: str,\n        headline: str,\n        language: str = "uk",\n    ) -> bool:\n        group = self.get_group(int(group_id))\n        source_text = group.combined_text.strip()\n        final = str(final_text or "").strip()\n        if not source_text or not final:\n            return False\n        lang = "en" if str(language).lower() == "en" else "uk"\n        fingerprint = hashlib.sha256(source_text.encode("utf-8")).hexdigest()\n        with self.connect() as db:\n            cursor = db.execute(\n                """\n                INSERT OR IGNORE INTO editorial_examples(\n                    group_id,source_fingerprint,source_text,ai_draft_text,final_text,headline,language,created_at\n                ) VALUES(?,?,?,?,?,?,?,?)\n                """,\n                (\n                    int(group_id),\n                    fingerprint,\n                    source_text,\n                    group.ai_draft_text,\n                    final,\n                    str(headline or "").strip(),\n                    lang,\n                    _iso(),\n                ),\n            )\n        return cursor.rowcount == 1\n''',
)
replace_once(
    "content_agent/database.py",
    '        decision: str = "merged",\n    ) -> bool:\n',
    '        decision: str = "merged",\n        language: str = "uk",\n    ) -> bool:\n',
)
replace_once(
    "content_agent/database.py",
    '                INSERT OR IGNORE INTO topic_merge_feedback(\n                    anchor_signature,candidate_signature,decision,anchor_text,candidate_text,created_at\n                ) VALUES(?,?,?,?,?,?)\n                """,\n                (left_sig, right_sig, decision, left, right, _iso()),\n',
    '                INSERT OR IGNORE INTO topic_merge_feedback(\n'
    '                    anchor_signature,candidate_signature,decision,anchor_text,candidate_text,language,created_at\n'
    '                ) VALUES(?,?,?,?,?,?,?)\n'
    '                """,\n'
    '                (\n'
    '                    left_sig, right_sig, decision, left, right,\n'
    '                    "en" if str(language).lower() == "en" else "uk", _iso(),\n'
    '                ),\n',
)
replace_regex(
    "content_agent/database.py",
    r'def list_topic_feedback\(self, limit: int = 1000\).*?return \[dict\(row\) for row in rows\]\n',
    '''def list_topic_feedback(\n        self,\n        limit: int = 1000,\n        *,\n        language: str | None = None,\n    ) -> list[dict[str, object]]:\n        query = "SELECT id,decision,anchor_text,candidate_text,language,created_at FROM topic_merge_feedback"\n        params: list[object] = []\n        if language is not None:\n            query += " WHERE language=?"\n            params.append("en" if str(language).lower() == "en" else "uk")\n        query += " ORDER BY id DESC LIMIT ?"\n        params.append(max(1, int(limit)))\n        with self.connect() as db:\n            rows = db.execute(query, params).fetchall()\n        return [dict(row) for row in rows]\n''',
)
replace_once(
    "content_agent/database.py",
    '                    "published_at": group.last_published_at or "",\n',
    '                    "published_at": group.last_published_at or "",\n'
    '                    "url": group.primary_url,\n',
)
replace_once(
    "content_agent/database.py",
    '    def set_group_options(self, group_id: int, *, include_source_link: bool) -> None:\n',
    '''    def record_learning_event(\n        self,\n        event_type: str,\n        *,\n        language: str = "uk",\n        group_id: int | None = None,\n        anchor_group_id: int | None = None,\n        payload: dict[str, object] | None = None,\n    ) -> int:\n        event = str(event_type or "").strip()\n        if not event:\n            raise ValueError("event_type is required")\n        lang = "en" if str(language).lower() == "en" else "uk"\n        with self.connect() as db:\n            cursor = db.execute(\n                """\n                INSERT INTO learning_events(\n                    event_type,language,group_id,anchor_group_id,payload_json,created_at\n                ) VALUES(?,?,?,?,?,?)\n                """,\n                (\n                    event, lang, group_id, anchor_group_id,\n                    json.dumps(payload or {}, ensure_ascii=False, sort_keys=True), _iso(),\n                ),\n            )\n        return int(cursor.lastrowid)\n\n    def list_learning_events(\n        self,\n        *,\n        language: str | None = None,\n        event_type: str | None = None,\n        limit: int = 1000,\n    ) -> list[dict[str, object]]:\n        query = "SELECT * FROM learning_events"\n        clauses: list[str] = []\n        params: list[object] = []\n        if language is not None:\n            clauses.append("language=?")\n            params.append("en" if str(language).lower() == "en" else "uk")\n        if event_type:\n            clauses.append("event_type=?")\n            params.append(str(event_type))\n        if clauses:\n            query += " WHERE " + " AND ".join(clauses)\n        query += " ORDER BY id DESC LIMIT ?"\n        params.append(max(1, int(limit)))\n        with self.connect() as db:\n            rows = db.execute(query, params).fetchall()\n        result: list[dict[str, object]] = []\n        for row in rows:\n            item = dict(row)\n            item["payload"] = self._safe_json(str(item.pop("payload_json", "{}")), {})\n            result.append(item)\n        return result\n\n    def learning_stats(self) -> dict[str, object]:\n        with self.connect() as db:\n            events = int(db.execute("SELECT COUNT(*) FROM learning_events").fetchone()[0] or 0)\n            examples = {\n                str(row["language"]): int(row["count"] or 0)\n                for row in db.execute(\n                    "SELECT language,COUNT(*) AS count FROM editorial_examples GROUP BY language"\n                ).fetchall()\n            }\n            feedback = int(db.execute("SELECT COUNT(*) FROM topic_merge_feedback").fetchone()[0] or 0)\n            exclusions = int(db.execute("SELECT COUNT(*) FROM content_exclusions WHERE active=1").fetchone()[0] or 0)\n        return {\n            "events": events,\n            "editorial_examples": examples,\n            "topic_feedback": feedback,\n            "active_exclusions": exclusions,\n        }\n\n    def export_learning_data(self, path: Path) -> Path:\n        payload = {\n            "format": "UA_FREE_LEARNING_V1",\n            "exported_at": _iso(),\n            "editorial_examples": self.list_editorial_examples(limit=100000),\n            "topic_feedback": self.list_topic_feedback(limit=100000),\n            "content_exclusions": self.list_content_exclusions(active_only=False, limit=100000),\n            "learning_events": self.list_learning_events(limit=100000),\n        }\n        target = Path(path)\n        target.parent.mkdir(parents=True, exist_ok=True)\n        target.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")\n        return target\n\n    def import_learning_data(self, path: Path) -> dict[str, int]:\n        payload = json.loads(Path(path).read_text(encoding="utf-8"))\n        if not isinstance(payload, dict) or payload.get("format") != "UA_FREE_LEARNING_V1":\n            raise ValueError("Unsupported learning-data file.")\n        counts = {"editorial_examples": 0, "topic_feedback": 0, "content_exclusions": 0, "learning_events": 0}\n        with self.connect() as db:\n            db.execute("BEGIN IMMEDIATE")\n            try:\n                for row in payload.get("editorial_examples", []):\n                    if not isinstance(row, dict):\n                        continue\n                    cursor = db.execute(\n                        """\n                        INSERT OR IGNORE INTO editorial_examples(\n                            group_id,source_fingerprint,source_text,ai_draft_text,final_text,headline,language,created_at\n                        ) VALUES(?,?,?,?,?,?,?,?)\n                        """,\n                        (\n                            row.get("group_id"),\n                            hashlib.sha256(str(row.get("source_text") or "").encode("utf-8")).hexdigest(),\n                            str(row.get("source_text") or ""),\n                            str(row.get("ai_draft_text") or ""),\n                            str(row.get("final_text") or ""),\n                            str(row.get("headline") or ""),\n                            "en" if str(row.get("language") or "uk").lower() == "en" else "uk",\n                            str(row.get("created_at") or _iso()),\n                        ),\n                    )\n                    counts["editorial_examples"] += int(bool(cursor.rowcount))\n                for row in payload.get("topic_feedback", []):\n                    if not isinstance(row, dict):\n                        continue\n                    left = " ".join(str(row.get("anchor_text") or "").split())\n                    right = " ".join(str(row.get("candidate_text") or "").split())\n                    if not left or not right:\n                        continue\n                    left_sig = hashlib.sha256(left.encode("utf-8")).hexdigest()\n                    right_sig = hashlib.sha256(right.encode("utf-8")).hexdigest()\n                    if right_sig < left_sig:\n                        left_sig, right_sig, left, right = right_sig, left_sig, right, left\n                    cursor = db.execute(\n                        """\n                        INSERT OR IGNORE INTO topic_merge_feedback(\n                            anchor_signature,candidate_signature,decision,anchor_text,candidate_text,language,created_at\n                        ) VALUES(?,?,?,?,?,?,?)\n                        """,\n                        (left_sig, right_sig, str(row.get("decision") or "merged"), left, right,\n                         "en" if str(row.get("language") or "uk").lower() == "en" else "uk",\n                         str(row.get("created_at") or _iso())),\n                    )\n                    counts["topic_feedback"] += int(bool(cursor.rowcount))\n                for row in payload.get("learning_events", []):\n                    if not isinstance(row, dict):\n                        continue\n                    cursor = db.execute(\n                        """\n                        INSERT INTO learning_events(\n                            event_type,language,group_id,anchor_group_id,payload_json,created_at\n                        ) VALUES(?,?,?,?,?,?)\n                        """,\n                        (str(row.get("event_type") or "imported"),\n                         "en" if str(row.get("language") or "uk").lower() == "en" else "uk",\n                         row.get("group_id"), row.get("anchor_group_id"),\n                         json.dumps(row.get("payload") or {}, ensure_ascii=False, sort_keys=True),\n                         str(row.get("created_at") or _iso())),\n                    )\n                    counts["learning_events"] += int(bool(cursor.rowcount))\n                db.execute("COMMIT")\n            except Exception:\n                db.execute("ROLLBACK")\n                raise\n        return counts\n\n    def clear_learning_history(self) -> None:\n        with self.connect() as db:\n            db.execute("BEGIN IMMEDIATE")\n            try:\n                db.execute("DELETE FROM editorial_examples")\n                db.execute("DELETE FROM topic_merge_feedback")\n                db.execute("DELETE FROM learning_events")\n                db.execute("COMMIT")\n            except Exception:\n                db.execute("ROLLBACK")\n                raise\n\n    def set_group_options(self, group_id: int, *, include_source_link: bool) -> None:\n''',
)

# ---------------------------------------------------------------------------
# Main window: localized UI, focused candidate dialog, better inbox ergonomics.
# ---------------------------------------------------------------------------
replace_once(
    "content_agent/ui/main_window.py",
    'from ..google_drive import (\n',
    'from ..i18n import (\n'
    '    LANGUAGE_LABELS,\n'
    '    language_from_label,\n'
    '    language_label,\n'
    '    localize_widget_tree,\n'
    '    normalize_language,\n'
    '    original_text,\n'
    '    tr,\n'
    ')\n'
    'from ..google_drive import (\n',
)
replace_once(
    "content_agent/ui/main_window.py",
    'from .queue_migration_dialog import QueueMigrationDialog\n',
    'from .queue_migration_dialog import QueueMigrationDialog\n'
    'from .topic_candidates_dialog import TopicCandidatesDialog\n',
)
replace_once(
    "content_agent/ui/main_window.py",
    '    "У роботі": "draft",\n',
    '',
)
replace_once(
    "content_agent/ui/main_window.py",
    '    "draft": "у роботі",\n',
    '    "draft": "",\n',
)
replace_once(
    "content_agent/ui/main_window.py",
    '        root.title("UA FREE Content Tool — R8 FIX30")\n',
    '        root.title("UA FREE Content Tool — v1.1.0")\n',
)
replace_once(
    "content_agent/ui/main_window.py",
    '        self._build_settings_tab()\n\n        ttk.Label(root, textvariable=self.status_var, anchor="w").pack(fill="x", padx=10, pady=(2, 8))\n',
    '        self._build_settings_tab()\n'
    '        self._apply_language(refresh=False)\n\n'
    '        ttk.Label(root, textvariable=self.status_var, anchor="w").pack(fill="x", padx=10, pady=(2, 8))\n',
)
replace_once(
    "content_agent/ui/main_window.py",
    '            self.ui_font_size_var,\n        ]\n',
    '            self.ui_font_size_var,\n'
    '            self.ui_language_var,\n'
    '            self.learning_enabled_var,\n'
    '            self.learning_examples_limit_var,\n'
    '        ]\n',
)
replace_once(
    "content_agent/ui/main_window.py",
    '    # Sources\n    def _build_sources_tab(self) -> None:\n',
    '''    def t(self, text: str) -> str:\n        return tr(text, self.config.ui_language)\n\n    def _apply_language(self, *, refresh: bool = True) -> None:\n        language = normalize_language(\n            language_from_label(self.ui_language_var.get())\n            if hasattr(self, "ui_language_var")\n            else self.config.ui_language\n        )\n        self.config.ui_language = language\n        self.root.title("UA FREE Content Tool — v1.1.0")\n        localize_widget_tree(self.root, language)\n        if hasattr(self, "group_filter_box"):\n            current = original_text(self.group_filter.get())\n            values = tuple(tr(item, language) for item in GROUP_FILTERS)\n            self.group_filter_box.configure(values=values)\n            self.group_filter.set(tr(current if current in GROUP_FILTERS else "Активні", language))\n        if hasattr(self, "queue_filter_box"):\n            current = original_text(self.queue_filter.get())\n            values = tuple(tr(item, language) for item in QUEUE_FILTERS)\n            self.queue_filter_box.configure(values=values)\n            self.queue_filter.set(tr(current if current in QUEUE_FILTERS else "Активні", language))\n        if hasattr(self, "settings_language_status_var"):\n            self.settings_language_status_var.set(\n                "Interface and Ollama output: English"\n                if language == "en"\n                else "Інтерфейс і вихід Ollama: українська"\n            )\n        if refresh and hasattr(self, "groups_tree"):\n            self.refresh_groups()\n            self.refresh_queue()\n\n    def preview_language(self, *_args: object) -> None:\n        self._apply_language()\n        self._mark_settings_dirty()\n\n    # Sources\n    def _build_sources_tab(self) -> None:\n''',
)
replace_regex(
    "content_agent/ui/main_window.py",
    r'    def _build_inbox_tab\(self\) -> None:\n.*?\n    def refresh_groups\(self\) -> None:',
    '''    def _build_inbox_tab(self) -> None:\n        tab = ttk.Frame(self.notebook, padding=10)\n        self.notebook.add(tab, text="Вхідні")\n\n        actions = ttk.Frame(tab)\n        actions.pack(fill="x", pady=(0, 6))\n        self.group_filter = tk.StringVar(value="Активні")\n        ttk.Label(actions, text="Показати").grid(row=0, column=0, sticky="w", padx=(0, 4))\n        self.group_filter_box = ttk.Combobox(\n            actions, textvariable=self.group_filter, values=tuple(GROUP_FILTERS),\n            state="readonly", width=13,\n        )\n        self.group_filter_box.grid(row=0, column=1, sticky="w", padx=(0, 5))\n        self.group_filter_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh_groups())\n        ttk.Button(actions, text="Оновити", command=self.refresh_groups).grid(row=0, column=2, padx=3)\n        ttk.Button(actions, text="Відновити / прийняти", command=self.accept_selected_group).grid(row=0, column=3, padx=3)\n        ttk.Button(actions, text="Видалити", command=self.delete_selected_groups).grid(row=0, column=4, padx=3)\n        tk.Button(\n            actions, text="Запам’ятати й більше не пропонувати",\n            command=self.remember_and_exclude_selected_groups, bg="#b3261e", fg="white",\n            activebackground="#8f1f19", activeforeground="white", relief="flat", padx=9, pady=4,\n        ).grid(row=0, column=5, padx=3)\n        ttk.Button(\n            actions, text="Пошук схожих за темою матеріалів", command=self.find_all_by_topic\n        ).grid(row=0, column=6, padx=3)\n        tk.Button(\n            actions, text="Об’єднати в один блок", command=self.merge_selected_groups,\n            bg="#2e7d32", fg="white", activebackground="#256628", activeforeground="white",\n            relief="flat", padx=9, pady=4,\n        ).grid(row=0, column=7, padx=3)\n        actions.columnconfigure(8, weight=1)\n\n        self.topic_search_status_var = tk.StringVar(\n            value="Оберіть одну новину й натисніть «Пошук схожих за темою матеріалів»."\n        )\n        ttk.Label(tab, textvariable=self.topic_search_status_var, foreground="#555", wraplength=1350).pack(\n            fill="x", pady=(0, 4)\n        )\n        ttk.Label(\n            tab,\n            text="Вибір: Shift — діапазон, Ctrl — окремі блоки, Ctrl+A — усі видимі, Delete — просте видалення.",\n        ).pack(fill="x", pady=(0, 6))\n\n        tree_frame = ttk.Frame(tab)\n        tree_frame.pack(fill="both", expand=True)\n        columns = ("id", "status", "title", "sources", "published", "score")\n        self.groups_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="extended")\n        headings = {\n            "id": "Блок", "status": "Статус", "title": "Подія", "sources": "Джерел",\n            "published": "Остання згадка", "score": "Вибуховість",\n        }\n        widths = {"id": 70, "status": 100, "title": 650, "sources": 90, "published": 190, "score": 120}\n        for column in columns:\n            self.groups_tree.heading(column, text=headings[column])\n            self.groups_tree.column(column, width=widths[column], anchor="w")\n        self.groups_tree.tag_configure("approved", background="#e7f5e8")\n        self.groups_tree.tag_configure("topic_strong", background="#dff2df")\n        self.groups_tree.tag_configure("topic_possible", background="#fff4cc")\n        groups_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.groups_tree.yview)\n        self.groups_tree.configure(yscrollcommand=groups_scroll.set)\n        self.groups_tree.pack(side="left", fill="both", expand=True)\n        groups_scroll.pack(side="right", fill="y")\n        self.groups_tree.bind("<Button-1>", self._remember_group_selection_anchor, add="+")\n        self.groups_tree.bind("<Shift-Button-1>", self._select_group_range)\n        self.groups_tree.bind("<Double-1>", lambda _event: self.accept_selected_group())\n        self.groups_tree.bind("<Control-a>", self._select_all_group_rows)\n        self.groups_tree.bind("<Control-A>", self._select_all_group_rows)\n        self.groups_tree.bind("<Delete>", self._delete_selected_group_rows)\n        self.groups_tree.bind("<Prior>", self._page_group_tree)\n        self.groups_tree.bind("<Next>", self._page_group_tree)\n        self.groups_tree.bind("<Home>", self._page_group_tree)\n        self.groups_tree.bind("<End>", self._page_group_tree)\n\n    def _page_group_tree(self, event: tk.Event) -> str:\n        key = str(getattr(event, "keysym", ""))\n        if key == "Prior":\n            self.groups_tree.yview_scroll(-1, "pages")\n        elif key == "Next":\n            self.groups_tree.yview_scroll(1, "pages")\n        elif key == "Home":\n            self.groups_tree.yview_moveto(0.0)\n        elif key == "End":\n            self.groups_tree.yview_moveto(1.0)\n        return "break"\n\n    def refresh_groups(self) -> None:''',
)
replace_regex(
    "content_agent/ui/main_window.py",
    r'    def refresh_groups\(self\) -> None:\n.*?\n    def refresh_articles\(self\) -> None:',
    '''    def refresh_groups(self) -> None:\n        selected_before = tuple(self.groups_tree.selection())\n        focus_before = self.groups_tree.focus()\n        yview_before = self.groups_tree.yview()\n        self.groups_tree.delete(*self.groups_tree.get_children())\n        selected_filter = original_text(self.group_filter.get())\n        status = GROUP_FILTERS.get(selected_filter)\n        for group in self.db.list_groups(status=status):\n            score = f"{group.explosiveness_score}/100" if group.explosiveness_score else "—"\n            tags = ("approved",) if group.status == "approved" else ()\n            self.groups_tree.insert(\n                "", "end", iid=str(group.id),\n                values=(\n                    group.id,\n                    tr(GROUP_STATUS_LABELS.get(group.status, group.status), self.config.ui_language),\n                    group.canonical_title, group.source_count, group.last_published_at or "—", score,\n                ),\n                tags=tags,\n            )\n        existing = [iid for iid in selected_before if self.groups_tree.exists(iid)]\n        if existing:\n            self.groups_tree.selection_set(existing)\n        if focus_before and self.groups_tree.exists(focus_before):\n            self.groups_tree.focus(focus_before)\n        if yview_before:\n            self.groups_tree.yview_moveto(float(yview_before[0]))\n\n    def refresh_articles(self) -> None:''',
)
replace_once(
    "content_agent/ui/main_window.py",
    '        if group.status in {"new", "rejected"}:\n            self.db.set_group_status(group_id, "draft")\n',
    '        if group.status == "rejected":\n            self.db.set_group_status(group_id, "new")\n',
)
replace_regex(
    "content_agent/ui/main_window.py",
    r'    def find_all_by_topic\(self\) -> None:\n.*?\n    def merge_selected_groups\(self\) -> None:',
    '''    def find_all_by_topic(self) -> None:\n        anchor_id = self._require_single_group_id("Пошук схожих за темою матеріалів")\n        if anchor_id is None:\n            return\n        try:\n            anchor = self.db.get_group(anchor_id)\n        except Exception as exc:\n            self._show_error(exc)\n            return\n        candidate_rows = self.db.topic_candidate_rows(anchor_id)\n        topic_feedback = (\n            self.db.list_topic_feedback(language=self.config.ui_language)\n            if self.config.learning_enabled\n            else []\n        )\n        local_candidates = rank_topic_candidates(\n            anchor.combined_text or anchor.canonical_title,\n            candidate_rows,\n            feedback=topic_feedback,\n            limit=12,\n            language=self.config.ui_language,\n        )\n        if not local_candidates:\n            self.topic_search_status_var.set(self.t("Схожих матеріалів для об’єднання не знайдено."))\n            return\n        rows_by_id = {int(row["group_id"]): row for row in candidate_rows}\n        shortlisted = [rows_by_id[item.group_id] for item in local_candidates if item.group_id in rows_by_id]\n        self.topic_search_status_var.set(\n            (f"Ollama is checking {len(shortlisted)} candidates…" if self.config.ui_language == "en"\n             else f"Ollama перевіряє {len(shortlisted)} кандидатів…")\n        )\n\n        def action() -> object:\n            prompt = build_topic_prompt(\n                anchor.canonical_title, anchor.combined_text, shortlisted,\n                feedback=topic_feedback, language=self.config.ui_language,\n            )\n            try:\n                client = OllamaClient(self.config.ollama_base_url, timeout=180, load_timeout=120)\n                raw = client.generate_text(self.config.ollama_model, prompt, num_predict=700)\n                model_matches = parse_topic_matches(raw)\n                error = ""\n            except OllamaError as exc:\n                model_matches = {}\n                error = str(exc)\n            return merge_local_and_ollama(local_candidates, model_matches, minimum_score=45), error\n\n        def success(result: object) -> None:\n            matches, error = result  # type: ignore[misc]\n            candidate_data: list[dict[str, object]] = []\n            for match in matches:\n                row = rows_by_id.get(match.group_id)\n                if row is None:\n                    continue\n                candidate_data.append({**row, "score": match.score, "reason": match.reason})\n            if not candidate_data:\n                suffix = f" {error}" if error else ""\n                self.topic_search_status_var.set(self.t("Схожих матеріалів для об’єднання не знайдено.") + suffix)\n                return\n            self.topic_search_status_var.set(\n                (f"Merge candidates: {len(candidate_data)}" if self.config.ui_language == "en"\n                 else f"Кандидатів на об’єднання: {len(candidate_data)}")\n            )\n            TopicCandidatesDialog(\n                self.root, anchor_id=anchor_id, anchor_title=anchor.canonical_title,\n                candidates=candidate_data, language=self.config.ui_language,\n                on_merge=lambda selected, all_ids: self._merge_topic_candidates(\n                    anchor_id, selected, all_ids\n                ),\n            )\n\n        self.run_async(\n            action, success,\n            label=(f"Topic search for block #{anchor_id}" if self.config.ui_language == "en"\n                   else f"Пошук матеріалів по темі блоку #{anchor_id}"),\n            done_label=("Topic search completed" if self.config.ui_language == "en"\n                        else "Тематичний пошук завершено"),\n        )\n\n    def _merge_topic_candidates(\n        self, anchor_id: int, selected_ids: list[int], all_candidate_ids: list[int]\n    ) -> None:\n        if not selected_ids:\n            return\n        group_ids = [anchor_id, *selected_ids]\n        try:\n            anchor = self.db.get_group(anchor_id)\n            candidate_groups = {group_id: self.db.get_group(group_id) for group_id in all_candidate_ids}\n            moved = self.db.merge_groups(anchor_id, group_ids)\n            if self.config.learning_enabled:\n                for group_id, candidate in candidate_groups.items():\n                    decision = "merged" if group_id in selected_ids else "not_related"\n                    self.db.record_topic_feedback(\n                        anchor.combined_text or anchor.canonical_title,\n                        candidate.combined_text or candidate.canonical_title,\n                        decision=decision, language=self.config.ui_language,\n                    )\n                self.db.record_learning_event(\n                    "topic_candidate_selection", language=self.config.ui_language,\n                    group_id=anchor_id, anchor_group_id=anchor_id,\n                    payload={"selected": selected_ids, "rejected": [i for i in all_candidate_ids if i not in selected_ids]},\n                )\n        except Exception as exc:\n            self._show_error(exc)\n            return\n        self.refresh_groups()\n        if self.groups_tree.exists(str(anchor_id)):\n            self.groups_tree.selection_set(str(anchor_id))\n            self.groups_tree.focus(str(anchor_id))\n            self.groups_tree.see(str(anchor_id))\n        self.set_status(\n            (f"Merged {len(selected_ids)} candidates; moved sources: {moved}."\n             if self.config.ui_language == "en"\n             else f"Об’єднано кандидатів: {len(selected_ids)}; перенесено джерел: {moved}.")\n        )\n\n    def merge_selected_groups(self) -> None:''',
)
replace_once(
    "content_agent/ui/main_window.py",
    '                    decision="merged",\n                )\n',
    '                    decision="merged",\n'
    '                    language=self.config.ui_language,\n'
    '                )\n',
)
replace_once(
    "content_agent/ui/main_window.py",
    '                self.db.list_editorial_examples(),\n                limit=3,\n',
    '                self.db.list_editorial_examples(language=config.ui_language),\n'
    '                limit=config.learning_examples_limit if config.learning_enabled else 0,\n',
)
replace_once(
    "content_agent/ui/main_window.py",
    '                editorial_examples=examples,\n            )\n',
    '                editorial_examples=examples,\n'
    '                language=config.ui_language,\n'
    '            )\n',
)
replace_once(
    "content_agent/ui/main_window.py",
    '            self.db.save_group_rewrite(\n                group.id,\n                headline=rewrite_result.headline,\n                fact_card=rewrite_result.fact_card,\n                rewrite_text=rewrite_result.rewrite,\n                platform_texts=rewrite_result.platform_texts,\n            )\n',
    '            self.db.save_group_rewrite(\n'
    '                group.id,\n'
    '                headline=rewrite_result.headline,\n'
    '                fact_card=rewrite_result.fact_card,\n'
    '                rewrite_text=rewrite_result.rewrite,\n'
    '                platform_texts=rewrite_result.platform_texts,\n'
    '            )\n'
    '            if config.learning_enabled:\n'
    '                self.db.record_learning_event(\n'
    '                    "rewrite_generated", language=config.ui_language, group_id=group.id,\n'
    '                    payload={"model": model_used, "fallback": bool(used_fallback), "examples": example_count},\n'
    '                )\n',
)
replace_once(
    "content_agent/ui/main_window.py",
    '            headline=headline,\n        )\n',
    '            headline=headline,\n'
    '            language=self.config.ui_language,\n'
    '        )\n',
)
replace_once(
    "content_agent/ui/main_window.py",
    '                f"Редакційна пам’ять: {self.db.editorial_example_count()} схвалених прикладів"\n',
    '                (f"Editorial memory: {self.db.editorial_example_count(language=self.config.ui_language)} approved examples"\n'
    '                 if self.config.ui_language == "en"\n'
    '                 else f"Редакційна пам’ять: {self.db.editorial_example_count(language=self.config.ui_language)} схвалених прикладів")\n',
)
replace_once(
    "content_agent/ui/main_window.py",
    '        self.ui_font_size_var = tk.StringVar(value=str(self.config.ui_font_size))\n\n        font_controls = ttk.Frame(sticky)\n',
    '        self.ui_font_size_var = tk.StringVar(value=str(self.config.ui_font_size))\n'
    '        self.ui_language_var = tk.StringVar(value=language_label(self.config.ui_language))\n'
    '        self.settings_language_status_var = tk.StringVar()\n\n'
    '        font_controls = ttk.Frame(sticky)\n',
)
replace_once(
    "content_agent/ui/main_window.py",
    '        ttk.Button(font_controls, text="A+", width=4, command=lambda: self.change_font_size(1)).pack(side="left", padx=(2, 10))\n\n        ttk.Label(sticky, textvariable=self.settings_dirty_var, foreground="#555").grid(\n',
    '        ttk.Button(font_controls, text="A+", width=4, command=lambda: self.change_font_size(1)).pack(side="left", padx=(2, 10))\n'
    '        ttk.Label(font_controls, text="Мова програми").pack(side="left", padx=(12, 4))\n'
    '        self.ui_language_combo = ttk.Combobox(\n'
    '            font_controls, textvariable=self.ui_language_var,\n'
    '            values=tuple(LANGUAGE_LABELS.values()), state="readonly", width=12,\n'
    '        )\n'
    '        self.ui_language_combo.pack(side="left", padx=(0, 6))\n'
    '        self.ui_language_combo.bind("<<ComboboxSelected>>", self.preview_language)\n'
    '        ttk.Label(font_controls, textvariable=self.settings_language_status_var, foreground="#555").pack(side="left")\n\n'
    '        ttk.Label(sticky, textvariable=self.settings_dirty_var, foreground="#555").grid(\n',
)
# Replace shared Meta app frame with independent Facebook and Threads credentials.
replace_regex(
    "content_agent/ui/main_window.py",
    r'        meta_app = ttk\.LabelFrame\(platforms, text="Meta застосунок — спільний для Facebook і Threads".*?        meta_app\.columnconfigure\(1, weight=1\)\n',
    '''        facebook_app = ttk.LabelFrame(platforms, text="Facebook застосунок", padding=8)\n        facebook_app.pack(fill="x", pady=4)\n        self.settings_vars["facebook_app_id"] = tk.StringVar(value=self.config.facebook_app_id)\n        self.settings_vars["facebook_app_secret"] = tk.StringVar(value=self.config.facebook_app_secret)\n        ttk.Label(facebook_app, text="Facebook App ID").grid(row=0, column=0, sticky="w")\n        ttk.Entry(facebook_app, textvariable=self.settings_vars["facebook_app_id"], width=32).grid(\n            row=1, column=0, sticky="ew", padx=(0, 8)\n        )\n        ttk.Label(facebook_app, text="Facebook App Secret").grid(row=0, column=1, sticky="w")\n        ttk.Entry(\n            facebook_app, textvariable=self.settings_vars["facebook_app_secret"], show="•", width=48\n        ).grid(row=1, column=1, sticky="ew")\n        ttk.Button(\n            facebook_app, text="Відкрити налаштування застосунку",\n            command=lambda: webbrowser.open("https://developers.facebook.com/apps/", new=2),\n        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))\n        facebook_app.columnconfigure(0, weight=1)\n        facebook_app.columnconfigure(1, weight=1)\n\n        threads_app = ttk.LabelFrame(platforms, text="Threads застосунок", padding=8)\n        threads_app.pack(fill="x", pady=4)\n        self.settings_vars["threads_app_id"] = tk.StringVar(value=self.config.threads_app_id)\n        self.settings_vars["threads_app_secret"] = tk.StringVar(value=self.config.threads_app_secret)\n        ttk.Label(threads_app, text="Threads App ID").grid(row=0, column=0, sticky="w")\n        ttk.Entry(threads_app, textvariable=self.settings_vars["threads_app_id"], width=32).grid(\n            row=1, column=0, sticky="ew", padx=(0, 8)\n        )\n        ttk.Label(threads_app, text="Threads App Secret").grid(row=0, column=1, sticky="w")\n        ttk.Entry(\n            threads_app, textvariable=self.settings_vars["threads_app_secret"], show="•", width=48\n        ).grid(row=1, column=1, sticky="ew")\n        ttk.Button(\n            threads_app, text="Відкрити налаштування застосунку",\n            command=lambda: webbrowser.open("https://developers.facebook.com/apps/", new=2),\n        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))\n        threads_app.columnconfigure(0, weight=1)\n        threads_app.columnconfigure(1, weight=1)\n''',
)
# Add learning controls before schedule/backup section.
replace_once(
    "content_agent/ui/main_window.py",
    '        schedule = ttk.LabelFrame(form, text="3. Розклад і резервні копії", padding=8)\n',
    '''        learning = ttk.LabelFrame(form, text="Локальне навчання", padding=8)\n        learning.pack(fill="x", pady=(0, 8))\n        self.learning_enabled_var = tk.BooleanVar(value=self.config.learning_enabled)\n        self.learning_examples_limit_var = tk.StringVar(value=str(self.config.learning_examples_limit))\n        self.learning_stats_var = tk.StringVar(value="")\n        ttk.Checkbutton(\n            learning, text="Використовувати навчальні приклади в промптах Ollama",\n            variable=self.learning_enabled_var,\n        ).grid(row=0, column=0, columnspan=3, sticky="w")\n        ttk.Label(learning, text="Кількість прикладів у промпті").grid(row=1, column=0, sticky="w", pady=(7, 0))\n        ttk.Combobox(\n            learning, textvariable=self.learning_examples_limit_var,\n            values=tuple(str(value) for value in range(1, 13)), state="readonly", width=6,\n        ).grid(row=1, column=1, sticky="w", padx=6, pady=(7, 0))\n        ttk.Button(learning, text="Оновити статистику", command=self.refresh_learning_stats).grid(\n            row=1, column=2, sticky="w", pady=(7, 0)\n        )\n        ttk.Label(learning, textvariable=self.learning_stats_var, foreground="#555").grid(\n            row=2, column=0, columnspan=3, sticky="w", pady=(6, 3)\n        )\n        learning_actions = ttk.Frame(learning)\n        learning_actions.grid(row=3, column=0, columnspan=3, sticky="w", pady=(5, 0))\n        ttk.Button(learning_actions, text="Експортувати навчальні дані", command=self.export_learning_data_ui).pack(side="left")\n        ttk.Button(learning_actions, text="Імпортувати навчальні дані", command=self.import_learning_data_ui).pack(side="left", padx=6)\n        ttk.Button(learning_actions, text="Очистити навчальну історію", command=self.clear_learning_history_ui).pack(side="left")\n        self.refresh_learning_stats()\n\n        schedule = ttk.LabelFrame(form, text="3. Розклад і резервні копії", padding=8)\n''',
)
replace_once(
    "content_agent/ui/main_window.py",
    '        app_id_var = self.settings_vars.get("meta_app_id")\n        app_secret_var = self.settings_vars.get("meta_app_secret")\n        app_id = app_id_var.get().strip() if app_id_var is not None else self.config.meta_app_id\n        app_secret = app_secret_var.get().strip() if app_secret_var is not None else self.config.meta_app_secret\n        graph_version = self.config.meta_graph_version or "v24.0"\n',
    '        app_id_var = self.settings_vars.get("facebook_app_id")\n'
    '        app_secret_var = self.settings_vars.get("facebook_app_secret")\n'
    '        app_id = app_id_var.get().strip() if app_id_var is not None else self.config.facebook_app_id\n'
    '        app_secret = app_secret_var.get().strip() if app_secret_var is not None else self.config.facebook_app_secret\n'
    '        graph_version = self.config.meta_graph_version or "v26.0"\n',
)
replace_once(
    "content_agent/ui/main_window.py",
    '        app_id_var = self.settings_vars.get("meta_app_id")\n        app_secret_var = self.settings_vars.get("meta_app_secret")\n        self.config.meta_app_id = app_id_var.get().strip() if app_id_var is not None else self.config.meta_app_id\n        self.config.meta_app_secret = app_secret_var.get().strip() if app_secret_var is not None else self.config.meta_app_secret\n',
    '        app_id_var = self.settings_vars.get("facebook_app_id")\n'
    '        app_secret_var = self.settings_vars.get("facebook_app_secret")\n'
    '        self.config.facebook_app_id = app_id_var.get().strip() if app_id_var is not None else self.config.facebook_app_id\n'
    '        self.config.facebook_app_secret = app_secret_var.get().strip() if app_secret_var is not None else self.config.facebook_app_secret\n'
    '        self.config.meta_app_id = self.config.facebook_app_id\n'
    '        self.config.meta_app_secret = self.config.facebook_app_secret\n',
)
replace_once(
    "content_agent/ui/main_window.py",
    '        app_secret_var = self.settings_vars.get("meta_app_secret")\n        app_secret = app_secret_var.get().strip() if app_secret_var is not None else self.config.meta_app_secret\n',
    '        app_secret_var = self.settings_vars.get("threads_app_secret")\n'
    '        app_secret = app_secret_var.get().strip() if app_secret_var is not None else self.config.threads_app_secret\n',
)
replace_once(
    "content_agent/ui/main_window.py",
    '            app_id_var = self.settings_vars.get("meta_app_id")\n            self.config.meta_app_id = app_id_var.get().strip() if app_id_var is not None else self.config.meta_app_id\n            self.config.meta_app_secret = app_secret\n',
    '            app_id_var = self.settings_vars.get("threads_app_id")\n'
    '            self.config.threads_app_id = app_id_var.get().strip() if app_id_var is not None else self.config.threads_app_id\n'
    '            self.config.threads_app_secret = app_secret\n'
    '            self.config.meta_app_id = self.config.facebook_app_id or self.config.threads_app_id\n'
    '            self.config.meta_app_secret = self.config.facebook_app_secret or self.config.threads_app_secret\n',
)
replace_once(
    "content_agent/ui/main_window.py",
    '            new_meta_app_id = self.settings_vars["meta_app_id"].get().strip()\n            new_meta_app_secret = self.settings_vars["meta_app_secret"].get().strip()\n',
    '            new_facebook_app_id = self.settings_vars["facebook_app_id"].get().strip()\n'
    '            new_facebook_app_secret = self.settings_vars["facebook_app_secret"].get().strip()\n'
    '            new_threads_app_id = self.settings_vars["threads_app_id"].get().strip()\n'
    '            new_threads_app_secret = self.settings_vars["threads_app_secret"].get().strip()\n',
)
replace_once(
    "content_agent/ui/main_window.py",
    '                    "meta_app_id": new_meta_app_id,\n                    "meta_app_secret": new_meta_app_secret,\n',
    '                    "facebook_app_id": new_facebook_app_id,\n'
    '                    "facebook_app_secret": new_facebook_app_secret,\n'
    '                    "threads_app_id": new_threads_app_id,\n'
    '                    "threads_app_secret": new_threads_app_secret,\n'
    '                    "meta_app_id": new_facebook_app_id or new_threads_app_id,\n'
    '                    "meta_app_secret": new_facebook_app_secret or new_threads_app_secret,\n'
    '                    "ui_language": language_from_label(self.ui_language_var.get()),\n'
    '                    "learning_enabled": self.learning_enabled_var.get(),\n'
    '                    "learning_examples_limit": int(self.learning_examples_limit_var.get()),\n',
)
replace_once(
    "content_agent/ui/main_window.py",
    '                    "meta_graph_version": self.config.meta_graph_version or "v24.0",\n',
    '                    "meta_graph_version": self.config.meta_graph_version or "v26.0",\n',
)
replace_once(
    "content_agent/ui/main_window.py",
    '        self._apply_ui_font_size(config.ui_font_size)\n        self._refresh_meta_pages_view()\n',
    '        self._apply_ui_font_size(config.ui_font_size)\n'
    '        self.ui_language_var.set(language_label(config.ui_language))\n'
    '        self._apply_language(refresh=False)\n'
    '        self._refresh_meta_pages_view()\n',
)
replace_once(
    "content_agent/ui/main_window.py",
    '    def create_backup_ui(self) -> None:\n',
    '''    def refresh_learning_stats(self) -> None:\n        if not hasattr(self, "learning_stats_var"):\n            return\n        stats = self.db.learning_stats()\n        examples = stats.get("editorial_examples", {})\n        if self.config.ui_language == "en":\n            self.learning_stats_var.set(\n                f"Examples: UK {examples.get('uk', 0)} · EN {examples.get('en', 0)} · "\n                f"merge feedback: {stats.get('topic_feedback', 0)} · events: {stats.get('events', 0)} · "\n                f"active exclusions: {stats.get('active_exclusions', 0)}"\n            )\n        else:\n            self.learning_stats_var.set(\n                f"Приклади: UK {examples.get('uk', 0)} · EN {examples.get('en', 0)} · "\n                f"рішень про об’єднання: {stats.get('topic_feedback', 0)} · подій: {stats.get('events', 0)} · "\n                f"активних виключень: {stats.get('active_exclusions', 0)}"\n            )\n\n    def export_learning_data_ui(self) -> None:\n        selected = filedialog.asksaveasfilename(\n            parent=self.root, title=self.t("Експортувати навчальні дані"),\n            defaultextension=".json", filetypes=[("JSON", "*.json")],\n            initialfile="UA_FREE_learning_data.json",\n        )\n        if not selected:\n            return\n        try:\n            path = self.db.export_learning_data(Path(selected))\n        except Exception as exc:\n            self._show_error(exc)\n            return\n        messagebox.showinfo(self.t("Локальне навчання"), str(path), parent=self.root)\n\n    def import_learning_data_ui(self) -> None:\n        selected = filedialog.askopenfilename(\n            parent=self.root, title=self.t("Імпортувати навчальні дані"),\n            filetypes=[("JSON", "*.json")],\n        )\n        if not selected:\n            return\n        try:\n            counts = self.db.import_learning_data(Path(selected))\n        except Exception as exc:\n            self._show_error(exc)\n            return\n        self.refresh_learning_stats()\n        messagebox.showinfo(self.t("Локальне навчання"), str(counts), parent=self.root)\n\n    def clear_learning_history_ui(self) -> None:\n        question = (\n            "Delete editorial examples, merge feedback, and learning events? Permanent inbox exclusions will remain."\n            if self.config.ui_language == "en"\n            else "Видалити редакційні приклади, рішення про об’єднання та навчальні події? Постійні виключення новин залишаться."\n        )\n        if not messagebox.askyesno(self.t("Очистити навчальну історію"), question, parent=self.root):\n            return\n        self.db.clear_learning_history()\n        self.refresh_learning_stats()\n\n    def create_backup_ui(self) -> None:\n''',
)
replace_once(
    "content_agent/ui/main_window.py",
    '            self._update_target_availability()\n            messagebox.showinfo(\n',
    '            self._update_target_availability()\n'
    '            self.ui_language_var.set(language_label(self.config.ui_language))\n'
    '            self._apply_language()\n'
    '            self.refresh_learning_stats()\n'
    '            messagebox.showinfo(\n',
)

# Extend a few localization strings introduced by the new dialog.
i18n = read("content_agent/i18n.py")
i18n = i18n.replace(
    '    "Схожих матеріалів для об’єднання не знайдено.":',
    '    "Кандидати на об’єднання": "Merge candidates",\n'
    '    "Попередній перегляд": "Preview",\n'
    '    "Вибір": "Selected",\n'
    '    "Схожість": "Similarity",\n'
    '    "Причина": "Reason",\n'
    '    "Для цього матеріалу немає доступного URL.": "No URL is available for this item.",\n'
    '    "Схожих матеріалів для об’єднання не знайдено.":',
)
write("content_agent/i18n.py", i18n)

# ---------------------------------------------------------------------------
# Version, changelog, docs and focused regression tests.
# ---------------------------------------------------------------------------
write("VERSION.txt", "1.1.0\n")
write("PUBLIC_VERSION.txt", "1.1.0\n")
changelog = read("CHANGELOG.md")
if "## 1.1.0" not in changelog:
    changelog = changelog.replace(
        "# Changelog\n",
        "# Changelog\n\n## 1.1.0\n\n"
        "- Added Ukrainian and English application modes; the selected language now controls Ollama prompts and rewrite output.\n"
        "- Added a focused merge-candidate dialog instead of selecting matches across the full inbox.\n"
        "- Added a visible inbox scrollbar, keyboard paging, one-row actions, approved-row highlighting, and removed the confusing visible in-work status.\n"
        "- Added local learning connectors, language-separated editorial examples, import/export, statistics, and history controls.\n"
        "- Split Facebook and Threads application credentials so different Meta accounts and apps can be used safely.\n\n",
    )
write("CHANGELOG.md", changelog)

readme = read("README.md")
if "Bilingual interface" not in readme:
    readme += """

## v1.1.0 development highlights

- **Bilingual interface:** Ukrainian and English modes are selected in Settings. The same setting controls Ollama prompts and final rewrite language.
- **Focused topic merging:** topic search opens a dedicated candidate window, so editors never have to hunt through the full inbox.
- **Local learning connectors:** approved edits, manual merges, rejected candidates, exclusions, and generated rewrites feed a local, exportable learning store. No training data is uploaded to a cloud service.
- **Independent Meta applications:** Facebook and Threads App IDs and secrets are configured separately.
"""
write("README.md", readme)

write(
    "tests/test_v1_1_i18n_learning.py",
    '''from __future__ import annotations\n\nfrom pathlib import Path\n\nfrom content_agent.config import AppConfig\nfrom content_agent.database import DATABASE_SCHEMA_VERSION, Database\nfrom content_agent.editorial_memory import EditorialExample, format_examples_for_prompt\nfrom content_agent.i18n import language_from_label, tr\nfrom content_agent.topic_search import build_topic_prompt\n\n\ndef test_config_supports_language_learning_and_independent_meta_apps() -> None:\n    config = AppConfig(\n        ui_language="en",\n        learning_enabled=True,\n        learning_examples_limit=5,\n        facebook_app_id="fb",\n        facebook_app_secret="fb-secret",\n        threads_app_id="threads",\n        threads_app_secret="threads-secret",\n    )\n    config.validate()\n    restored = AppConfig.from_json_bytes(config.to_json_bytes())\n    assert restored.ui_language == "en"\n    assert restored.facebook_app_id == "fb"\n    assert restored.threads_app_id == "threads"\n\n\ndef test_legacy_shared_meta_fields_migrate_to_both_apps() -> None:\n    raw = AppConfig(meta_app_id="legacy", meta_app_secret="secret").to_json_bytes()\n    restored = AppConfig.from_json_bytes(raw)\n    assert restored.facebook_app_id == "legacy"\n    assert restored.threads_app_id == "legacy"\n\n\ndef test_static_translation_and_language_label() -> None:\n    assert tr("Вхідні", "en") == "Inbox"\n    assert tr("Вхідні", "uk") == "Вхідні"\n    assert language_from_label("English") == "en"\n\n\ndef test_editorial_prompt_examples_are_language_specific() -> None:\n    example = EditorialExample(1, "source", "draft", "final", language="en", similarity=0.7)\n    assert "EDITOR'S FINAL TEXT" in format_examples_for_prompt([example], language="en")\n    assert "ФІНАЛЬНИЙ ТЕКСТ" in format_examples_for_prompt([example], language="uk")\n\n\ndef test_topic_prompt_uses_selected_language() -> None:\n    prompt = build_topic_prompt(\n        "Title", "Body", [{"group_id": 2, "title": "Candidate", "text": "Candidate body"}],\n        language="en",\n    )\n    assert "ANCHOR STORY" in prompt\n    assert "Return ONLY" in prompt\n\n\ndef test_schema_v8_and_learning_roundtrip(tmp_path: Path) -> None:\n    assert DATABASE_SCHEMA_VERSION >= 8\n    db = Database(tmp_path / "data.sqlite3")\n    event_id = db.record_learning_event(\n        "rewrite_generated", language="en", group_id=7, payload={"model": "test"}\n    )\n    rows = db.list_learning_events(language="en")\n    assert rows[0]["id"] == event_id\n    assert rows[0]["payload"] == {"model": "test"}\n    exported = db.export_learning_data(tmp_path / "learning.json")\n    assert exported.exists()\n''',
)

write(
    "tests/test_v1_1_rewriter_language.py",
    '''from __future__ import annotations\n\nfrom content_agent.models import Article\nfrom content_agent.rewriter import rewrite_article\n\n\nclass FakeClient:\n    def __init__(self, payload: dict[str, str]):\n        self.payload = payload\n        self.prompts: list[str] = []\n\n    def generate_json(self, model, prompt, schema, **kwargs):  # type: ignore[no-untyped-def]\n        self.prompts.append(prompt)\n        return dict(self.payload)\n\n\ndef article() -> Article:\n    return Article(\n        id=1, source_id=1, title="Заголовок", url="https://example.com",\n        raw_text="Українське джерело повідомляє про подію у Києві 4 серпня.", status="new",\n    )\n\n\ndef test_english_mode_changes_prompt_and_accepts_english_output() -> None:\n    client = FakeClient({\n        "headline": "Kyiv event",\n        "fact_card": "One source used.",\n        "rewrite": "Officials reported the event in Kyiv on 4 August.",\n    })\n    result = rewrite_article(client, "model", article(), language="en")\n    assert result.rewrite.startswith("Officials")\n    assert "ENGLISH ONLY" in client.prompts[0]\n\n\ndef test_ukrainian_mode_keeps_ukrainian_instruction() -> None:\n    client = FakeClient({\n        "headline": "Подія у Києві",\n        "fact_card": "Використано одне джерело.",\n        "rewrite": "Посадовці повідомили про подію у Києві 4 серпня.",\n    })\n    result = rewrite_article(client, "model", article(), language="uk")\n    assert result.rewrite.startswith("Посадовці")\n    assert "ВИКЛЮЧНО УКРАЇНСЬКА" in client.prompts[0]\n''',
)

# The migration helper and its temporary workflow remove themselves after a clean
# application, so the feature branch contains only product code and tests.
for temporary in (
    ROOT / "tools" / "apply_v1_1_0.py",
    ROOT / ".github" / "workflows" / "apply-v1-1-0.yml",
):
    if temporary.exists():
        temporary.unlink()

print("v1.1.0 source migration applied")
