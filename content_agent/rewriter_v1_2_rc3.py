from __future__ import annotations

import re

from .editorial_memory import EditorialExample
from .i18n import normalize_language, output_language_instruction
from .models import Article, NewsGroup, RewriteResult
from .ollama_client import OllamaClient, OllamaError
from .rewriter import (
    EDITORIAL_TEXT_LIMIT,
    _rewrite_quality_issue_v11,
    fit_factual_text_to_limit,
    platform_texts_from_base,
    rewrite_article_with_fallback as _legacy_rewrite_with_fallback,
)
from .strict_ollama_decode_v1_2_rc3 import sanitize_publication_rewrite

_SENTENCES = re.compile(r"(?<=[.!?…])\s+")
_META_LINE = re.compile(
    r"(?im)^\s*(?:ЗАГОЛОВОК|HEADLINE|ФАКТИ|FACTS|FACT\s+CARD|"
    r"ПОЯСНЕННЯ|EXPLANATION|АНАЛІЗ|ANALYSIS|ПРИМІТКА|NOTE)\s*:.*$"
)
_TEXT_MARKER = re.compile(r"(?is)^.*?^\s*(?:ТЕКСТ|РЕРАЙТ|TEXT|ARTICLE)\s*:\s*", re.MULTILINE)


def _source_values(article: Article | NewsGroup) -> tuple[str, str, str, bool, int]:
    title = str(getattr(article, "canonical_title", "") or getattr(article, "title", "") or "Новина").strip()
    source_url = str(getattr(article, "primary_url", "") or getattr(article, "url", "") or "").strip()
    source_text = str(getattr(article, "combined_text", "") or getattr(article, "raw_text", "") or "").strip()
    include_source = bool(getattr(article, "include_source_link", False))
    total_sources = int(getattr(article, "source_count", 1) or 1)
    return title, source_url, source_text, include_source, total_sources


def is_short_news(article: Article | NewsGroup) -> bool:
    _title, _url, text, _include_source, total_sources = _source_values(article)
    compact = " ".join(text.split())
    if not compact:
        return False
    sentence_count = len([item for item in _SENTENCES.split(compact) if item.strip()])
    if total_sources <= 1:
        return len(compact) <= 380 and sentence_count <= 2
    return len(compact) <= 260 and sentence_count <= 2


def _short_prompt(title: str, source_text: str, language: str) -> str:
    if normalize_language(language) == "en":
        return f"""
{output_language_instruction('en')}
Rewrite this very short news item as one concise factual news sentence, or two
sentences only if needed to preserve all facts. Do not expand it. Do not add a
headline, fact card, explanation, analysis, URL, hashtag, fundraising call, or
anything not present in the source. Preserve names, numbers, places and actions.

Return ONLY:
TEXT: <finished publication text>

SOURCE TITLE: {title}
SOURCE:
{source_text}
""".strip()
    return f"""
{output_language_instruction('uk')} Не залишай російських слів або літер.
Перепиши це дуже коротке повідомлення як ОДНЕ лаконічне новинне речення.
Друге речення дозволене лише якщо без нього губиться важливий факт. Не роздувай
текст. Не додавай заголовок, факт-картку, пояснення, аналіз, посилання, хештеги,
донатний заклик або будь-які факти від себе. Збережи імена, числа, місця та дію.

Поверни ВИКЛЮЧНО:
ТЕКСТ: <готовий текст публікації>

ПОЧАТКОВИЙ ЗАГОЛОВОК: {title}
ДЖЕРЕЛО:
{source_text}
""".strip()


def _parse_short_response(raw: str) -> str:
    value = str(raw or "").strip()
    if not value:
        raise OllamaError("Ollama повернула порожній короткий рерайт.")
    marker = re.search(r"(?im)^\s*(?:ТЕКСТ|РЕРАЙТ|TEXT|ARTICLE)\s*:", value)
    if marker:
        value = value[marker.end():].strip()
    elif _META_LINE.search(value):
        raise OllamaError("Ollama змішала службові секції з коротким рерайтом.")
    value = _META_LINE.sub("", value).strip()
    return sanitize_publication_rewrite(value)


def _short_rewrite(client: OllamaClient, model: str, article: Article | NewsGroup, language: str) -> RewriteResult:
    title, source_url, source_text, include_source, total_sources = _source_values(article)
    if not source_text:
        raise OllamaError("Немає тексту для рерайту.")
    raw = client.generate_text(
        model,
        _short_prompt(title, source_text, language),
        num_predict=180,
        temperature=0.03,
    )
    rewrite = _parse_short_response(raw)
    if len(rewrite) > EDITORIAL_TEXT_LIMIT:
        rewrite = fit_factual_text_to_limit(rewrite, EDITORIAL_TEXT_LIMIT)
    issue = _rewrite_quality_issue_v11(title, rewrite, source_text, language)
    if issue:
        raise OllamaError(
            f"Короткий рерайт не пройшов перевірку: {issue}."
            if normalize_language(language) == "uk"
            else f"Short rewrite failed validation: {issue}."
        )
    fact_card = (
        f"Передано моделі джерел: {total_sources} із {total_sources}.\nКороткий режим: без розширення вихідного повідомлення."
        if normalize_language(language) == "uk"
        else f"Sources provided to the model: {total_sources} of {total_sources}.\nShort mode: source was not expanded."
    )
    return RewriteResult(
        headline=title,
        fact_card=fact_card,
        rewrite=rewrite,
        platform_texts=platform_texts_from_base(
            rewrite,
            include_source_link=include_source,
            source_url=source_url,
        ),
        source_count_used=total_sources,
        source_count_total=total_sources,
        auto_compacted=False,
    )


def rewrite_article_with_fallback_rc3(
    client: OllamaClient,
    primary_model: str,
    fallback_model: str,
    article: Article | NewsGroup,
    *,
    fallback_client: OllamaClient | None = None,
    editorial_examples: list[EditorialExample] | None = None,
    language: str = "uk",
) -> tuple[RewriteResult, str, bool]:
    language = normalize_language(language)
    if not is_short_news(article):
        return _legacy_rewrite_with_fallback(
            client,
            primary_model,
            fallback_model,
            article,
            fallback_client=fallback_client,
            editorial_examples=editorial_examples,
            language=language,
        )

    primary = str(primary_model or "").strip()
    fallback = str(fallback_model or "").strip()
    if not primary:
        raise OllamaError("Спочатку оберіть установлену модель Ollama.")
    try:
        return _short_rewrite(client, primary, article, language), primary, False
    except OllamaError as primary_error:
        if not fallback or fallback == primary:
            raise
        try:
            return _short_rewrite(fallback_client or client, fallback, article, language), fallback, True
        except OllamaError as fallback_error:
            raise OllamaError(
                f"Основна модель «{primary}» не впоралася з короткою новиною: {primary_error}\n"
                f"Запасна модель «{fallback}» також не впоралася: {fallback_error}"
            ) from fallback_error
