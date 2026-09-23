from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlencode

from .network import NetworkError, fetch_url


class TrendError(RuntimeError):
    pass


@dataclass(frozen=True)
class ThreadsTrendSample:
    """A transparent summary of Threads keyword-search results."""

    count: int | None
    per_query: dict[str, int]
    error: str = ""

    @property
    def available(self) -> bool:
        return self.count is not None


def _error_detail(response: object) -> str:
    status = int(getattr(response, "status", 0) or 0)
    detail = f"HTTP {status}." if status else "Threads API error."
    try:
        payload = response.json()  # type: ignore[attr-defined]
    except Exception:
        return detail
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or "").strip()
            if message:
                return message
    return detail


def check_threads_keyword_access(token: str, query: str = "Україна") -> tuple[bool, str]:
    """Check whether a Threads token can call keyword_search without exposing it."""
    token = token.strip()
    if not token:
        return False, "Токен порожній."
    url = "https://graph.threads.net/keyword_search?" + urlencode(
        {
            "q": query[:100],
            "search_type": "RECENT",
            "search_mode": "KEYWORD",
            "fields": "id",
            "limit": "1",
        }
    )
    try:
        response = fetch_url(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            max_bytes=512 * 1024,
            allowed_content_types={"application/json", "text/javascript"},
            timeout=12,
            max_redirects=0,
            allow_http_errors=True,
        )
    except NetworkError as exc:
        return False, str(exc)
    if response.status >= 400:
        return False, _error_detail(response)
    try:
        payload = response.json()
    except Exception:
        return False, "Threads повернув неочікувану відповідь."
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return False, "Threads не повернув список результатів."
    return True, "Дозвіл threads_keyword_search працює."


def threads_keyword_sample(
    token: str,
    queries: list[str] | tuple[str, ...],
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> ThreadsTrendSample:
    """Search several human-readable queries and return deduplicated post counts.

    A single long headline-like query often returns zero even when the subject is
    active. The caller therefore supplies a compact specific query plus fallback
    entity/action queries. Results are shown per query so zero is distinguishable
    from an unavailable permission or API error.
    """
    token = token.strip()
    unique_queries: list[str] = []
    for raw in queries:
        query = " ".join(str(raw).split()).strip()
        if query and query.casefold() not in {item.casefold() for item in unique_queries}:
            unique_queries.append(query[:100])
        if len(unique_queries) >= 4:
            break
    if not token or not unique_queries:
        return ThreadsTrendSample(None, {}, "Немає токена або пошукових запитів.")

    all_ids: set[str] = set()
    per_query: dict[str, int] = {}
    successful_requests = 0
    errors: list[str] = []

    for query in unique_queries:
        query_ids: set[str] = set()
        query_succeeded = False
        for search_type in ("RECENT", "TOP"):
            params: dict[str, str] = {
                "q": query,
                "search_type": search_type,
                "search_mode": "KEYWORD",
                "fields": "id,text,timestamp,permalink",
                "limit": "50",
            }
            if since is not None:
                params["since"] = since.isoformat(timespec="seconds")
            if until is not None:
                params["until"] = until.isoformat(timespec="seconds")
            url = "https://graph.threads.net/keyword_search?" + urlencode(params)
            try:
                response = fetch_url(
                    url,
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                    max_bytes=4 * 1024 * 1024,
                    allowed_content_types={"application/json", "text/javascript"},
                    timeout=15,
                    max_redirects=0,
                    allow_http_errors=True,
                )
            except NetworkError as exc:
                errors.append(f"{query}: {exc}")
                continue
            if response.status >= 400:
                errors.append(f"{query}: {_error_detail(response)}")
                continue
            try:
                payload = response.json()
            except Exception:
                errors.append(f"{query}: неочікувана відповідь Threads")
                continue
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, list):
                errors.append(f"{query}: Threads не повернув список")
                continue
            successful_requests += 1
            query_succeeded = True
            for item in data:
                if not isinstance(item, dict):
                    continue
                identifier = str(item.get("id") or "").strip()
                if identifier:
                    query_ids.add(identifier)
                    all_ids.add(identifier)
        if query_succeeded:
            per_query[query] = len(query_ids)

    if successful_requests == 0:
        detail = errors[0] if errors else "Threads keyword search недоступний."
        return ThreadsTrendSample(None, {}, detail)
    return ThreadsTrendSample(len(all_ids), per_query, "; ".join(errors[:2]))


def threads_keyword_count(token: str, query: str) -> int | None:
    """Backward-compatible single-query count."""
    return threads_keyword_sample(token, [query]).count
