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


# Fact Guard is deliberately deterministic. It compares factual tokens in the
# current Evidence Pack only; editorial memory and transport metadata never
# authorize a number/model in the public rewrite.
_METADATA_PREFIXES = ("ДЖЕРЕЛО ", "SOURCE ", "ЧАС:", "TIME:", "URL:")
_KEYCAP_DIGIT_RE = re.compile(r"([0-9])\ufe0f?\u20e3")
_ROMAN_RE = re.compile(r"\b[IVXLCDM]{2,}\b")
_UNICODE_NUMBER_ALIASES = {"💯": "100", "🔟": "10"}

_SCALE_PATTERNS: tuple[tuple[re.Pattern[str], Decimal], ...] = (
    (re.compile(r"^(?:тис\.?|тисяч(?:а|і|у|ею)?|тыс\.?|тысяч(?:а|и|у|ей)?|thousand|k)$", re.I), Decimal(1_000)),
    (re.compile(r"^(?:млн\.?|мільйон(?:а|ів|и)?|миллион(?:а|ов|ы)?|million)$", re.I), Decimal(1_000_000)),
    (re.compile(r"^(?:млрд\.?|мільярд(?:а|ів|и)?|миллиард(?:а|ов|ы)?|billion|bn)$", re.I), Decimal(1_000_000_000)),
)

_UNIT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^(?:км|km|кілометр(?:а|у|і|ом|и|ів|ами|ах)?|километр(?:а|у|е|ом|ы|ов|ами|ах)?|kilometers?|kilometres?)$", re.I), "km"),
    (re.compile(r"^(?:м|m|метр(?:а|у|і|ом|и|ів|ами|ах)?|метр(?:а|у|е|ом|ы|ов|ами|ах)?|meters?|metres?)$", re.I), "m"),
    (re.compile(r"^(?:кг|kg|кілограм(?:а|у|і|ом|и|ів|ами|ах)?|килограмм?(?:а|у|е|ом|ы|ов|ами|ах)?|kilograms?)$", re.I), "kg"),
    (re.compile(r"^(?:мвт|mw|мегават(?:а|у|і|ом|и|ів|ами|ах)?|мегаватт?(?:а|у|е|ом|ы|ов|ами|ах)?|megawatts?)$", re.I), "mw"),
    (re.compile(r"^(?:гвт|gw|гігават(?:а|у|і|ом|и|ів|ами|ах)?|гигаватт?(?:а|у|е|ом|ы|ов|ами|ах)?|gigawatts?)$", re.I), "gw"),
    (re.compile(r"^(?:гб|gb|гігабайт(?:а|у|і|ом|и|ів|ами|ах)?|гигабайт(?:а|у|е|ом|ы|ов|ами|ах)?|gigabytes?)$", re.I), "gb"),
    (re.compile(r"^(?:мб|mb|мегабайт(?:а|у|і|ом|и|ів|ами|ах)?|мегабайт(?:а|у|е|ом|ы|ов|ами|ах)?|megabytes?)$", re.I), "mb"),
    (re.compile(r"^(?:тб|tb|терабайт(?:а|у|і|ом|и|ів|ами|ах)?|терабайт(?:а|у|е|ом|ы|ов|ами|ах)?|terabytes?)$", re.I), "tb"),
    (re.compile(r"^(?:usd|\$|дол(?:л?\.?|ар(?:и|а|ів)?|лар(?:а|ів)?)|dollars?)$", re.I), "usd"),
    (re.compile(r"^(?:eur|€|євро|евро|euros?)$", re.I), "eur"),
    (re.compile(r"^(?:uah|₴|грн|грив(?:ня|ні|ень))$", re.I), "uah"),
    (re.compile(r"^%$"), "%"),
)

# Number + at most two factual suffix tokens. The suffix requires a real token
# boundary, so the short unit "м" cannot eat the first letter of "моделей".
_NUMBER_RE = re.compile(
    r"(?<!\w)"
    r"(?:(?P<prefix>[$€₴])\s*|(?P<prefix_word>USD|EUR|UAH)\s+)?"
    r"(?P<number>(?:\d{1,3}(?:[ \u00a0\u202f,'’ʼ]\d{3})+|\d+(?:[.,]\d+)?))"
    r"(?P<suffix>(?:\s*(?:"
    r"%|тис\.?|тисяч(?:а|і|у|ею)?|тыс\.?|тысяч(?:а|и|у|ей)?|thousand|"
    r"млн\.?|мільйон(?:а|ів|и)?|миллион(?:а|ов|ы)?|million|"
    r"млрд\.?|мільярд(?:а|ів|и)?|миллиард(?:а|ов|ы)?|billion|bn|k|"
    r"км|km|м|m|кг|kg|гб|gb|мб|mb|тб|tb|мвт|mw|гвт|gw|"
    r"кілометр(?:а|у|і|ом|и|ів|ами|ах)?|километр(?:а|у|е|ом|ы|ов|ами|ах)?|kilometers?|kilometres?|"
    r"метр(?:а|у|і|ом|и|ів|ами|ах)?|метр(?:а|у|е|ом|ы|ов|ами|ах)?|meters?|metres?|"
    r"кілограм(?:а|у|і|ом|и|ів|ами|ах)?|килограмм?(?:а|у|е|ом|ы|ов|ами|ах)?|kilograms?|"
    r"мегават(?:а|у|і|ом|и|ів|ами|ах)?|мегаватт?(?:а|у|е|ом|ы|ов|ами|ах)?|megawatts?|"
    r"гігават(?:а|у|і|ом|и|ів|ами|ах)?|гигаватт?(?:а|у|е|ом|ы|ов|ами|ах)?|gigawatts?|"
    r"usd|eur|uah|грн|грив(?:ня|ні|ень)|дол(?:л?\.?|ар(?:и|а|ів)?|лар(?:а|ів)?)|dollars?|євро|евро|euros?|₴|\$|€"
    r")(?![A-Za-zА-Яа-яІіЇїЄєҐґ])){0,2})",
    re.I,
)
_SUFFIX_TOKEN_RE = re.compile(
    r"%|тис\.?|тисяч(?:а|і|у|ею)?|тыс\.?|тысяч(?:а|и|у|ей)?|thousand|"
    r"млн\.?|мільйон(?:а|ів|и)?|миллион(?:а|ов|ы)?|million|"
    r"млрд\.?|мільярд(?:а|ів|и)?|миллиард(?:а|ов|ы)?|billion|bn|k|"
    r"км|km|м|m|кг|kg|гб|gb|мб|mb|тб|tb|мвт|mw|гвт|gw|"
    r"кілометр(?:а|у|і|ом|и|ів|ами|ах)?|километр(?:а|у|е|ом|ы|ов|ами|ах)?|kilometers?|kilometres?|"
    r"метр(?:а|у|і|ом|и|ів|ами|ах)?|метр(?:а|у|е|ом|ы|ов|ами|ах)?|meters?|metres?|"
    r"кілограм(?:а|у|і|ом|и|ів|ами|ах)?|килограмм?(?:а|у|е|ом|ы|ов|ами|ах)?|kilograms?|"
    r"мегават(?:а|у|і|ом|и|ів|ами|ах)?|мегаватт?(?:а|у|е|ом|ы|ов|ами|ах)?|megawatts?|"
    r"гігават(?:а|у|і|ом|и|ів|ами|ах)?|гигаватт?(?:а|у|е|ом|ы|ов|ами|ах)?|gigawatts?|"
    r"usd|eur|uah|грн|грив(?:ня|ні|ень)|дол(?:л?\.?|ар(?:и|а|ів)?|лар(?:а|ів)?)|dollars?|євро|евро|euros?|₴|\$|€",
    re.I,
)

_LATIN_TOKEN_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9._+\-/]*\b")
_LATIN_STOP = frozenset(
    "a an and are as at be been by for from has have in is it its of on or that the this to was were will with "
    "destroy signal keep you safe story continues list focus television history new system company tested hardware top first world".split()
)
_GENERIC_LATIN = frozenset({"ai", "api", "gpu", "cpu", "ram", "vram", "gb", "mb", "tb", "usb", "ssd", "hdd", "http", "https", "json", "rss", "url", "html", "ua", "free", "usd", "eur"})

_HIGH_RISK = (
    ("першість", re.compile(r"\b(?:перш(?:ий|а|е|і)\s+(?:у|в)\s+(?:світі|історії)|first[- ]ever|world['’]?s first|перв(?:ый|ая|ое|ые)\s+в\s+мире)\b", re.I)),
    ("найбільший", re.compile(r"\b(?:найбільш(?:ий|а|е|і)|largest|biggest|крупнейш\w*)\b", re.I)),
    ("найшвидший", re.compile(r"\b(?:найшвидш\w*|fastest|сам\w*\s+быстр\w*)\b", re.I)),
    ("найпотужніший", re.compile(r"\b(?:найпотужніш\w*|most powerful|сам\w*\s+мощн\w*)\b", re.I)),
    ("рекорд", re.compile(r"\b(?:рекордн\w*|record[- ]breaking|record\s+(?:high|low))\b", re.I)),
)
_UNCERTAINTY_OUTPUT = re.compile(r"\b(?:можливо|ймовірно|схоже|може|можуть|might|may|could|reportedly|likely|possibly|возможно|вероятно|может|могут)\b", re.I)
_SOURCE_UNCERTAINTY = re.compile(r"\b(?:можливо|ймовірно|схоже|може|можуть|планує|планують|очікує|очікується|за даними|за словами|заявив|повідомив|might|may|could|plans?|expected|reportedly|according to|said|возможно|вероятно|может|могут|планирует|ожидается|по данным|заявил|сообщил)\b", re.I)


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
    for pattern, canonical in _UNIT_PATTERNS:
        if pattern.fullmatch(clean):
            return canonical
    return None


def _roman_to_int(token: str) -> int | None:
    clean = str(token or "").strip().upper()
    if len(clean) < 2 or not re.fullmatch(r"[IVXLCDM]+", clean):
        return None
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    for index, char in enumerate(clean):
        value = values[char]
        total += -value if index + 1 < len(clean) and value < values[clean[index + 1]] else value
    if not 0 < total <= 3999:
        return None
    # reject malformed Roman strings by round-tripping the normal forms needed
    # by editorial content (centuries, ordinals, model generations).
    pairs = ((1000,"M"),(900,"CM"),(500,"D"),(400,"CD"),(100,"C"),(90,"XC"),(50,"L"),(40,"XL"),(10,"X"),(9,"IX"),(5,"V"),(4,"IV"),(1,"I"))
    remaining = total
    out = []
    for amount, symbol in pairs:
        while remaining >= amount:
            out.append(symbol); remaining -= amount
    return total if "".join(out) == clean else None


def extract_numbers(value: str) -> set[str]:
    text = _normalize_numeric_text(value)
    result: set[str] = set()
    for match in _NUMBER_RE.finditer(text):
        base = _parse_decimal(match.group("number"))
        if base is None:
            continue
        scale = Decimal(1)
        unit = _unit_for(match.group("prefix") or match.group("prefix_word") or "")
        for suffix_match in _SUFFIX_TOKEN_RE.finditer(match.group("suffix") or ""):
            token = suffix_match.group(0)
            multiplier = _scale_for(token)
            if multiplier is not None:
                scale = multiplier
            else:
                found_unit = _unit_for(token)
                if found_unit is not None:
                    unit = found_unit
        canonical = _decimal_text(base * scale)
        result.add(canonical + (f" {unit}" if unit else ""))
    for match in _ROMAN_RE.finditer(text):
        value_int = _roman_to_int(match.group(0))
        if value_int is not None:
            result.add(str(value_int))
    return result


def extract_latin_entities(value: str) -> set[str]:
    result: set[str] = set()
    for token in _LATIN_TOKEN_RE.findall(str(value or "")):
        clean = token.strip(".,:;!?()[]{}\"'")
        folded = clean.casefold()
        if len(clean) < 2 or folded in _LATIN_STOP or folded in _GENERIC_LATIN:
            continue
        if _roman_to_int(clean) is not None:
            continue
        if any(ch.isdigit() for ch in clean) or any(ch in "._+-/" for ch in clean):
            result.add(folded)
            continue
        letters = [ch for ch in clean if ch.isalpha()]
        if not letters:
            continue
        # Mixed/camel case names such as OpenAI are strong identifiers. Capitalized
        # model/product names such as Cybercab/Cybertruck are also retained, while
        # ordinary lowercase English prose is deliberately ignored.
        if any(ch.isupper() for ch in clean[1:]) or (clean[0].isupper() and len(clean) >= 6):
            result.add(folded)
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


def _quality_score(evidence: str, headline: str, rewrite: str, language: str) -> int:
    score = 86
    source_numbers = extract_numbers(evidence)
    output_numbers = extract_numbers(f"{headline}\n{rewrite}")
    if source_numbers and output_numbers:
        score += round(min(6.0, len(source_numbers & output_numbers) / max(1, len(source_numbers)) * 6.0))
    plain_source = " ".join(evidence.split())
    plain_rewrite = " ".join(rewrite.split())
    if len(plain_source) <= 700 and len(plain_rewrite) > 700:
        score -= 8
    return max(0, min(100, score))


def guard_rewrite(evidence: str, headline: str, rewrite: str, *, language: str = "uk") -> FactGuardResult:
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

    for label, pattern in _HIGH_RISK:
        if pattern.search(output) and not pattern.search(source):
            issues.append(f"непідтверджене посилення: {label}")

    if _UNCERTAINTY_OUTPUT.search(output) and not _SOURCE_UNCERTAINTY.search(source):
        issues.append("додано непідтверджену невизначеність або припущення")

    return FactGuardResult(
        allowed=not issues,
        issues=tuple(issues),
        score=0 if issues else _quality_score(source, headline, rewrite, language),
        unsupported_numbers=tuple(unsupported_numbers),
        unsupported_entities=tuple(unsupported_entities),
    )


__all__ = ["FactGuardResult", "extract_numbers", "extract_latin_entities", "guard_rewrite"]
