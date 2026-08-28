from __future__ import annotations

import json
from urllib.parse import urlencode, urlsplit

from .destinations_v1_4 import InstagramDestination
from .network import NetworkError, fetch_url
from .platform_setup import PlatformSetupError


def _payload(body: bytes, status: int) -> dict[str, object]:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PlatformSetupError("Meta повернула пошкоджену відповідь Instagram.", http_status=status) from exc
    if not isinstance(value, dict):
        raise PlatformSetupError("Meta повернула неочікуваний формат Instagram.", http_status=status)
    error = value.get("error")
    if error:
        if isinstance(error, dict):
            raise PlatformSetupError(
                str(error.get("message") or error),
                code=int(error.get("code") or 0),
                subcode=int(error.get("error_subcode") or 0),
                http_status=status,
            )
        raise PlatformSetupError(str(error), http_status=status)
    if status >= 400:
        raise PlatformSetupError(f"Meta повернула HTTP {status}.", http_status=status)
    return value


def _get(url: str, token: str) -> dict[str, object]:
    try:
        response = fetch_url(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=20,
            max_bytes=3 * 1024 * 1024,
            allowed_content_types={"application/json", "text/javascript"},
            max_redirects=0,
            allow_http_errors=True,
        )
    except NetworkError as exc:
        raise PlatformSetupError(str(exc)) from exc
    return _payload(response.body, response.status)


def discover_instagram_accounts(user_token: str, graph_version: str) -> list[InstagramDestination]:
    """Discover every Instagram professional account reachable through Facebook Pages.

    Tokens are intentionally not returned or persisted. Each Instagram destination
    stores only its page_id; publication later resolves the already encrypted Page
    access token from AppConfig.facebook_pages.
    """

    token = str(user_token or "").strip()
    version = str(graph_version or "v26.0").strip() or "v26.0"
    if not token:
        raise PlatformSetupError(
            "Спочатку підключіть Facebook Pages: потрібен чинний Facebook User Access Token."
        )

    # Meta Graph API v26.0 does not expose account_type on this edge. Asking for
    # it aborts the whole /me/accounts request with (#100), so keep discovery to
    # fields that are valid for Instagram Business Account expansion.
    fields = "id,name,access_token,instagram_business_account{id,username}"
    url = f"https://graph.facebook.com/{version}/me/accounts?" + urlencode(
        {"fields": fields, "limit": "100"}
    )
    result: list[InstagramDestination] = []
    seen_accounts: set[str] = set()
    seen_urls: set[str] = set()

    for _page_number in range(100):
        if url in seen_urls:
            raise PlatformSetupError("Meta повернула циклічну пагінацію Instagram-акаунтів.")
        seen_urls.add(url)
        payload = _get(url, token)
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise PlatformSetupError("Meta не повернула список Facebook Pages для Instagram.")

        for raw in rows:
            if not isinstance(raw, dict):
                continue
            page_id = str(raw.get("id") or "").strip()
            page_name = str(raw.get("name") or page_id).strip()
            instagram = raw.get("instagram_business_account")
            if not isinstance(instagram, dict):
                continue
            account_id = str(instagram.get("id") or "").strip()
            if not account_id or account_id in seen_accounts:
                continue
            seen_accounts.add(account_id)
            result.append(
                InstagramDestination(
                    id=account_id,
                    username=str(instagram.get("username") or "").strip(),
                    account_type="Professional",
                    page_id=page_id,
                    page_name=page_name,
                    auth_mode="facebook_login",
                )
            )

        paging = payload.get("paging")
        next_url = str(paging.get("next") or "") if isinstance(paging, dict) else ""
        if not next_url:
            break
        parts = urlsplit(next_url)
        if parts.scheme != "https" or parts.hostname not in {"graph.facebook.com", "www.graph.facebook.com"}:
            raise PlatformSetupError("Meta повернула небезпечне посилання пагінації.")
        url = next_url

    return result
