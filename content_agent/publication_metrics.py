from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import quote, urlencode

from .config import AppConfig
from .network import NetworkError, fetch_url


@dataclass(slots=True)
class MetricsResult:
    metrics: dict[str, int] = field(default_factory=dict)
    permalink_url: str = ""
    error: str = ""
    note: str = ""


def _json_request(url: str, token: str, *, headers: dict[str, str] | None = None) -> dict[str, object]:
    request_headers = {"Accept": "application/json"}
    if token:
        request_headers["Authorization"] = f"Bearer {token}"
    if headers:
        request_headers.update(headers)
    response = fetch_url(
        url,
        headers=request_headers,
        timeout=30,
        max_bytes=2 * 1024 * 1024,
        allowed_content_types={"application/json", "application/problem+json"},
        allow_http_errors=True,
    )
    payload = response.json()
    if not isinstance(payload, dict):
        raise NetworkError("Platform metrics response is not a JSON object.")
    if response.status >= 400 or payload.get("error"):
        error = payload.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or error.get("status") or "API rejected the request")
        else:
            message = str(error or payload.get("message") or f"HTTP {response.status}")
        raise NetworkError(message)
    return payload


def _metric_value(item: object) -> int:
    if not isinstance(item, dict):
        return 0
    values = item.get("values")
    if isinstance(values, list) and values:
        last = values[-1]
        if isinstance(last, dict):
            value = last.get("value")
            if isinstance(value, dict):
                return sum(int(number or 0) for number in value.values() if isinstance(number, (int, float)))
            if isinstance(value, (int, float)):
                return int(value)
    total = item.get("total_value")
    if isinstance(total, dict):
        value = total.get("value")
        if isinstance(value, (int, float)):
            return int(value)
    return 0


def _facebook_metrics(config: AppConfig, platform: str, remote_id: str) -> MetricsResult:
    page_id = platform.split(":", 1)[1] if ":" in platform else ""
    page = config.facebook_page(page_id)
    if page is None:
        return MetricsResult(error="Не знайдено Page Access Token для цієї Facebook-сторінки.")
    fields = "permalink_url,created_time,shares,reactions.limit(0).summary(true),comments.limit(0).summary(true)"
    url = f"https://graph.facebook.com/{config.meta_graph_version}/{quote(remote_id, safe='')}?{urlencode({'fields': fields})}"
    try:
        payload = _json_request(url, page["access_token"])
    except NetworkError as exc:
        return MetricsResult(error=f"Facebook: {exc}")
    metrics: dict[str, int] = {}
    reactions = payload.get("reactions")
    if isinstance(reactions, dict) and isinstance(reactions.get("summary"), dict):
        metrics["likes"] = int(reactions["summary"].get("total_count") or 0)
    comments = payload.get("comments")
    if isinstance(comments, dict) and isinstance(comments.get("summary"), dict):
        metrics["comments"] = int(comments["summary"].get("total_count") or 0)
    shares = payload.get("shares")
    if isinstance(shares, dict):
        metrics["shares"] = int(shares.get("count") or 0)
    return MetricsResult(
        metrics=metrics,
        permalink_url=str(payload.get("permalink_url") or ""),
        note="Facebook не повертає перегляди допису з базовими правами сторінки." if "views" not in metrics else "",
    )


def _threads_metrics(config: AppConfig, remote_id: str, progress: dict[str, object]) -> MetricsResult:
    raw_ids = progress.get("remote_ids")
    ids = [str(value) for value in raw_ids if value] if isinstance(raw_ids, list) else []
    if remote_id and remote_id not in ids:
        ids.insert(0, remote_id)
    if not ids:
        return MetricsResult(error="Threads: у збереженій історії немає ID допису.")
    totals = {key: 0 for key in ("views", "likes", "comments", "reposts", "quotes", "shares")}
    errors: list[str] = []
    permalink = ""
    for item_id in ids:
        insights_url = (
            f"https://graph.threads.net/v1.0/{quote(item_id, safe='')}/insights?"
            + urlencode({"metric": "views,likes,replies,reposts,quotes,shares"})
        )
        try:
            payload = _json_request(insights_url, config.threads_token)
            data = payload.get("data")
            if isinstance(data, list):
                for metric in data:
                    if not isinstance(metric, dict):
                        continue
                    name = str(metric.get("name") or "")
                    target = "comments" if name == "replies" else name
                    if target in totals:
                        totals[target] += _metric_value(metric)
        except NetworkError as exc:
            errors.append(str(exc))
        if not permalink:
            try:
                media = _json_request(
                    f"https://graph.threads.net/v1.0/{quote(item_id, safe='')}?fields=id,permalink",
                    config.threads_token,
                )
                permalink = str(media.get("permalink") or "")
            except NetworkError:
                pass
    if errors and not any(totals.values()):
        return MetricsResult(
            error="Threads: " + errors[0],
            note="Для статистики потрібен дозвіл threads_manage_insights.",
            permalink_url=permalink,
        )
    return MetricsResult(
        metrics={key: value for key, value in totals.items() if value or key in {"views", "likes", "comments"}},
        permalink_url=permalink,
        error=("Threads, частина ланцюжка: " + errors[0]) if errors else "",
    )


def _linkedin_metrics(config: AppConfig, remote_id: str) -> MetricsResult:
    if not remote_id:
        return MetricsResult(error="LinkedIn: у збереженій історії немає URN допису.")
    url = f"https://api.linkedin.com/rest/socialActions/{quote(remote_id, safe='')}"
    headers = {
        "LinkedIn-Version": config.linkedin_version,
        "X-Restli-Protocol-Version": "2.0.0",
    }
    try:
        payload = _json_request(url, config.linkedin_token, headers=headers)
    except NetworkError as exc:
        return MetricsResult(
            error=f"LinkedIn: {exc}",
            note="Читання реакцій і коментарів особистих дописів може вимагати окремого схваленого доступу LinkedIn.",
        )
    metrics: dict[str, int] = {}
    likes = payload.get("likesSummary")
    if isinstance(likes, dict):
        metrics["likes"] = int(likes.get("totalLikes") or likes.get("aggregatedTotalLikes") or 0)
    comments = payload.get("commentsSummary")
    if isinstance(comments, dict):
        metrics["comments"] = int(comments.get("totalFirstLevelComments") or comments.get("aggregatedTotalComments") or 0)
    return MetricsResult(metrics=metrics)


def _telegram_metrics(config: AppConfig, remote_id: str, progress: dict[str, object]) -> MetricsResult:
    raw_ids = progress.get("remote_ids")
    ids = [str(value) for value in raw_ids if value] if isinstance(raw_ids, list) else []
    message_id = ids[-1] if ids else str(remote_id or "")
    chat = str(config.telegram_chat_id or "").strip()
    permalink = ""
    if chat.startswith("@") and message_id:
        permalink = f"https://t.me/{chat[1:]}/{message_id}"
    return MetricsResult(
        permalink_url=permalink,
        note="Telegram Bot API не надає перегляди, реакції, пересилання й коментарі канального допису.",
    )


def collect_publication_metrics(
    config: AppConfig,
    platform: str,
    remote_id: str | None,
    progress: dict[str, object] | None = None,
) -> MetricsResult:
    progress = progress if isinstance(progress, dict) else {}
    value = str(remote_id or "").strip()
    if platform.startswith("facebook:"):
        return _facebook_metrics(config, platform, value)
    if platform == "threads":
        return _threads_metrics(config, value, progress)
    if platform == "linkedin":
        return _linkedin_metrics(config, value)
    if platform == "telegram":
        return _telegram_metrics(config, value, progress)
    return MetricsResult(error=f"Статистика для платформи «{platform}» не підтримується.")

@dataclass(slots=True)
class BulkMetricsSummary:
    targets_total: int = 0
    targets_processed: int = 0
    metrics_received: int = 0
    errors: int = 0
    skipped: int = 0
    blocked_platforms: dict[str, str] = field(default_factory=dict)


def _platform_failure_key(platform: str) -> str:
    value = str(platform or "").strip().lower()
    return value


def _global_failure(error: str) -> bool:
    text = str(error or "").casefold()
    markers = (
        "name or service not known",
        "temporary failure in name resolution",
        "could not resolve",
        "timed out",
        "timeout",
        "access token",
        "oauth",
        "permission",
        "unauthorized",
        "forbidden",
    )
    return any(marker in text for marker in markers)


def collect_all_publication_metrics(
    database: Any,
    config: AppConfig,
    history_rows: list[dict[str, object]],
    *,
    progress_callback: Callable[[int, int, BulkMetricsSummary], None] | None = None,
    delay_seconds: float = 0.15,
    collector: Callable[[AppConfig, str, str | None, dict[str, object] | None], MetricsResult] = collect_publication_metrics,
) -> BulkMetricsSummary:
    """Refresh every sent publication target with platform-level circuit breaking.

    Two repeated global failures for the same configured target stop further calls
    to that target during this run. This avoids dozens of identical 30-second DNS,
    token, or permission failures while preserving per-post errors in the history.
    """

    targets: list[dict[str, object]] = []
    seen_ids: set[int] = set()
    for row in history_rows:
        raw_targets = row.get("targets")
        for target in raw_targets if isinstance(raw_targets, list) else []:
            if not isinstance(target, dict) or str(target.get("status")) != "sent":
                continue
            try:
                target_id = int(target.get("id") or 0)
            except (TypeError, ValueError):
                continue
            if target_id <= 0 or target_id in seen_ids:
                continue
            seen_ids.add(target_id)
            targets.append(target)

    summary = BulkMetricsSummary(targets_total=len(targets))
    repeated_failures: dict[str, tuple[str, int]] = {}
    blocked: dict[str, str] = {}

    for index, target in enumerate(targets, start=1):
        platform = str(target.get("platform") or "")
        failure_key = _platform_failure_key(platform)
        if failure_key in blocked:
            message = "Масове оновлення пропущено після повторної помилки платформи: " + blocked[failure_key]
            database.save_publication_metrics(
                int(target["id"]), metrics=None, error=message,
                note="Інші дописи цієї платформи не запитувалися повторно в цьому запуску.",
                permalink_url="",
            )
            summary.targets_processed += 1
            summary.skipped += 1
            if progress_callback is not None:
                progress_callback(index, len(targets), summary)
            continue

        result = collector(
            config,
            platform,
            str(target.get("remote_id") or ""),
            target.get("progress") if isinstance(target.get("progress"), dict) else {},
        )
        database.save_publication_metrics(
            int(target["id"]), metrics=result.metrics if result.metrics else None, error=result.error,
            note=result.note, permalink_url=result.permalink_url,
        )
        summary.targets_processed += 1
        if result.metrics:
            summary.metrics_received += 1
        if result.error:
            summary.errors += 1
            normalized = " ".join(result.error.split())[:240]
            previous, count = repeated_failures.get(failure_key, ("", 0))
            count = count + 1 if previous == normalized else 1
            repeated_failures[failure_key] = (normalized, count)
            if count >= 2 and _global_failure(normalized):
                blocked[failure_key] = normalized
                summary.blocked_platforms[failure_key] = normalized
        else:
            repeated_failures.pop(failure_key, None)

        if progress_callback is not None:
            progress_callback(index, len(targets), summary)
        if delay_seconds > 0 and platform != "telegram" and index < len(targets):
            time.sleep(float(delay_seconds))

    return summary

