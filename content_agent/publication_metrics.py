from __future__ import annotations

from dataclasses import dataclass, field
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
