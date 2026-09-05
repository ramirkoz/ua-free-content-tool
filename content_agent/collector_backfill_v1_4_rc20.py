from __future__ import annotations

import json
import logging
from datetime import datetime, time, timedelta, tzinfo
from pathlib import Path
import xml.etree.ElementTree as ET

from .collectors import (
    CollectorError,
    _TelegramPreviewParser,
    _fetch_article_text,
    _first_text,
    _strip_html,
    collect_source,
    normalize_telegram_preview_url,
)
from .models import CollectedArticle, Source
from .network import NetworkError, fetch_url
from .news_logic import parse_published_at
from .paths import data_dir

logger = logging.getLogger("content_agent.collector_backfill_rc20")

RECOVERY_STALE_AFTER = timedelta(minutes=12)
RECOVERY_OVERLAP = timedelta(minutes=10)
TELEGRAM_BACKFILL_MAX_PAGES = 48
RC20_MARKER_FILENAME = "rc20_current_day_backfill.json"


def working_day_start(*, now: datetime, zone: tzinfo) -> datetime:
    local = now.astimezone(zone)
    return datetime.combine(local.date(), time.min, tzinfo=zone)


def recovery_not_before(
    last_checked_at: str | None,
    *,
    now: datetime,
    zone: tzinfo,
    force_full_day: bool = False,
    manual: bool = False,
) -> datetime | None:
    """Return the lower bound for a recovery read, or None for a lightweight poll.

    The first RC20 run and a manual source refresh deliberately recover from the
    start of the working day. Later automatic polls remain cheap unless the
    source has not been checked successfully for long enough to create a gap.
    """

    local_now = now.astimezone(zone)
    day_start = working_day_start(now=local_now, zone=zone)
    if force_full_day or manual:
        return day_start

    checked = parse_published_at(last_checked_at)
    if checked is None:
        return day_start
    checked_local = checked.astimezone(zone)
    if checked_local.date() != local_now.date():
        return day_start
    if local_now - checked_local <= RECOVERY_STALE_AFTER:
        return None
    return max(day_start, checked_local - RECOVERY_OVERLAP)


def rc20_marker_path() -> Path:
    return data_dir() / RC20_MARKER_FILENAME


def rc20_upgrade_backfill_done(path: Path | None = None) -> bool:
    target = path or rc20_marker_path()
    if not target.exists():
        return False
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(payload.get("completed"))


def mark_rc20_upgrade_backfill_done(path: Path | None = None) -> None:
    target = path or rc20_marker_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            {
                "completed": True,
                "version": "1.4.0-rc20",
                "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)


def _parse_telegram_page_all(html: str) -> list[CollectedArticle]:
    parser = _TelegramPreviewParser()
    parser.feed(html)
    return parser.items


def _telegram_message_id(external_id: str) -> int | None:
    try:
        value = str(external_id).rsplit("/", 1)[-1]
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _on_or_after(item: CollectedArticle, not_before: datetime, zone: tzinfo) -> bool:
    parsed = parse_published_at(item.published_at)
    if parsed is None:
        return False
    return parsed.astimezone(zone) >= not_before.astimezone(zone)


def _telegram_backfill(source: Source, *, not_before: datetime, zone: tzinfo) -> list[CollectedArticle]:
    base_url = normalize_telegram_preview_url(source.url)
    cursor: int | None = None
    seen_cursors: set[int] = set()
    collected: dict[str, CollectedArticle] = {}
    reached_boundary = False

    for page_index in range(TELEGRAM_BACKFILL_MAX_PAGES):
        page_url = base_url if cursor is None else f"{base_url}?before={cursor}"
        response = fetch_url(
            page_url,
            max_bytes=5 * 1024 * 1024,
            allowed_content_types={"text/html"},
            timeout=30,
        )
        items = _parse_telegram_page_all(response.body.decode("utf-8", errors="replace"))
        if not items:
            break

        dated: list[tuple[CollectedArticle, datetime]] = []
        ids: list[int] = []
        for item in items:
            message_id = _telegram_message_id(item.external_id)
            if message_id is not None:
                ids.append(message_id)
            parsed = parse_published_at(item.published_at)
            if parsed is None:
                continue
            local = parsed.astimezone(zone)
            dated.append((item, local))
            if local >= not_before.astimezone(zone):
                collected[item.external_id] = item

        if dated and min(local for _item, local in dated) < not_before.astimezone(zone):
            reached_boundary = True
            break
        if not ids:
            break
        next_cursor = min(ids)
        if next_cursor in seen_cursors or (cursor is not None and next_cursor >= cursor):
            break
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    else:
        logger.warning(
            "RC20 Telegram recovery page cap reached source=%s cap=%s boundary=%s",
            source.name,
            TELEGRAM_BACKFILL_MAX_PAGES,
            not_before.isoformat(),
        )

    if not reached_boundary and collected:
        logger.info(
            "RC20 Telegram recovery ended before an older-than-boundary post was observed source=%s items=%s boundary=%s",
            source.name,
            len(collected),
            not_before.isoformat(),
        )

    def sort_key(item: CollectedArticle) -> datetime:
        parsed = parse_published_at(item.published_at)
        return (parsed.astimezone(zone) if parsed is not None else not_before)

    return sorted(collected.values(), key=sort_key)


def _parse_rss_all(xml_bytes: bytes) -> list[CollectedArticle]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise CollectorError("RSS/Atom XML is invalid.") from exc
    items: list[CollectedArticle] = []
    candidates = [
        node
        for node in root.iter()
        if node.tag.rsplit("}", 1)[-1].lower() in {"item", "entry"}
    ]
    for node in candidates:
        title = _first_text(node, ["title"])
        link = _first_text(node, ["link"])
        if not link:
            for child in node:
                if child.tag.rsplit("}", 1)[-1].lower() == "link" and child.attrib.get("href"):
                    link = child.attrib["href"]
                    break
        guid = _first_text(node, ["guid", "id"]) or link or title
        description = _first_text(node, ["encoded", "content", "description", "summary"])
        published = _first_text(node, ["pubdate", "published", "updated"]) or None
        text_value = _strip_html(description)
        if not guid or not (title or text_value):
            continue
        items.append(
            CollectedArticle(
                external_id=guid[:1000],
                title=title or text_value[:120] or "Без заголовка",
                url=link,
                raw_text=text_value,
                published_at=published,
            )
        )
    return items


def _rss_backfill(source: Source, *, not_before: datetime, zone: tzinfo) -> list[CollectedArticle]:
    response = fetch_url(
        source.url,
        max_bytes=5 * 1024 * 1024,
        allowed_content_types={
            "application/rss+xml",
            "application/atom+xml",
            "application/xml",
            "text/xml",
            "text/plain",
        },
        timeout=30,
    )
    available = _parse_rss_all(response.body)
    selected = [item for item in available if _on_or_after(item, not_before, zone)]
    # Full-page extraction is the expensive part. Enrich the newest entries and
    # keep feed text for the rest; the important RC20 job is not to lose events.
    for item in selected[-20:]:
        item.raw_text = _fetch_article_text(item.url, item.raw_text)
    return selected


def collect_source_rc20(
    source: Source,
    *,
    zone: tzinfo,
    not_before: datetime | None = None,
) -> list[CollectedArticle]:
    """Collect one source, using bounded recovery only when a gap must be filled."""

    if not_before is None:
        return collect_source(source)
    try:
        if source.kind == "telegram":
            return _telegram_backfill(source, not_before=not_before, zone=zone)
        if source.kind == "rss":
            return _rss_backfill(source, not_before=not_before, zone=zone)
        return collect_source(source)
    except NetworkError as exc:
        raise CollectorError(str(exc)) from exc
