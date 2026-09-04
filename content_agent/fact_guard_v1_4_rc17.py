from __future__ import annotations

import re

from .fact_guard import FactGuardResult, _factual_evidence, _quality_score, guard_rewrite

# Curated aliases only. These are well-known brand/platform spellings that are
# routinely transliterated in RU/UA source feeds while the public rewrite keeps
# the canonical Latin brand. We deliberately do NOT attempt generic Cyrillic ↔
# Latin transliteration for arbitrary model/person names because that would turn
# Fact Guard into a hallucination permit.
_ENTITY_ALIAS_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "youtube": (
        re.compile(r"(?iu)\byou\s*tube\b"),
        re.compile(r"(?iu)\bютуб(?:а|і|и|у|ом|і|е)?\b"),
    ),
    "telegram": (
        re.compile(r"(?iu)\btelegram\b"),
        re.compile(r"(?iu)\bтелеграм(?:а|і|и|у|ом|і|е)?\b"),
    ),
    "facebook": (
        re.compile(r"(?iu)\bfacebook\b"),
        re.compile(r"(?iu)\bфейсбук(?:а|і|и|у|ом|і|е)?\b"),
    ),
    "instagram": (
        re.compile(r"(?iu)\binstagram\b"),
        re.compile(r"(?iu)\bінстаграм(?:а|і|у|ом|і)?\b"),
        re.compile(r"(?iu)\bинстаграм(?:а|е|у|ом)?\b"),
    ),
    "tiktok": (
        re.compile(r"(?iu)\btik\s*tok\b"),
        re.compile(r"(?iu)\bтік\s*ток(?:а|у|ом|і)?\b"),
        re.compile(r"(?iu)\bтик\s*ток(?:а|е|у|ом)?\b"),
    ),
    "twitter": (
        re.compile(r"(?iu)\btwitter\b"),
        re.compile(r"(?iu)\bтвіттер(?:а|і|у|ом)?\b"),
        re.compile(r"(?iu)\bтвиттер(?:а|е|у|ом)?\b"),
    ),
    "linkedin": (
        re.compile(r"(?iu)\blinked\s*in\b"),
        re.compile(r"(?iu)\bлінкедін(?:а|і|у|ом)?\b"),
        re.compile(r"(?iu)\bлинкедин(?:а|е|у|ом)?\b"),
    ),
    "whatsapp": (
        re.compile(r"(?iu)\bwhats\s*app\b"),
        re.compile(r"(?iu)\bватсап(?:а|і|у|ом|е)?\b"),
        re.compile(r"(?iu)\bвотсап(?:а|е|у|ом)?\b"),
    ),
    "reddit": (
        re.compile(r"(?iu)\breddit\b"),
        re.compile(r"(?iu)\bреддіт(?:а|і|у|ом)?\b"),
        re.compile(r"(?iu)\bреддит(?:а|е|у|ом)?\b"),
    ),
    "google": (
        re.compile(r"(?iu)\bgoogle\b"),
        re.compile(r"(?iu)\bгугл(?:а|і|и|у|ом|і|е)?\b"),
    ),
    "microsoft": (
        re.compile(r"(?iu)\bmicrosoft\b"),
        re.compile(r"(?iu)\bмайкрософт(?:а|і|и|у|ом|і|е)?\b"),
    ),
    "nvidia": (
        re.compile(r"(?iu)\bnvidia\b"),
        re.compile(r"(?iu)\b(?:нвідіа|енвідіа|нвидиа|энвидиа)\b"),
    ),
    "tesla": (
        re.compile(r"(?iu)\btesla\b"),
        re.compile(r"(?iu)\bтесл(?:а|и|і|у|ою|ой|е)\b"),
    ),
    "spacex": (
        re.compile(r"(?iu)\bspace\s*x\b"),
        re.compile(r"(?iu)\bспейс\s*ікс\b"),
        re.compile(r"(?iu)\bспейс\s*икс\b"),
    ),
    "openai": (
        re.compile(r"(?iu)\bopen\s*ai\b"),
        re.compile(r"(?iu)\bоупен\s*(?:ейай|аи)\b"),
    ),
    "chatgpt": (
        re.compile(r"(?iu)\bchat\s*gpt\b"),
        re.compile(r"(?iu)\bчат\s*джипіті\b"),
        re.compile(r"(?iu)\bчат\s*джипити\b"),
    ),
    "github": (
        re.compile(r"(?iu)\bgithub\b"),
        re.compile(r"(?iu)\bгітхаб(?:а|і|у|ом)?\b"),
        re.compile(r"(?iu)\bгитхаб(?:а|е|у|ом)?\b"),
    ),
    "netflix": (
        re.compile(r"(?iu)\bnetflix\b"),
        re.compile(r"(?iu)\bнетфлікс(?:а|і|у|ом)?\b"),
        re.compile(r"(?iu)\bнетфликс(?:а|е|у|ом)?\b"),
    ),
    "spotify": (
        re.compile(r"(?iu)\bspotify\b"),
        re.compile(r"(?iu)\bспотіфай\b"),
        re.compile(r"(?iu)\bспотифай\b"),
    ),
    "discord": (
        re.compile(r"(?iu)\bdiscord\b"),
        re.compile(r"(?iu)\bдіскорд(?:а|і|у|ом)?\b"),
        re.compile(r"(?iu)\bдискорд(?:а|е|у|ом)?\b"),
    ),
    "twitch": (
        re.compile(r"(?iu)\btwitch\b"),
        re.compile(r"(?iu)\bтвіч(?:а|і|у|ом)?\b"),
        re.compile(r"(?iu)\bтвич(?:а|е|у|ом)?\b"),
    ),
}


def extract_supported_entity_aliases(value: str) -> set[str]:
    text = str(value or "")
    found: set[str] = set()
    for canonical, patterns in _ENTITY_ALIAS_PATTERNS.items():
        if any(pattern.search(text) for pattern in patterns):
            found.add(canonical)
    return found


def guard_rewrite_rc17(
    evidence: str,
    headline: str,
    rewrite: str,
    *,
    language: str = "uk",
) -> FactGuardResult:
    """RC17 Fact Guard with safe canonical-brand equivalence.

    RC16 compared Latin entities literally. A source spelling ``Ютуб`` and a
    perfectly factual rewrite spelling ``YouTube`` therefore looked like a new
    entity. RC17 only relaxes that one class of false positive through a
    curated alias table. Unknown products/models remain strict.
    """

    result = guard_rewrite(evidence, headline, rewrite, language=language)
    if result.allowed or not result.unsupported_entities or not language.casefold().startswith("uk"):
        return result

    source = _factual_evidence(evidence)
    supported_aliases = extract_supported_entity_aliases(source)
    remaining_entities = tuple(
        entity for entity in result.unsupported_entities if entity.casefold() not in supported_aliases
    )
    if remaining_entities == result.unsupported_entities:
        return result

    issues = [
        issue for issue in result.issues
        if not str(issue).startswith("назви/моделі відсутні у поточних джерелах:")
    ]
    if remaining_entities:
        issues.append(
            "назви/моделі відсутні у поточних джерелах: " + ", ".join(remaining_entities[:8])
        )

    allowed = not issues
    score = _quality_score(source, headline, rewrite, language) if allowed else 0
    return FactGuardResult(
        allowed=allowed,
        issues=tuple(issues),
        score=score,
        unsupported_numbers=result.unsupported_numbers,
        unsupported_entities=remaining_entities,
    )
