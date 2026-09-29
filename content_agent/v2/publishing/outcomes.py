from __future__ import annotations

from enum import StrEnum

from .retry import uncertain_publication_reason


class PublicationOutcome(StrEnum):
    NOT_ATTEMPTED = "not_attempted"
    SENT = "sent"
    FAILED_KNOWN = "failed_known"
    UNKNOWN = "unknown"
    CONFIRMED_NOT_SENT = "confirmed_not_sent"


_VALID = {item.value for item in PublicationOutcome}


def normalize_outcome(value: object) -> PublicationOutcome:
    text = str(value or "").strip().casefold()
    if text in _VALID:
        return PublicationOutcome(text)
    return PublicationOutcome.NOT_ATTEMPTED


def derive_outcome(
    *,
    status: object,
    remote_id: object = "",
    last_error: object = "",
    progress_json: object = "{}",
    current: object = "",
) -> PublicationOutcome:
    existing = normalize_outcome(current)
    if existing is PublicationOutcome.CONFIRMED_NOT_SENT:
        return existing
    normalized_status = str(status or "").strip().casefold()
    if normalized_status == "sent" or str(remote_id or "").strip():
        return PublicationOutcome.SENT
    if uncertain_publication_reason(last_error, progress_json):
        return PublicationOutcome.UNKNOWN
    if normalized_status == "failed":
        return PublicationOutcome.FAILED_KNOWN
    return PublicationOutcome.NOT_ATTEMPTED


__all__ = ["PublicationOutcome", "derive_outcome", "normalize_outcome"]
