from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import quote, urlencode

from .config import AppConfig
from .models import MediaPayload
from .network import NetworkError, fetch_url
from .editorial_memory import split_threads_chain
from .publication_text import telegram_split


class PublishError(RuntimeError):
    """Publication failure with retry metadata safe for queue scheduling.

    ``retryable=False`` means the request will not become valid by repeating the
    exact same credentials and payload. Typical examples are an invalid OAuth
    token, missing Page role, a missing Telegram administrator right or a
    policy block. Rate limits and transport failures remain retryable, but the
    worker applies paced exponential backoff instead of hammering the API.
    """

    def __init__(
        self,
        message: str,
        *,
        code: int | None = None,
        subcode: int | None = None,
        retryable: bool = True,
        auth_error: bool = False,
        rate_limited: bool = False,
        outcome_unknown: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.subcode = subcode
        self.retryable = retryable
        self.auth_error = auth_error
        self.rate_limited = rate_limited
        self.outcome_unknown = outcome_unknown


@dataclass(slots=True)
class PublishContext:
    before_write: Callable[[], None]
    save_progress: Callable[[dict[str, object]], None]


@dataclass(slots=True)
class PublishResult:
    remote_id: str | None
    progress: dict[str, object]


class Publisher:
    def publish(
        self,
        text: str,
        progress: dict[str, object],
        context: PublishContext,
        media: MediaPayload | None = None,
    ) -> PublishResult:
        raise NotImplementedError


def _as_int(value: object) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _check_payload(payload: object, *, http_status: int | None = None) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise PublishError(
            "Platform response must be a JSON object.",
            retryable=http_status is None or http_status >= 500,
        )
    if payload.get("ok") is False:
        description = str(payload.get("description") or "Telegram rejected the publication.")
        code = _as_int(payload.get("error_code"))
        suffix = f" (код {code})" if code is not None else ""
        retry_after = None
        parameters = payload.get("parameters")
        if isinstance(parameters, dict):
            retry_after = _as_int(parameters.get("retry_after"))
        rate_limited = code == 429
        auth_error = code in {401, 403}
        retryable = rate_limited or (code is not None and code >= 500)
        detail = f"; повторити через {retry_after} с" if retry_after else ""
        raise PublishError(
            f"Telegram: {description}{suffix}{detail}",
            code=code,
            retryable=retryable,
            auth_error=auth_error,
            rate_limited=rate_limited,
        )
    if payload.get("error"):
        error = payload["error"]
        if isinstance(error, dict):
            message = str(error.get("message") or "Platform rejected the publication.")
            code = _as_int(error.get("code"))
            subcode = _as_int(error.get("error_subcode"))
            code_suffix = ""
            if code is not None:
                code_suffix = f" (код {code}" + (f", підкод {subcode}" if subcode is not None else "") + ")"
            auth_error = code in {190, 200, 10}
            rate_limited = code in {4, 17, 32, 613} or http_status == 429
            retryable = rate_limited or code in {1, 2} or (http_status is not None and http_status >= 500)
            if code in {190, 200, 10, 100, 368}:
                retryable = False
            raise PublishError(
                message + code_suffix,
                code=code,
                subcode=subcode,
                retryable=retryable,
                auth_error=auth_error,
                rate_limited=rate_limited,
            )
        raise PublishError(str(error), retryable=http_status is None or http_status >= 500)
    if payload.get("error_description"):
        raise PublishError(
            str(payload["error_description"]),
            retryable=http_status is None or http_status >= 500,
        )
    return payload


def _post_form(url: str, fields: dict[str, object], *, timeout: float = 45) -> dict[str, object]:
    body = urlencode({key: str(value) for key, value in fields.items()}).encode("utf-8")
    response = fetch_url(
        url,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        body=body,
        max_bytes=2 * 1024 * 1024,
        allowed_content_types={"application/json", "text/javascript"},
        timeout=timeout,
        max_redirects=0,
        allow_http_errors=True,
    )
    payload = response.json() if response.body else {}
    if response.status >= 400:
        _check_payload(payload, http_status=response.status)
        raise PublishError(
            f"Platform request failed with HTTP {response.status}.",
            retryable=response.status == 429 or response.status >= 500,
            rate_limited=response.status == 429,
        )
    return _check_payload(payload)


def _post_json(
    url: str,
    payload: dict[str, object],
    headers: dict[str, str],
    *,
    timeout: float = 60,
) -> tuple[dict[str, object], dict[str, str]]:
    response = fetch_url(
        url,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json", **headers},
        body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        max_bytes=3 * 1024 * 1024,
        allowed_content_types={"application/json"},
        timeout=timeout,
        max_redirects=0,
        allow_http_errors=True,
    )
    decoded = response.json() if response.body else {}
    if response.status >= 400:
        _check_payload(decoded, http_status=response.status)
        raise PublishError(
            f"Platform request failed with HTTP {response.status}.",
            retryable=response.status == 429 or response.status >= 500,
            rate_limited=response.status == 429,
        )
    return _check_payload(decoded), response.headers


def _multipart_body(fields: dict[str, object], file_field: str, media: MediaPayload) -> tuple[bytes, str]:
    boundary = "----UAFree" + secrets.token_hex(16)
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )
    safe_name = media.name.replace('"', "_").replace("\r", "_").replace("\n", "_")
    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{file_field}"; filename="{safe_name}"\r\n'.encode("utf-8"),
            f"Content-Type: {media.mime_type}\r\n\r\n".encode(),
            media.data,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _post_multipart(
    url: str,
    fields: dict[str, object],
    file_field: str,
    media: MediaPayload,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 180,
) -> dict[str, object]:
    body, content_type = _multipart_body(fields, file_field, media)
    response = fetch_url(
        url,
        method="POST",
        headers={"Content-Type": content_type, "Accept": "application/json", **(headers or {})},
        body=body,
        max_bytes=3 * 1024 * 1024,
        allowed_content_types={"application/json", "text/javascript"},
        timeout=timeout,
        max_redirects=1,
        allow_http_errors=True,
    )
    payload = response.json() if response.body else {}
    if response.status >= 400:
        _check_payload(payload, http_status=response.status)
        raise PublishError(
            f"Media upload failed with HTTP {response.status}.",
            retryable=response.status == 429 or response.status >= 500,
            rate_limited=response.status == 429,
        )
    return _check_payload(payload)


def _upload_binary(url: str, media: MediaPayload, headers: dict[str, str], *, method: str = "PUT") -> None:
    response = fetch_url(
        url,
        method=method,
        headers={"Content-Type": media.mime_type, "Content-Length": str(len(media.data)), **headers},
        body=media.data,
        max_bytes=2 * 1024 * 1024,
        timeout=240,
        max_redirects=1,
        allow_http_errors=True,
    )
    if response.status >= 400:
        raise PublishError(
            f"Binary media upload failed with HTTP {response.status}.",
            retryable=response.status == 429 or response.status >= 500,
            rate_limited=response.status == 429,
        )


class TelegramBotPublisher(Publisher):
    def __init__(self, token: str, chat_id: str):
        if not token or not chat_id:
            raise PublishError("Telegram bot token and target chat are required.", retryable=False, auth_error=True)
        self.token = token
        self.chat_id = chat_id

    def publish(
        self,
        text: str,
        progress: dict[str, object],
        context: PublishContext,
        media: MediaPayload | None = None,
    ) -> PublishResult:
        remote_ids = list(progress.get("remote_ids", [])) if isinstance(progress.get("remote_ids"), list) else []
        media_sent = bool(progress.get("media_sent"))
        caption_used = bool(progress.get("caption_used"))
        remaining_text = text
        if media and not media_sent:
            caption = text if len(text) <= 1024 else ""
            method = "sendPhoto" if media.kind == "image" else "sendVideo"
            field = "photo" if media.kind == "image" else "video"
            context.before_write()
            payload = _post_multipart(
                f"https://api.telegram.org/bot{self.token}/{method}",
                {"chat_id": self.chat_id, "caption": caption},
                field,
                media,
            )
            if payload.get("ok") is not True:
                raise PublishError(str(payload.get("description", "Telegram rejected the media.")))
            result = payload.get("result")
            message_id = str(result.get("message_id")) if isinstance(result, dict) and result.get("message_id") else ""
            if message_id:
                remote_ids.append(message_id)
            caption_used = bool(caption)
            media_sent = True
            progress = {**progress, "media_sent": True, "caption_used": caption_used, "remote_ids": remote_ids}
            context.save_progress(progress)
        if caption_used:
            remaining_text = ""
        parts = telegram_split(remaining_text) if remaining_text else []
        sent_parts = int(progress.get("sent_parts", 0))
        for index in range(sent_parts, len(parts)):
            context.before_write()
            payload = _post_form(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                {"chat_id": self.chat_id, "text": parts[index], "disable_web_page_preview": "false"},
            )
            if payload.get("ok") is not True:
                raise PublishError(str(payload.get("description", "Telegram rejected the message.")))
            result = payload.get("result")
            message_id = str(result.get("message_id")) if isinstance(result, dict) and result.get("message_id") else ""
            if message_id:
                remote_ids.append(message_id)
            progress = {
                **progress,
                "media_sent": media_sent,
                "caption_used": caption_used,
                "sent_parts": index + 1,
                "remote_ids": remote_ids,
            }
            context.save_progress(progress)
        return PublishResult(remote_id=remote_ids[-1] if remote_ids else None, progress=progress)


class FacebookPagePublisher(Publisher):
    def __init__(self, page_id: str, token: str, graph_version: str):
        if not page_id or not token or not graph_version:
            raise PublishError("Facebook Page ID, Page token and Graph API version are required.", retryable=False, auth_error=True)
        self.page_id = page_id
        self.token = token
        self.graph_version = graph_version

    def publish(
        self,
        text: str,
        progress: dict[str, object],
        context: PublishContext,
        media: MediaPayload | None = None,
    ) -> PublishResult:
        context.before_write()
        if media:
            endpoint = "photos" if media.kind == "image" else "videos"
            text_field = "caption" if media.kind == "image" else "description"
            payload = _post_multipart(
                f"https://graph.facebook.com/{self.graph_version}/{self.page_id}/{endpoint}",
                {text_field: text, "access_token": self.token, "published": "true"},
                "source",
                media,
                timeout=300,
            )
        else:
            payload = _post_form(
                f"https://graph.facebook.com/{self.graph_version}/{self.page_id}/feed",
                {"message": text, "access_token": self.token},
            )
        remote_id = str(payload.get("post_id") or payload.get("id") or "") or None
        if not remote_id:
            raise PublishError("Facebook did not return a post ID.")
        return PublishResult(remote_id=remote_id, progress={})


class ThreadsPublisher(Publisher):
    def __init__(self, user_id: str, token: str):
        if not user_id or not token:
            raise PublishError("Threads user ID and token are required.", retryable=False, auth_error=True)
        self.user_id = user_id
        self.token = token
        self.base = "https://graph.threads.net/v1.0"

    def _wait_until_ready(self, container_id: str) -> None:
        for _ in range(30):
            response = fetch_url(
                f"{self.base}/{quote(container_id)}?fields=status,error_message",
                headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
                max_bytes=2 * 1024 * 1024,
                allowed_content_types={"application/json", "text/javascript"},
                timeout=30,
                max_redirects=0,
                allow_http_errors=True,
            )
            payload = response.json() if response.body else {}
            if not isinstance(payload, dict):
                raise PublishError("Threads returned invalid media status.")
            status = str(payload.get("status", "")).upper()
            if status in {"FINISHED", "PUBLISHED"}:
                return
            if status == "ERROR" or payload.get("error"):
                raise PublishError(str(payload.get("error_message") or payload.get("error") or "Threads media processing failed."))
            time.sleep(2)
        raise PublishError("Threads media processing did not finish in time.")

    def publish(
        self,
        text: str,
        progress: dict[str, object],
        context: PublishContext,
        media: MediaPayload | None = None,
    ) -> PublishResult:
        parts = split_threads_chain(text, 500)
        remote_ids = list(progress.get("remote_ids", [])) if isinstance(progress.get("remote_ids"), list) else []
        published_parts = int(progress.get("published_parts", len(remote_ids)) or 0)
        published_parts = min(published_parts, len(remote_ids), len(parts))

        for index in range(published_parts, len(parts)):
            saved_index = int(progress.get("container_part_index", -1) or -1)
            container_id = str(progress.get("container_id", "")) if saved_index in {-1, index} else ""
            reply_to_id = str(remote_ids[-1]) if remote_ids else ""
            part_media = media if index == 0 else None

            if not container_id:
                context.before_write()
                fields: dict[str, object] = {"text": parts[index], "access_token": self.token}
                if reply_to_id:
                    fields["reply_to_id"] = reply_to_id
                if part_media:
                    if not part_media.public_url:
                        raise PublishError("Threads requires a public direct media URL.")
                    fields["media_type"] = "IMAGE" if part_media.kind == "image" else "VIDEO"
                    fields["image_url" if part_media.kind == "image" else "video_url"] = part_media.public_url
                else:
                    fields["media_type"] = "TEXT"
                payload = _post_form(f"{self.base}/{self.user_id}/threads", fields)
                container_id = str(payload.get("id", ""))
                if not container_id:
                    raise PublishError("Threads did not return a creation container ID.")
                progress = {
                    **progress,
                    "container_id": container_id,
                    "container_part_index": index,
                    "published_parts": published_parts,
                    "remote_ids": remote_ids,
                    "total_parts": len(parts),
                }
                context.save_progress(progress)

            if part_media:
                self._wait_until_ready(container_id)
            context.before_write()
            payload = _post_form(
                f"{self.base}/{self.user_id}/threads_publish",
                {"creation_id": container_id, "access_token": self.token},
            )
            remote_id = str(payload.get("id", ""))
            if not remote_id:
                raise PublishError("Threads did not return a published post ID.")
            remote_ids.append(remote_id)
            published_parts = index + 1
            progress = {
                key: value
                for key, value in progress.items()
                if key not in {"container_id", "container_part_index"}
            }
            progress.update(
                {
                    "published_parts": published_parts,
                    "remote_ids": remote_ids,
                    "total_parts": len(parts),
                }
            )
            context.save_progress(progress)

        return PublishResult(remote_id=str(remote_ids[0]) if remote_ids else None, progress=progress)


class LinkedInPublisher(Publisher):
    def __init__(self, author_urn: str, token: str, version: str):
        if not author_urn or not token or not version:
            raise PublishError("LinkedIn author URN, token and YYYYMM API version are required.", retryable=False, auth_error=True)
        self.author_urn = author_urn
        self.token = token
        self.version = version

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "Linkedin-Version": self.version,
        }

    def _register_and_upload(self, media: MediaPayload, context: PublishContext) -> str:
        recipe = "feedshare-image" if media.kind == "image" else "feedshare-video"
        context.before_write()
        payload, _ = _post_json(
            "https://api.linkedin.com/v2/assets?action=registerUpload",
            {
                "registerUploadRequest": {
                    "recipes": [f"urn:li:digitalmediaRecipe:{recipe}"],
                    "owner": self.author_urn,
                    "serviceRelationships": [
                        {"relationshipType": "OWNER", "identifier": "urn:li:userGeneratedContent"}
                    ],
                }
            },
            self.headers,
        )
        value = payload.get("value") if isinstance(payload.get("value"), dict) else {}
        mechanism = value.get("uploadMechanism") if isinstance(value.get("uploadMechanism"), dict) else {}
        request_info = mechanism.get("com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest")
        if not isinstance(request_info, dict):
            raise PublishError("LinkedIn did not return a media upload URL.")
        upload_url = str(request_info.get("uploadUrl", ""))
        asset = str(value.get("asset", ""))
        if not upload_url or not asset:
            raise PublishError("LinkedIn media registration is incomplete.")
        _upload_binary(upload_url, media, {"Authorization": f"Bearer {self.token}"})
        return asset

    def publish(
        self,
        text: str,
        progress: dict[str, object],
        context: PublishContext,
        media: MediaPayload | None = None,
    ) -> PublishResult:
        if not media:
            context.before_write()
            _, headers = _post_json(
                "https://api.linkedin.com/rest/posts",
                {
                    "author": self.author_urn,
                    "commentary": text,
                    "visibility": "PUBLIC",
                    "distribution": {
                        "feedDistribution": "MAIN_FEED",
                        "targetEntities": [],
                        "thirdPartyDistributionChannels": [],
                    },
                    "lifecycleState": "PUBLISHED",
                    "isReshareDisabledByAuthor": False,
                },
                self.headers,
            )
            remote_id = headers.get("x-restli-id")
            if not remote_id:
                raise PublishError("LinkedIn did not return x-restli-id.")
            return PublishResult(remote_id=remote_id, progress={})

        asset = str(progress.get("asset", ""))
        if not asset:
            asset = self._register_and_upload(media, context)
            progress = {"asset": asset}
            context.save_progress(progress)
        context.before_write()
        payload, headers = _post_json(
            "https://api.linkedin.com/v2/ugcPosts",
            {
                "author": self.author_urn,
                "lifecycleState": "PUBLISHED",
                "specificContent": {
                    "com.linkedin.ugc.ShareContent": {
                        "shareCommentary": {"text": text},
                        "shareMediaCategory": "IMAGE" if media.kind == "image" else "VIDEO",
                        "media": [
                            {
                                "status": "READY",
                                "media": asset,
                                "title": {"text": media.name[:200]},
                            }
                        ],
                    }
                },
                "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
            },
            {
                "Authorization": f"Bearer {self.token}",
                "X-Restli-Protocol-Version": "2.0.0",
            },
            timeout=120,
        )
        remote_id = headers.get("x-restli-id") or str(payload.get("id", "")) or None
        if not remote_id:
            raise PublishError("LinkedIn did not return a post ID.")
        return PublishResult(remote_id=remote_id, progress=progress)


class PublisherFactory:
    def __init__(self, config: AppConfig):
        self.config = config

    def create(self, platform: str) -> Publisher:
        if platform == "telegram":
            return TelegramBotPublisher(self.config.telegram_bot_token, self.config.telegram_chat_id)
        if platform.startswith("facebook:"):
            page_id = platform.split(":", 1)[1]
            page = self.config.facebook_page(page_id)
            if page is not None:
                return FacebookPagePublisher(page["id"], page["access_token"], self.config.meta_graph_version)
            if platform == "facebook:1":
                return FacebookPagePublisher(
                    self.config.facebook_page_1_id,
                    self.config.facebook_page_1_token,
                    self.config.meta_graph_version,
                )
            if platform == "facebook:2":
                return FacebookPagePublisher(
                    self.config.facebook_page_2_id,
                    self.config.facebook_page_2_token,
                    self.config.meta_graph_version,
                )
            raise PublishError(f"Facebook page is not configured: {page_id}", retryable=False, auth_error=True)
        if platform == "threads":
            return ThreadsPublisher(self.config.threads_user_id, self.config.threads_token)
        if platform == "linkedin":
            return LinkedInPublisher(
                self.config.linkedin_author_urn,
                self.config.linkedin_token,
                self.config.linkedin_version,
            )
        raise PublishError(f"Unsupported publication platform: {platform}", retryable=False)
