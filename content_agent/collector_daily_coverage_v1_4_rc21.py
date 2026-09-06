from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, time, tzinfo
from pathlib import Path

from .collector_backfill_v1_4_rc20 import (
    _parse_rss_all,
    _parse_telegram_page_all,
    _telegram_message_id,
    recovery_not_before,
)
from .collectors import CollectorError, _fetch_article_text, collect_source, normalize_telegram_preview_url
from .models import CollectedArticle, Source
from .network import NetworkError, fetch_url
from .news_logic import parse_published_at
from .paths import data_dir

logger = logging.getLogger("content_agent.collector_daily_coverage_rc21")

TELEGRAM_FULL_DAY_MAX_PAGES = 256
COVERAGE_FILENAME = "rc21_daily_source_coverage.json"


@dataclass(frozen=True)
class CoverageResult:
    items: list[CollectedArticle]
    complete: bool
    oldest_seen: str | None = None
    newest_seen: str | None = None
    detail: str = ""


def working_day_start(*, now: datetime, zone: tzinfo) -> datetime:
    local = now.astimezone(zone)
    return datetime.combine(local.date(), time.min, tzinfo=zone)


def coverage_path() -> Path:
    return data_dir() / COVERAGE_FILENAME


def empty_coverage_state(working_date: str) -> dict[str, object]:
    return {
        "version": "1.4.0-rc21",
        "working_date": working_date,
        "sources": {},
    }


def load_coverage_state(*, working_date: str, path: Path | None = None) -> dict[str, object]:
    target = path or coverage_path()
    if not target.exists():
        return empty_coverage_state(working_date)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return empty_coverage_state(working_date)
    if str(payload.get("working_date") or "") != working_date:
        return empty_coverage_state(working_date)
    sources = payload.get("sources")
    if not isinstance(sources, dict):
        payload["sources"] = {}
    payload["version"] = "1.4.0-rc21"
    return payload


def save_coverage_state(payload: dict[str, object], path: Path | None = None) -> None:
    target = path or coverage_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)


def source_coverage_complete(payload: dict[str, object], source_id: int) -> bool:
    sources = payload.get("sources")
    if not isinstance(sources, dict):
        return False
    row = sources.get(str(int(source_id)))
    return isinstance(row, dict) and bool(row.get("complete"))


def update_source_coverage(
    payload: dict[str, object],
    *,
    source: Source,
    result: CoverageResult,
    checked_at: datetime,
) -> None:
    if source.id is None:
        return
    sources = payload.setdefault("sources", {})
    if not isinstance(sources, dict):
        sources = {}
        payload["sources"] = sources
    sources[str(int(source.id))] = {
        "name": source.name,
        "kind": source.kind,
        "complete": bool(result.complete),
        "oldest_seen": result.oldest_seen,
        "newest_seen": result.newest_seen,
        "detail": result.detail,
        "checked_at": checked_at.isoformat(timespec="seconds"),
    }


def coverage_summary(payload: dict[str, object], source_ids: set[int]) -> tuple[int, int]:
    total = len(source_ids)
    complete = sum(1 for source_id in source_ids if source_coverage_complete(payload, source_id))
    return complete, total


def _range_seen(items: list[CollectedArticle], zone: tzinfo) -> tuple[str | None, str | None]:
    parsed = [parse_published_at(item.published_at) for item in items]
    dated = [value.astimezone(zone) for value in parsed if value is not None]
    if not dated:
        return None, None
    return min(dated).isoformat(timespec="seconds"), max(dated).isoformat(timespec="seconds")


def _telegram_full_day(source: Source, *, not_before: datetime, zone: tzinfo) -> CoverageResult:
    base_url = normalize_telegram_preview_url(source.url)
    cursor: int | None = None
    seen_cursors: set[int] = set()
    collected: dict[str, CollectedArticle] = {}
    observed_dates: list[datetime] = []
    reached_boundary = False
    stop_detail = ""

    for _page_index in range(TELEGRAM_FULL_DAY_MAX_PAGES):
        page_url = base_url if cursor is None else f"{base_url}?before={cursor}"
        response = fetch_url(
            page_url,
            max_bytes=5 * 1024 * 1024,
            allowed_content_types={"text/html"},
            timeout=30,
        )
        items = _parse_telegram_page_all(response.body.decode("utf-8", errors="replace"))
        if not items:
            stop_detail = "telegram preview returned no parseable messages before midnight boundary"
            break

        ids: list[int] = []
        page_dates: list[datetime] = []
        for item in items:
            message_id = _telegram_message_id(item.external_id)
            if message_id is not None:
                ids.append(message_id)
            parsed = parse_published_at(item.published_at)
            if parsed is None:
                continue
            local = parsed.astimezone(zone)
            page_dates.append(local)
            observed_dates.append(local)
            if local >= not_before.astimezone(zone):
                collected[item.external_id] = item

        if page_dates and min(page_dates) < not_before.astimezone(zone):
            reached_boundary = True
            stop_detail = "midnight boundary confirmed"
            break
        if not ids:
            stop_detail = "telegram preview did not expose message ids for pagination"
            break
        next_cursor = min(ids)
        if next_cursor in seen_cursors or (cursor is not None and next_cursor >= cursor):
            stop_detail = "telegram pagination cursor stopped progressing before midnight boundary"
            break
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    else:
        stop_detail = f"telegram safety page cap {TELEGRAM_FULL_DAY_MAX_PAGES} reached before midnight boundary"
        logger.warning(
            "RC21 Telegram daily coverage page cap source=%s boundary=%s cap=%s",
            source.name,
            not_before.isoformat(),
            TELEGRAM_FULL_DAY_MAX_PAGES,
        )

    ordered = sorted(
        collected.values(),
        key=lambda item: parse_published_at(item.published_at) or not_before,
    )
    if observed_dates:
        oldest = min(observed_dates).isoformat(timespec="seconds")
        newest = max(observed_dates).isoformat(timespec="seconds")
    else:
        oldest = newest = None
    return CoverageResult(
        items=ordered,
        complete=reached_boundary,
        oldest_seen=oldest,
        newest_seen=newest,
        detail=stop_detail or "midnight boundary not confirmed",
    )


def _rss_full_day(source: Source, *, not_before: datetime, zone: tzinfo) -> CoverageResult:
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
    selected: list[CollectedArticle] = []
    for item in available:
        parsed = parse_published_at(item.published_at)
        if parsed is not None and parsed.astimezone(zone) >= not_before.astimezone(zone):
            selected.append(item)
    for item in selected[-20:]:
        item.raw_text = _fetch_article_text(item.url, item.raw_text)
    oldest, newest = _range_seen(available, zone)
    return CoverageResult(
        items=selected,
        complete=True,
        oldest_seen=oldest,
        newest_seen=newest,
        detail=f"entire currently exposed RSS/Atom feed exhausted ({len(available)} entries)",
    )


def collect_source_rc21(
    source: Source,
    *,
    zone: tzinfo,
    not_before: datetime | None = None,
    require_full_day: bool = False,
) -> CoverageResult:
    """Collect a source and report whether the requested daily coverage is proven."""
    try:
        if require_full_day:
            if not_before is None:
                raise ValueError("Full-day collection requires a lower boundary.")
            if source.kind == "telegram":
                return _telegram_full_day(source, not_before=not_before, zone=zone)
            if source.kind == "rss":
                return _rss_full_day(source, not_before=not_before, zone=zone)

        if not_before is None:
            items = collect_source(source)
            oldest, newest = _range_seen(items, zone)
            return CoverageResult(items=items, complete=True, oldest_seen=oldest, newest_seen=newest, detail="lightweight poll")

        # Gap recovery after a previously confirmed day may reuse RC21's full
        # collectors against the smaller lower boundary. It does not change the
        # already-confirmed midnight coverage state.
        if source.kind == "telegram":
            return _telegram_full_day(source, not_before=not_before, zone=zone)
        if source.kind == "rss":
            return _rss_full_day(source, not_before=not_before, zone=zone)
        items = collect_source(source)
        oldest, newest = _range_seen(items, zone)
        return CoverageResult(items=items, complete=True, oldest_seen=oldest, newest_seen=newest, detail="plain URL poll")
    except NetworkError as exc:
        raise CollectorError(str(exc)) from exc


__all__ = [
    "CoverageResult",
    "collect_source_rc21",
    "coverage_summary",
    "empty_coverage_state",
    "load_coverage_state",
    "recovery_not_before",
    "save_coverage_state",
    "source_coverage_complete",
    "update_source_coverage",
    "working_day_start",
]
