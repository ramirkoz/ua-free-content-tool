from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

_NUMBER_RE = re.compile(
    r"(?<![\w])"
    r"(?:(?P<prefix>[$€₴])\s*|(?P<prefix_word>USD|EUR|UAH)\s+)?"
    r"(?P<number>"
    r"(?:\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d{1,3}(?:,\d{3})+|\d+(?:[.,]\d+)?)"
    r")"
    r"(?P<suffix>"
    r"(?:\s*(?:"
    r"%|"
    r"тис\.?|тисяч(?:а|і|у|ею)?|тыс\.?|тысяч(?:а|и|у|ей)?|thousand|"
    r"млн\.?|мільйон(?:а|ів|и)?|миллион(?:а|ов|ы)?|million|"
    r"млрд\.?|мільярд(?:а|ів|и)?|миллиард(?:а|ов|ы)?|billion|bn|"
    r"km|км|kg|кг|gb|гб|mb|мб|tb|тб|mw|мвт|gw|гвт|m|м|k(?![a-zа-яіїєґ])|"
    r"usd|eur|uah|грн|грив(?:ня|ні|ень)|дол(?:л?\.?|ар(?:и|а|ів)?|лар(?:а|ів)?)|"
    r"dollars?|євро|евро|euros?|₴|\$|€"
    r")){0,2}"
    r")",
    re.IGNORECASE,
)
_SUFFIX_TOKEN_RE = re.compile(
    r"(?iu)%|"
    r"тис\.?|тисяч(?:а|і|у|ею)?|тыс\.?|тысяч(?:а|и|у|ей)?|thousand|"
    r"млн\.?|мільйон(?:а|ів|и)?|миллион(?:а|ов|ы)?|million|"
    r"млрд\.?|мільярд(?:а|ів|и)?|миллиард(?:а|ов|ы)?|billion|bn|"
    r"km|км|kg|кг|gb|гб|mb|мб|tb|тб|mw|мвт|gw|гвт|m|м|k(?![a-zа-яіїєґ])|"
    r"usd|eur|uah|грн|грив(?:ня|ні|ень)|дол(?:л?\.?|ар(?:и|а|ів)?|лар(?:а|ів)?)|"
    r"dollars?|євро|евро|euros?|₴|\$|€"
)
_LATIN_ENTITY_RE = re.compile(
    r"\b(?:[A-Z][A-Za-z0-9]*(?:[._+\-/][A-Za-z0-9]+)*|[A-Z]{2,}[A-Z0-9._+\-/]*|[A-Za-z]+\d+[A-Za-z0-9._+\-/]*)\b"
)
_GENERIC_LATIN = frozenset({
    "AI", "API", "GPU", "CPU", "RAM", "VRAM", "GB", "MB", "TB", "USB", "SSD", "HDD",
    "HTTP", "HTTPS", "JSON", "RSS", "URL", "HTML", "UA", "FREE", "USD", "EUR",
})
_METADATA_PREFIXES = (
    "ДЖЕРЕЛО ",
    "SOURCE ",
    "ЧАС:",
    "TIME:",
    "URL:",
)

_SCALE_ALIASES: tuple[tuple[re.Pattern[str], Decimal], ...] = (
    (re.compile(r"(?iu)^(?:тис\.?|тисяч(?:а|і|у|ею)?|тыс\.?|тысяч(?:а|и|у|ей)?|thousand|k)$"), Decimal(1000)),
    (re.compile(r"(?iu)^(?:млн\.?|мільйон(?:а|ів|и)?|миллион(?:а|ов|ы)?|million)$"), Decimal(1_000_000)),
    (re.compile(r"(?iu)^(?:млрд\.?|мільярд(?:а|ів|и)?|миллиард(?:а|ов|ы)?|billion|bn)$"), Decimal(1_000_000_000)),
)
_UNIT_ALIASES: dict[str, str] = {
    "%": "%",
    "km": "km",
    "км": "km",
    "m": "m",
    "м": "m",
    "kg": "kg",
    "кг": "kg",
    "gb": "gb",
    "гб": "gb",
    "mb": "mb",
    "мб": "mb",
    "tb": "tb",
    "тб": "tb",
    "mw": "mw",
    "мвт": "mw",
    "gw": "gw",
    "гвт": "gw",
    "usd": "usd",
    "$": "usd",
    "eur": "eur",
    "€": "eur",
    "uah": "uah",
    "грн": "uah",
    "₴": "uah",
}
_CURRENCY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?iu)^грив(?:ня|ні|ень)$"), "uah"),
    (re.compile(r"(?iu)^дол(?:л?\.?|ар(?:и|а|ів)?|лар(?:а|ів)?)$"), "usd"),
    (re.compile(r"(?iu)^dollars?$"), "usd"),
    (re.compile(r"(?iu)^(?:євро|евро|euros?)$"), "eur"),
)

_HIGH_RISK_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "першість",
        re.compile(
            r"(?iu)\b(?:перш(?:ий|а|е|і)\s+(?:у\s+світі|в\s+світі|в\s+історії)|"
            r"first[- ]ever|world['’]?s first|перв(?:ый|ая|ое|ые)\s+в\s+мире)\b"
        ),
    ),
    (
        "найбільший",
        re.compile(r"(?iu)\b(?:найбільш(?:ий|а|е|і)|largest|biggest|крупнейш(?:ий|ая|ее|ие))\b"),
    ),
    (
        "найшвидший",
        re.compile(r"(?iu)\b(?:найшвидш(?:ий|а|е|і)|fastest|сам(?:ый|ая|ое)\s+быстр\w*)\b"),
    ),
    (
        "найпотужніший",
        re.compile(r"(?iu)\b(?:найпотужніш(?:ий|а|е|і)|most powerful|сам(?:ый|ая|ое)\s+мощн\w*)\b"),
    ),
    (
        "рекорд",
        re.compile(r"(?iu)\b(?:рекордн(?:ий|а|е|і|ого|ої)|record[- ]breaking|record\s+(?:high|low)|рекордн\w*)\b"),
    ),
)

_UNCERTAINTY_OUTPUT = re.compile(
    r"(?iu)\b(?:можливо|ймовірно|схоже|може|можуть|might|may|could|reportedly|likely|possibly|"
    r"возможно|вероятно|может|могут)\b"
)
_SOURCE_UNCERTAINTY = re.compile(
    r"(?iu)\b(?:можливо|ймовірно|схоже|може|можуть|планує|планують|очікує|очікується|"
    r"за даними|за словами|заявив|повідомив|might|may|could|plans?|expected|reportedly|according to|said|"
    r"возможно|вероятно|может|могут|планирует|ожидается|по данным|заявил|сообщил)\b"
)


@dataclass(frozen=True, slots=True)
class FactGuardResult:
    allowed: bool
    issues: tuple[str, ...]
    score: int
    unsupported_numbers: tuple[str, ...] = ()
    unsupported_entities: tuple[str, ...] = ()


def _parse_decimal(raw: str) -> Decimal | None:
    value = str(raw or "").strip().replace("\u00a0", " ").replace("\u202f", " ")
    compact = value.replace(" ", "")
    if re.fullmatch(r"[1-9]\d{0,2}(?:,\d{3})+", compact):
        compact = compact.replace(",", "")
    elif "," in compact and "." not in compact:
        compact = compact.replace(",", ".")
    try:
        return Decimal(compact)
    except (InvalidOperation, ValueError):
        return None


def _decimal_text(value: Decimal) -> str:
    if value == value.to_integral():
        return str(int(value))
    return format(value.normalize(), "f").rstrip("0").rstrip(".")


def _scale_for(token: str) -> Decimal | None:
    clean = str(token or "").strip().casefold()
    for pattern, multiplier in _SCALE_ALIASES:
        if pattern.fullmatch(clean):
            return multiplier
    return None


def _unit_for(token: str) -> str | None:
    clean = str(token or "").strip().casefold()
    if clean in _UNIT_ALIASES:
        return _UNIT_ALIASES[clean]
    for pattern, canonical in _CURRENCY_PATTERNS:
        if pattern.fullmatch(clean):
            return canonical
    return None


def _canon_number_match(match: re.Match[str]) -> str:
    base = _parse_decimal(match.group("number"))
    if base is None:
        return ""
    scale = Decimal(1)
    unit = _unit_for(match.group("prefix") or match.group("prefix_word") or "")
    suffix = match.group("suffix") or ""
    for token_match in _SUFFIX_TOKEN_RE.finditer(suffix):
        token = token_match.group(0)
        multiplier = _scale_for(token)
        if multiplier is not None:
            scale = multiplier
            continue
        candidate_unit = _unit_for(token)
        if candidate_unit is not None:
            unit = candidate_unit
    value = base * scale
    canonical = _decimal_text(value)
    return canonical + (f" {unit}" if unit else "")


def _factual_evidence(value: str) -> str:
    """Remove Evidence Pack transport metadata before factual comparison.

    Source index, fetch/publication time and URL help the model understand the
    dossier but they are not evidence that an event happened in that year or
    that a number belongs in the public rewrite.
    """

    rows: list[str] = []
    for raw in str(value or "").splitlines():
        stripped = raw.strip()
        upper = stripped.upper()
        if any(upper.startswith(prefix) for prefix in _METADATA_PREFIXES):
            continue
        if stripped == "---":
            continue
        rows.append(raw)
    return "\n".join(rows)


def extract_numbers(value: str) -> set[str]:
    result: set[str] = set()
    for match in _NUMBER_RE.finditer(str(value or "")):
        canonical = _canon_number_match(match)
        if canonical:
            result.add(canonical)
    return result


def extract_latin_entities(value: str) -> set[str]:
    result: set[str] = set()
    for token in _LATIN_ENTITY_RE.findall(str(value or "")):
        clean = token.strip(".,:;!?()[]{}«»\"'")
        if len(clean) < 3 or clean.upper() in _GENERIC_LATIN:
            continue
        if clean[0].isupper() and (any(ch.isupper() for ch in clean[1:]) or any(ch.isdigit() for ch in clean) or any(ch in "._+-/" for ch in clean)):
            result.add(clean.casefold())
        elif clean.isupper():
            result.add(clean.casefold())
        elif clean[0].isupper() and any(ch.islower() for ch in clean[1:]):
            result.add(clean.casefold())
    return result


def _unsupported_high_risk(evidence: str, output: str) -> list[str]:
    issues: list[str] = []
    for label, pattern in _HIGH_RISK_RULES:
        if pattern.search(output) and not pattern.search(evidence):
            issues.append(f"непідтверджене посилення: {label}")
    return issues


def _repetition_penalty(rewrite: str) -> int:
    sentences = [" ".join(part.split()).casefold() for part in re.split(r"(?<=[.!?…])\s+", rewrite) if part.strip()]
    if len(sentences) < 2:
        return 0
    unique = len(set(sentences))
    return 10 if unique < len(sentences) else 0


def _quality_score(evidence: str, headline: str, rewrite: str, language: str) -> int:
    score = 86
    source_numbers = extract_numbers(evidence)
    output_numbers = extract_numbers(f"{headline}\n{rewrite}")
    if source_numbers:
        if not output_numbers:
            score -= min(8, 2 + len(source_numbers) * 2)
        else:
            covered = len(source_numbers & output_numbers) / max(1, len(source_numbers))
            score += round(min(6.0, covered * 6.0))
    if language.casefold().startswith("uk"):
        source_entities = extract_latin_entities(evidence)
        output_entities = extract_latin_entities(f"{headline}\n{rewrite}")
        if source_entities and output_entities:
            covered = len(source_entities & output_entities) / max(1, len(output_entities))
            score += round(min(6.0, covered * 6.0))
    evidence_plain = " ".join(evidence.split())
    rewrite_plain = " ".join(rewrite.split())
    if len(evidence_plain) <= 700 and len(rewrite_plain) > 700:
        score -= 8
    if len(rewrite_plain) < 80 and len(evidence_plain) > 1200:
        score -= 6
    score -= _repetition_penalty(rewrite)
    return max(0, min(100, score))


def guard_rewrite(
    evidence: str,
    headline: str,
    rewrite: str,
    *,
    language: str = "uk",
) -> FactGuardResult:
    """Reject deterministic factual strengthening unsupported by current sources.

    Editorial memory is deliberately absent from ``evidence``. Evidence Pack
    transport metadata is also excluded from factual matching. Therefore an old
    memory fact or a source timestamp cannot silently authorize a new claim.

    Numeric facts are compared semantically across common RU/UA/EN forms, so
    ``500 тыс.``, ``500 тис.``, ``500 thousand`` and ``500,000`` are treated as
    the same quantity instead of as four unrelated strings.
    """

    source = _factual_evidence(evidence)
    output = f"{headline}\n{rewrite}".strip()
    issues: list[str] = []

    source_numbers = extract_numbers(source)
    output_numbers = extract_numbers(output)
    unsupported_numbers = sorted(output_numbers - source_numbers)
    if unsupported_numbers:
        issues.append("числа/дати відсутні у поточних джерелах: " + ", ".join(unsupported_numbers[:8]))

    unsupported_entities: list[str] = []
    if language.casefold().startswith("uk"):
        source_entities = extract_latin_entities(source)
        output_entities = extract_latin_entities(output)
        unsupported_entities = sorted(output_entities - source_entities)
        if unsupported_entities:
            issues.append("назви/моделі відсутні у поточних джерелах: " + ", ".join(unsupported_entities[:8]))

    issues.extend(_unsupported_high_risk(source, output))

    if _UNCERTAINTY_OUTPUT.search(output) and not _SOURCE_UNCERTAINTY.search(source):
        issues.append("додано непідтверджену невизначеність або припущення")

    score = 0 if issues else _quality_score(source, headline, rewrite, language)
    return FactGuardResult(
        allowed=not issues,
        issues=tuple(issues),
        score=score,
        unsupported_numbers=tuple(unsupported_numbers),
        unsupported_entities=tuple(unsupported_entities),
    )
