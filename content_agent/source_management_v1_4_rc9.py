from __future__ import annotations

from urllib.parse import parse_qs, urlsplit


SOURCE_KINDS = ("rss", "telegram", "url")
SOURCE_KIND_CHOICES = ("auto", *SOURCE_KINDS)

_TELEGRAM_HOSTS = {
    "t.me",
    "www.t.me",
    "telegram.me",
    "www.telegram.me",
    "telegram.dog",
    "www.telegram.dog",
}
_RSS_PATH_PARTS = {"feed", "feeds", "rss", "rss2", "atom"}
_RSS_SUFFIXES = (".rss", ".xml", ".atom", ".rdf")


def detect_source_kind(address: str) -> str:
    """Infer the collector type from an address without network access.

    This deliberately uses only strong syntactic signals. A normal HTTP(S) URL is
    treated as a web page unless its path/query clearly looks like a feed. Users
    can still explicitly override the result in the UI for unusual feed URLs.
    """

    raw = str(address or "").strip()
    if not raw:
        return "url"
    lowered = raw.casefold()
    if raw.startswith("@") and len(raw) > 1:
        return "telegram"
    if lowered.startswith(("tg://", "telegram://")):
        return "telegram"
    if lowered.startswith("feed://"):
        return "rss"

    candidate = raw if "://" in raw else f"https://{raw}"
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return "url"

    host = (parsed.hostname or "").casefold()
    if host in _TELEGRAM_HOSTS:
        return "telegram"

    path = (parsed.path or "").casefold().rstrip("/")
    if path.endswith(_RSS_SUFFIXES):
        return "rss"
    path_parts = {part for part in path.split("/") if part}
    if path_parts & _RSS_PATH_PARTS:
        return "rss"

    query = {key.casefold(): [str(value).casefold() for value in values] for key, values in parse_qs(parsed.query).items()}
    for key in ("feed", "format", "output", "type"):
        if any(value in {"rss", "rss2", "atom", "xml"} for value in query.get(key, [])):
            return "rss"

    return "url"


def resolve_source_kind(address: str, selected_kind: str = "auto") -> str:
    """Return a persisted source kind, respecting an explicit user override."""

    selected = str(selected_kind or "auto").strip().casefold()
    if selected in SOURCE_KINDS:
        return selected
    return detect_source_kind(address)
