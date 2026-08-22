from __future__ import annotations

import json
import re

from .ollama_client import OllamaError, _decode_rewrite_payload as _legacy_decode, _strip_code_fence

_STRUCTURAL_MARKER = re.compile(
    r"(?im)^\s*(?:ЗАГОЛОВОК|HEADLINE|ФАКТИ|ФАКТ-КАРТКА|FACTS|FACT\s+CARD|"
    r"ПОЯСНЕННЯ|EXPLANATION|АНАЛІЗ|ANALYSIS|ПРИМІТКА|NOTE)\s*:"
)
_TEXT_MARKER = re.compile(r"(?im)^\s*(?:ТЕКСТ|РЕРАЙТ|TEXT|ARTICLE)\s*:")
_FORBIDDEN_REWRITE_LINE = re.compile(
    r"(?im)^\s*(?:ЗАГОЛОВОК|HEADLINE|ФАКТИ|ФАКТ-КАРТКА|FACTS|FACT\s+CARD|"
    r"ПОЯСНЕННЯ|EXPLANATION|АНАЛІЗ|ANALYSIS|ПРИМІТКА|NOTE)\s*:"
)
_LEADING_PREAMBLE = re.compile(
    r"(?is)^\s*(?:ось\s+(?:рерайт|текст|готовий\s+текст)|here\s+is\s+(?:the\s+)?rewrite)\s*:\s*"
)


def sanitize_publication_rewrite(value: str) -> str:
    """Return only publishable prose, never protocol/debug sections."""

    text = _strip_code_fence(str(value or "")).strip()
    if not text:
        raise OllamaError("Ollama повернула порожній текст рерайту.")
    text = _LEADING_PREAMBLE.sub("", text).strip()
    text = re.sub(r"(?im)^\s*(?:ТЕКСТ|РЕРАЙТ|TEXT|ARTICLE)\s*:\s*", "", text, count=1).strip()
    if _FORBIDDEN_REWRITE_LINE.search(text):
        raise OllamaError(
            "Ollama змішала службові секції із текстом публікації. "
            "Відповідь відхилено, щоб ЗАГОЛОВОК/ФАКТИ/пояснення не потрапили у допис."
        )
    if text.startswith("{") or text.startswith("["):
        raise OllamaError("Сирий JSON або службова структура не може бути текстом публікації.")
    return text


def decode_rewrite_payload_rc3(response_text: str) -> dict[str, object]:
    """Strict wrapper around the legacy decoder used by RC3.

    The old decoder deliberately recovered malformed small-model answers, but one
    fallback could treat the entire marker response as publication prose when the
    literal TEXT marker was missing. RC3 fails closed instead.
    """

    text = _strip_code_fence(str(response_text or ""))
    if not text:
        raise OllamaError("Ollama повернула порожній текст.")

    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        decoded = None
    if isinstance(decoded, dict):
        rewrite = decoded.get("rewrite") or decoded.get("text") or decoded.get("article")
        if not str(rewrite or "").strip():
            raise OllamaError("Ollama повернула структуровану відповідь без тексту рерайту.")
        result = dict(decoded)
        result["rewrite"] = sanitize_publication_rewrite(str(rewrite))
        result.setdefault("headline", str(decoded.get("headline") or ""))
        result.setdefault("fact_card", str(decoded.get("fact_card") or decoded.get("facts") or ""))
        return result

    has_structure = bool(_STRUCTURAL_MARKER.search(text))
    has_text_marker = bool(_TEXT_MARKER.search(text))
    if has_structure and not has_text_marker:
        raise OllamaError(
            "Ollama повернула ЗАГОЛОВОК/ФАКТИ, але не відокремила ТЕКСТ. "
            "Службову відповідь не збережено як публікацію."
        )

    payload = _legacy_decode(text)
    rewrite = sanitize_publication_rewrite(str(payload.get("rewrite") or ""))
    return {
        **payload,
        "rewrite": rewrite,
        "headline": str(payload.get("headline") or "").strip(),
        "fact_card": str(payload.get("fact_card") or "").strip(),
    }
