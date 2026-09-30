from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True, slots=True)
class FactGuardResult:
    allowed: bool
    issues: tuple[str, ...]
    score: int
    unsupported_numbers: tuple[str, ...] = ()
    unsupported_entities: tuple[str, ...] = ()


_METADATA_PREFIXES = ("ДЖЕРЕЛО ", "SOURCE ", "ЧАС:", "TIME:", "URL:")
_GENERIC_LATIN = frozenset({
    "AI", "API", "GPU", "CPU", "RAM", "VRAM", "GB", "MB", "TB", "USB", "SSD", "HDD",
    "HTTP", "HTTPS", "JSON", "RSS", "URL", "HTML", "UA", "FREE", "USD", "EUR",
})
_UNICODE_NUMBER_ALIASES = {"💯": "100", "🔟": "10"}
_KEYCAP_DIGIT_RE = re.compile(r"([0-9])\ufe0f?\u20e3")
_ROMAN_RE = re.compile(r"\b[IVXLCDM]{2,}\b")
_LATIN_TOKEN_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9._+\-/]*\b")

_SCALE_PATTERNS: tuple[tuple[re.Pattern[str], Decimal], ...] = (
    (re.compile(r"(?iu)^(?:тис\.?|тисяч(?:а|і|у|ею)?|тыс\.?|тысяч(?:а|и|у|ей)?|thousand|k)$"), Decimal(1_000)),
    (re.compile(r"(?iu)^(?:млн\.?|мільйон(?:а|ів|и)?|миллион(?:а|ов|ы)?|million)$"), Decimal(1_000_000)),
    (re.compile(r"(?iu)^(?:млрд\.?|мільярд(?:а|ів|и)?|миллиард(?:а|ов|ы)?|billion|bn)$"), Decimal(1_000_000_000)),
)
_UNIT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?iu)^(?:km|км|кілометр(?:а|у|і|ом|и|ів|ами|ах)?|километр(?:а|у|е|ом|ы|ов|ами|ах)?|kilometers?|kilometres?)$"), "km"),
    (re.compile(r"(?iu)^(?:m|м|метр(?:а|у|і|ом|и|ів|ами|ах)?|метр(?:а|у|е|ом|ы|ов|ами|ах)?|meters?|metres?)$"), "m"),
    (re.compile(r"(?iu)^(?:kg|кг|кілограм(?:а|у|і|ом|и|ів|ами|ах)?|килограмм?(?:а|у|е|ом|ы|ов|ами|ах)?|kilograms?)$"), "kg"),
    (re.compile(r"(?iu)^(?:mw|мвт|мегават(?:а|у|і|ом|и|ів|ами|ах)?|мегаватт?(?:а|у|е|ом|ы|ов|ами|ах)?|megawatts?)$"), "mw"),
    (re.compile(r"(?iu)^(?:gw|гвт|гігават(?:а|у|і|ом|и|ів|ами|ах)?|гигаватт?(?:а|у|е|ом|ы|ов|ами|ах)?|gigawatts?)$"), "gw"),
    (re.compile(r"(?iu)^(?:gb|гб|гігабайт(?:а|у|і|ом|и|ів|ами|ах)?|гигабайт(?:а|у|е|ом|ы|ов|ами|ах)?|gigabytes?)$"), "gb"),
    (re.compile(r"(?iu)^(?:mb|мб|мегабайт(?:а|у|і|ом|и|ів|ами|ах)?|мегабайт(?:а|у|е|ом|ы|ов|ами|ах)?|megabytes?)$"), "mb"),
    (re.compile(r"(?iu)^(?:tb|тб|терабайт(?:а|у|і|ом|и|ів|ами|ах)?|терабайт(?:а|у|е|ом|ы|ов|ами|ах)?|terabytes?)$"), "tb"),
)
_CURRENCY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?iu)^(?:usd|\$|дол(?:л?\.?|ар(?:и|а|ів)?|лар(?:а|ів)?)|dollars?)$"), "usd"),
    (re.compile(r"(?iu)^(?:eur|€|євро|евро|euros?)$"), "eur"),
    (re.compile(r"(?iu)^(?:uah|₴|грн|грив(?:ня|ні|ень))$"), "uah"),
)
_SUFFIX_TOKEN_RE = re.compile(
    r"(?iu)(?:тис\.?|тисяч(?:а|і|у|ею)?|тыс\.?|тысяч(?:а|и|у|ей)?|thousand|"
    r"млн\.?|мільйон(?:а|ів|и)?|миллион(?:а|ов|ы)?|million|"
    r"млрд\.?|мільярд(?:а|ів|и)?|миллиард(?:а|ов|ы)?|billion|bn|"
    r"кілометр(?:а|у|і|ом|и|ів|ами|ах)?|километр(?:а|у|е|ом|ы|ов|ами|ах)?|kilometers?|kilometres?|km|км|"
    r"метр(?:а|у|і|ом|и|ів|ами|ах)?|метр(?:а|у|е|ом|ы|ов|ами|ах)?|meters?|metres?|m|м|"
    r"кілограм(?:а|у|і|ом|и|ів|ами|ах)?|килограмм?(?:а|у|е|ом|ы|ов|ами|ах)?|kilograms?|kg|кг|"
    r"мегават(?:а|у|і|ом|и|ів|ами|ах)?|мегаватт?(?:а|у|е|ом|ы|ов|ами|ах)?|megawatts?|mw|мвт|"
    r"гігават(?:а|у|і|ом|и|ів|ами|ах)?|гигаватт?(?:а|у|е|ом|ы|ов|ами|ах)?|gigawatts?|gw|гвт|"
    r"gb|гб|mb|мб|tb|тб|%|usd|eur|uah|грн|₴|\$|€|дол(?:л?\.?|ар(?:и|а|ів)?|лар(?:а|ів)?)|dollars?|євро|евро|euros?)"
)
_NUMBER_RE = re.compile(
    r"(?<!\w)(?:(?P<prefix>[$€₴])\s*|(?P<prefix_word>USD|EUR|UAH)\s+)?"
    r"(?P<number>(?:\d{1,3}(?:[ \u00a0\u202f,'’ʼ]\d{3})+|\d+(?:[.,]\d+)?))"
    r"(?P<suffix>(?:\s*(?:" + _SUFFIX_TOKEN_RE.pattern + r")){0,2})",
    re.IGNORECASE,
)

_HIGH_RISK_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("першість", re.compile(r"(?iu)\b(?:перш(?:ий|а|е|і)\s+(?:у|в)\s+(?:світі|історії)|first[- ]ever|world['’]?s first|перв(?:ый|ая|ое|ые)\s+в\s+мире)\b")),
    ("найбільший", re.compile(r"(?iu)\b(?:найбільш(?:ий|а|е|і)|largest|biggest|крупнейш(?:ий|ая|ее|ие))\b")),
    ("найшвидший", re.compile(r"(?iu)\b(?:найшвидш(?:ий|а|е|і)|fastest|сам(?:ый|ая|ое)\s+быстр\w*)\b")),
    ("найпотужніший", re.compile(r"(?iu)\b(?:найпотужніш(?:ий|а|е|і)|most powerful|сам(?:ый|ая|ое)\s+мощн\w*)\b")),
    ("рекорд", re.compile(r"(?iu)\b(?:рекордн\w*|record[- ]breaking|record\s+(?:high|low))\b")),
)
_UNCERTAINTY_OUTPUT = re.compile(r"(?iu)\b(?:можливо|ймовірно|схоже|might|may|could|reportedly|likely|possibly|возможно|вероятно)\b")
_SOURCE_UNCERTAINTY = re.compile(r"(?iu)\b(?:можливо|ймовірно|схоже|планує|планують|очікує|очікується|за даними|за словами|заявив|повідомив|might|may|could|plans?|expected|reportedly|according to|said|возможно|вероятно|планирует|ожидается|по данным|заявил|сообщил)\b")


def _normalize_numeric_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = _KEYCAP_DIGIT_RE.sub(lambda m: m.group(1), text)
    for token, replacement in _UNICODE_NUMBER_ALIASES.items():
        text = text.replace(token, replacement)
    return text


def _parse_decimal(raw: str) -> Decimal | None:
    value = str(raw or "").strip().replace("\u00a0", " ").replace("\u202f", " ")
    if re.fullmatch(r"[1-9]\d{0,2}(?:[ ,'’ʼ]\d{3})+", value):
        value = re.sub(r"[ ,'’ʼ]", "", value)
    else:
        value = value.replace(" ", "")
        if "," in value and "." not in value:
            value = value.replace(",", ".")
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return None


def _decimal_text(value: Decimal) -> str:
    if value == value.to_integral():
        return str(int(value))
    return format(value.normalize(), "f").rstrip("0").rstrip(".")


def _scale_for(token: str) -> Decimal | None:
    clean = str(token or "").strip().casefold()
    for pattern, multiplier in _SCALE_PATTERNS:
        if pattern.fullmatch(clean):
            return multiplier
    return None


def _unit_for(token: str) -> str | None:
    clean = str(token or "").strip().casefold()
    if clean == "%":
        return "%"
    for pattern, canonical in (*_UNIT_PATTERNS, *_CURRENCY_PATTERNS):
        if pattern.fullmatch(clean):
            return canonical
    return None


def _canon_number_match(match: re.Match[str]) -> str:
    base = _parse_decimal(match.group("number"))
    if base is None:
        return ""
    scale = Decimal(1)
    unit = _unit_for(match.group("prefix") or match.group("prefix_word") or "")
    for token_match in _SUFFIX_TOKEN_RE.finditer(match.group("suffix") or ""):
        token = token_match.group(0)
        multiplier = _scale_for(token)
        if multiplier is not None:
            scale = multiplier
        else:
            candidate = _unit_for(token)
            if candidate is not None:
                unit = candidate
    canonical = _decimal_text(base * scale)
    return canonical + (f" {unit}" if unit else "")


def _int_to_roman(value: int) -> str:
    if not 0 < value <= 3999:
        return ""
    pairs = ((1000,"M"),(900,"CM"),(500,"D"),(400,"CD"),(100,"C"),(90,"XC"),(50,"L"),(40,"XL"),(10,"X"),(9,"IX"),(5,"V"),(4,"IV"),(1,"I"))
    result: list[str] = []
    remaining = value
    for amount, token in pairs:
        while remaining >= amount:
            result.append(token)
            remaining -= amount
    return "".join(result)


def _roman_to_int(token: str) -> int | None:
    clean = str(token or "").upper()
    if len(clean) < 2 or not re.fullmatch(r"[IVXLCDM]+", clean):
        return None
    values = {"I":1,"V":5,"X":10,"L":50,"C":100,"D":500,"M":1000}
    total = 0
    for i, char in enumerate(clean):
        current = values[char]
        total += -current if i + 1 < len(clean) and current < values[clean[i+1]] else current
    return total if _int_to_roman(total) == clean else None


def extract_numbers(value: str) -> set[str]:
    text = _normalize_numeric_text(value)
    result: set[str] = set()
    for match in _NUMBER_RE.finditer(text):
        canonical = _canon_number_match(match)
        if canonical:
            result.add(canonical)
    for match in _ROMAN_RE.finditer(text):
        value_int = _roman_to_int(match.group(0))
        if value_int is not None:
            result.add(str(value_int))
    return result


def _is_strong_latin_token(token: str) -> bool:
    clean = str(token or "").strip(".,:;!?()[]{}«»\"'")
    if len(clean) < 2 or clean.upper() in _GENERIC_LATIN or _roman_to_int(clean) is not None:
        return False
    if any(ch.isdigit() for ch in clean) or any(ch in "._+-/" for ch in clean):
        return True
    letters = [ch for ch in clean if ch.isalpha()]
    if not letters:
        return False
    if any(ch.isupper() for ch in letters) and any(ch.islower() for ch in letters) and not (clean[:1].isupper() and clean[1:].islower()):
        return True
    if clean.isupper() and 2 <= len(clean) <= 5:
        return True
    # Product/model families that are routinely proper names but surface as a
    # single TitleCase token. Keep this narrow to avoid treating ordinary English
    # prose as invented entities.
    if re.fullmatch(r"(?i)(?:cyber(?:cab|truck)|modelx)", clean):
        return True
    return False


def extract_latin_entities(value: str) -> set[str]:
    result: set[str] = set()
    for token in _LATIN_TOKEN_RE.findall(str(value or "")):
        if _is_strong_latin_token(token):
            result.add(token.casefold())
    return result


def _factual_evidence(value: str) -> str:
    rows: list[str] = []
    for raw in str(value or "").splitlines():
        stripped = raw.strip()
        upper = stripped.upper()
        if any(upper.startswith(prefix) for prefix in _METADATA_PREFIXES) or stripped == "---":
            continue
        rows.append(raw)
    return "\n".join(rows)


def _unsupported_high_risk(evidence: str, output: str) -> list[str]:
    return [f"непідтверджене посилення: {label}" for label, pattern in _HIGH_RISK_RULES if pattern.search(output) and not pattern.search(evidence)]


def _quality_score(evidence: str, headline: str, rewrite: str, language: str) -> int:
    score = 86
    source_numbers = extract_numbers(evidence)
    output_numbers = extract_numbers(f"{headline}\n{rewrite}")
    if source_numbers:
        if not output_numbers:
            score -= min(8, 2 + len(source_numbers) * 2)
        else:
            score += round(min(6.0, (len(source_numbers & output_numbers) / max(1, len(source_numbers))) * 6.0))
    if language.casefold().startswith("uk"):
        source_entities = extract_latin_entities(evidence)
        output_entities = extract_latin_entities(f"{headline}\n{rewrite}")
        if source_entities and output_entities:
            score += round(min(6.0, (len(source_entities & output_entities) / max(1, len(output_entities))) * 6.0))
    sentences = [" ".join(part.split()).casefold() for part in re.split(r"(?<=[.!?…])\s+", rewrite) if part.strip()]
    if len(sentences) >= 2 and len(set(sentences)) < len(sentences):
        score -= 10
    return max(0, min(100, score))


def guard_rewrite(evidence: str, headline: str, rewrite: str, *, language: str = "uk") -> FactGuardResult:
    source = _factual_evidence(evidence)
    output = f"{headline}\n{rewrite}".strip()
    issues: list[str] = []
    unsupported_numbers = sorted(extract_numbers(output) - extract_numbers(source))
    if unsupported_numbers:
        issues.append("числа/дати відсутні у поточних джерелах: " + ", ".join(unsupported_numbers[:8]))
    unsupported_entities: list[str] = []
    if language.casefold().startswith("uk"):
        unsupported_entities = sorted(extract_latin_entities(output) - extract_latin_entities(source))
        if unsupported_entities:
            issues.append("назви/моделі відсутні у поточних джерелах: " + ", ".join(unsupported_entities[:8]))
    issues.extend(_unsupported_high_risk(source, output))
    if _UNCERTAINTY_OUTPUT.search(output) and not _SOURCE_UNCERTAINTY.search(source):
        issues.append("додано непідтверджену невизначеність або припущення")
    score = 0 if issues else _quality_score(source, headline, rewrite, language)
    return FactGuardResult(not issues, tuple(issues), score, tuple(unsupported_numbers), tuple(unsupported_entities))
