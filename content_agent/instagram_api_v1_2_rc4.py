from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import urlencode

from .network import NetworkError, fetch_url


class InstagramError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class InstagramProfile:
    user_id: str
    username: str
    account_type: str


def _graph_request(url: str, *, method: str = "GET", fields: dict[str, object] | None = None) -> dict[str, object]:
    body = None
    headers = {"Accept": "application/json"}
    if fields is not None:
        body = urlencode({key: str(value) for key, value in fields.items()}).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    try:
        response = fetch_url(
            url,
            method=method,
            headers=headers,
            body=body,
            max_bytes=2 * 1024 * 1024,
            allowed_content_types={"application/json", "text/javascript"},
            timeout=60,
            max_redirects=0,
            allow_http_errors=True,
        )
    except NetworkError as exc:
        raise InstagramError(str(exc)) from exc
    payload = response.json() if response.body else {}
    if response.status >= 400 or not isinstance(payload, dict):
        message = f"Instagram API повернув HTTP {response.status}."
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                message = str(error.get("message") or message)
        raise InstagramError(message)
    return payload


def inspect_instagram_profile(user_id: str, token: str, graph_version: str) -> InstagramProfile:
    user_id = str(user_id or "").strip()
    token = str(token or "").strip()
    version = str(graph_version or "v26.0").strip()
    if not user_id or not token:
        raise InstagramError("Вкажіть Instagram User ID і Access Token.")
    payload = _graph_request(
        f"https://graph.facebook.com/{version}/{user_id}?"
        + urlencode({"fields": "id,username,account_type", "access_token": token})
    )
    returned_id = str(payload.get("id") or "").strip()
    if not returned_id:
        raise InstagramError("Instagram не повернув ID професійного акаунта.")
    return InstagramProfile(
        user_id=returned_id,
        username=str(payload.get("username") or returned_id),
        account_type=str(payload.get("account_type") or "professional"),
    )


def create_instagram_container(
    user_id: str,
    token: str,
    graph_version: str,
    *,
    public_url: str,
    kind: str,
    caption: str = "",
    carousel_item: bool = False,
) -> str:
    fields: dict[str, object] = {"access_token": token}
    if kind == "image":
        fields["image_url"] = public_url
    elif kind == "video":
        fields.update({"media_type": "REELS", "video_url": public_url, "share_to_feed": "true"})
    else:
        raise InstagramError("Instagram підтримує в цій програмі лише фото або відео.")
    if caption:
        fields["caption"] = caption
    if carousel_item:
        fields["is_carousel_item"] = "true"
    payload = _graph_request(
        f"https://graph.facebook.com/{graph_version}/{user_id}/media",
        method="POST",
        fields=fields,
    )
    container_id = str(payload.get("id") or "").strip()
    if not container_id:
        raise InstagramError("Instagram не повернув ID медіаконтейнера.")
    return container_id


def wait_instagram_container(container_id: str, token: str, graph_version: str) -> None:
    for _ in range(40):
        payload = _graph_request(
            f"https://graph.facebook.com/{graph_version}/{container_id}?"
            + urlencode({"fields": "status_code,status", "access_token": token})
        )
        status = str(payload.get("status_code") or payload.get("status") or "").upper()
        if status in {"FINISHED", "PUBLISHED"}:
            return
        if status in {"ERROR", "EXPIRED"}:
            raise InstagramError(f"Instagram не обробив медіа: {status}.")
        time.sleep(2)
    raise InstagramError("Instagram не завершив обробку медіа вчасно.")


def create_instagram_carousel(
    user_id: str,
    token: str,
    graph_version: str,
    child_ids: list[str],
    caption: str,
) -> str:
    if not (2 <= len(child_ids) <= 10):
        raise InstagramError("Instagram-карусель повинна містити від 2 до 10 фото.")
    payload = _graph_request(
        f"https://graph.facebook.com/{graph_version}/{user_id}/media",
        method="POST",
        fields={
            "media_type": "CAROUSEL",
            "children": ",".join(child_ids),
            "caption": caption,
            "access_token": token,
        },
    )
    container_id = str(payload.get("id") or "").strip()
    if not container_id:
        raise InstagramError("Instagram не повернув ID контейнера каруселі.")
    return container_id


def publish_instagram_container(user_id: str, token: str, graph_version: str, container_id: str) -> str:
    payload = _graph_request(
        f"https://graph.facebook.com/{graph_version}/{user_id}/media_publish",
        method="POST",
        fields={"creation_id": container_id, "access_token": token},
    )
    media_id = str(payload.get("id") or "").strip()
    if not media_id:
        raise InstagramError("Instagram не повернув ID опублікованого матеріалу.")
    return media_id
