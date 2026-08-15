from __future__ import annotations

import json
import secrets

from .facebook_comments_v1_2_rc3 import CommentedFacebookPublisher
from .linkedin_comments_v1_2_rc3 import CommentedLinkedInPublisher
from .media_gallery_v1_2_rc4 import ImageGalleryPayload
from .models import MediaPayload
from .network import NetworkError, fetch_url
from .publication_text import FUND_FOOTER, footer_for
from .publishers import (
    PublishContext,
    PublishError,
    PublishResult,
    TelegramBotPublisher,
    _check_payload,
)
from .threads_comments_v1_2_rc3 import CommentedThreadsPublisher


def _without_legacy_footer(text: str, platform: str) -> str:
    """Normalize queued pre-RC3 payloads for comment-only platforms."""

    value = str(text or "").strip()
    footer = footer_for(platform)
    if not footer or footer not in value:
        return value
    return "\n\n".join(part.strip() for part in value.split(footer) if part.strip()).strip()


def _with_inline_fund_footer(text: str) -> str:
    """Ensure exactly one donation block in the root post.

    This also upgrades already queued LinkedIn payloads created before RC8, so
    they do not need a new OAuth scope just to create a donation comment.
    """

    value = str(text or "").strip()
    if FUND_FOOTER in value:
        return value
    parts = [part.strip() for part in value.split("\n\n") if part.strip()]
    if parts and parts[-1].startswith("Джерело: "):
        source = parts.pop()
        parts.extend([FUND_FOOTER, source])
    else:
        parts.append(FUND_FOOTER)
    return "\n\n".join(parts)


def _telegram_media_group_body(
    chat_id: str,
    text: str,
    gallery: ImageGalleryPayload,
) -> tuple[bytes, str]:
    """Build one Telegram sendMediaGroup multipart body for 2-10 photos."""

    boundary = "----UAFreeAlbum" + secrets.token_hex(16)
    media_rows: list[dict[str, object]] = []
    for index, item in enumerate(gallery.items):
        row: dict[str, object] = {
            "type": "photo",
            "media": f"attach://photo{index}",
        }
        if index == 0 and text:
            row["caption"] = text
        media_rows.append(row)

    chunks: list[bytes] = []
    fields = {
        "chat_id": chat_id,
        "media": json.dumps(media_rows, ensure_ascii=False, separators=(",", ":")),
    }
    for key, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )

    for index, item in enumerate(gallery.items):
        safe_name = item.name.replace('"', "_").replace("\r", "_").replace("\n", "_")
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    f'Content-Disposition: form-data; name="photo{index}"; '
                    f'filename="{safe_name}"\r\n'
                ).encode("utf-8"),
                f"Content-Type: {item.mime_type}\r\n\r\n".encode(),
                item.data,
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _telegram_send_media_group(
    token: str,
    chat_id: str,
    text: str,
    gallery: ImageGalleryPayload,
) -> list[str]:
    body, content_type = _telegram_media_group_body(chat_id, text, gallery)
    response = fetch_url(
        f"https://api.telegram.org/bot{token}/sendMediaGroup",
        method="POST",
        headers={"Content-Type": content_type, "Accept": "application/json"},
        body=body,
        max_bytes=4 * 1024 * 1024,
        allowed_content_types={"application/json", "text/javascript"},
        timeout=300,
        max_redirects=1,
        allow_http_errors=True,
    )
    payload = response.json() if response.body else {}
    if response.status >= 400:
        _check_payload(payload, http_status=response.status)
        raise PublishError(
            f"Telegram sendMediaGroup failed with HTTP {response.status}.",
            retryable=response.status == 429 or response.status >= 500,
            rate_limited=response.status == 429,
        )
    checked = _check_payload(payload)
    result = checked.get("result")
    if not isinstance(result, list):
        raise PublishError(
            "Telegram не повернув список повідомлень після публікації альбому.",
            retryable=False,
            outcome_unknown=True,
        )
    remote_ids = [
        str(row.get("message_id"))
        for row in result
        if isinstance(row, dict) and row.get("message_id") not in (None, "")
    ]
    if not remote_ids:
        raise PublishError(
            "Telegram опрацював альбом, але не повернув жодного message_id.",
            retryable=False,
            outcome_unknown=True,
        )
    return remote_ids


class CompatibleTelegramPublisher(TelegramBotPublisher):
    def _publish_legacy_gallery(
        self,
        text: str,
        progress: dict[str, object],
        context: PublishContext,
        media: ImageGalleryPayload,
    ) -> PublishResult:
        """Finish only galleries that v1.2.0 already started photo-by-photo."""

        sent = int(progress.get("telegram_gallery_sent") or 0)
        remote_ids = list(progress.get("telegram_gallery_remote_ids") or [])
        for index in range(sent, len(media.items)):
            if progress.get("telegram_gallery_started") == index:
                raise PublishError(
                    "Telegram: попереднє фото має невідомий результат; автоматичний повтор заблоковано.",
                    retryable=False,
                    outcome_unknown=True,
                )
            progress = {**progress, "telegram_gallery_started": index}
            context.save_progress(progress)
            outer_progress = dict(progress)

            def save_sub(sub: dict[str, object]) -> None:
                context.save_progress({**outer_progress, "telegram_gallery_sub": sub})

            sub_context = PublishContext(before_write=context.before_write, save_progress=save_sub)
            result = TelegramBotPublisher.publish(
                self,
                text if index == 0 else "",
                {},
                sub_context,
                media.items[index],
            )
            if result.remote_id:
                remote_ids.append(str(result.remote_id))
            progress = {
                **progress,
                "telegram_gallery_started": None,
                "telegram_gallery_sent": index + 1,
                "telegram_gallery_remote_ids": remote_ids,
                "telegram_gallery_sub": {},
            }
            context.save_progress(progress)
        return PublishResult(remote_id=remote_ids[0] if remote_ids else None, progress=progress)

    def publish(
        self,
        text: str,
        progress: dict[str, object],
        context: PublishContext,
        media: MediaPayload | ImageGalleryPayload | None = None,
    ) -> PublishResult:
        if not isinstance(media, ImageGalleryPayload):
            return super().publish(text, progress, context, media)

        # Never change transport semantics halfway through an old v1.2.0
        # gallery. That could duplicate photos. Only fresh galleries use albums.
        legacy_sent = int(progress.get("telegram_gallery_sent") or 0)
        legacy_started = progress.get("telegram_gallery_started") is not None
        if legacy_sent or legacy_started:
            return self._publish_legacy_gallery(text, progress, context, media)

        remote_ids = list(progress.get("telegram_album_remote_ids") or [])
        if bool(progress.get("telegram_album_completed")) and remote_ids:
            return PublishResult(remote_id=str(remote_ids[0]), progress=progress)
        if bool(progress.get("telegram_album_started")):
            raise PublishError(
                "Telegram: результат попередньої публікації альбому невідомий; автоматичний повтор заблоковано.",
                retryable=False,
                outcome_unknown=True,
            )

        progress = {**progress, "telegram_album_started": True, "telegram_album_completed": False}
        context.save_progress(progress)
        context.before_write()
        try:
            remote_ids = _telegram_send_media_group(self.token, self.chat_id, text, media)
        except PublishError as exc:
            # A definitive 4xx response means Telegram rejected the request and
            # no album exists. Clear the barrier so a corrected payload may run.
            if not exc.retryable and not exc.outcome_unknown:
                progress = {**progress, "telegram_album_started": False}
                context.save_progress(progress)
                raise
            raise PublishError(
                "Telegram: результат публікації альбому невідомий; автоматичний повтор заблоковано, щоб не створити дубль.",
                retryable=False,
                outcome_unkown=True,
            ) from exc
        except NetworkError as exc:
            raise PublishError(
                "Telegram: зеднання перервалося під час публікації альбому. Результат невідомий; автоматичний повтор заблоковано.",
                retryable=False,
                outcome_unknown=True,
            ) from exc

        progress = {
            **progress,
            "telegram_album_started": False,
            "telegram_album_completed": True,
            "telegram_album_remote_ids": remote_ids,
        }
        context.save_progress(progress)
        return PublishResult(remote_id=remote_ids[0], progress=progress)


class CompatibleFacebookPublisher(CommentedFacebookPublisher):
    def publish(self, text: str, progress: dict[str, object], context: PublishContext, media: MediaPayload | ImageGalleryPayload | None = None) -> PublishResult:
        return super().publish(_without_legacy_footer(text, "facebook"), progress, context, media)


class CompatibleThreadsPublisher(CommentedThreadsPublisher):
    def publish(self, text: str, progress: dict[str, object], context: PublishContext, media: MediaPayload | ImageGalleryPayload | None = None) -> PublishResult:
        return super().publish(_without_legacy_footer(text, "threads"), progress, context, media)


class CompatibleLinkedInPublisher(CommentedLinkedInPublisher):
    def publish(self, text: str, progress: dict[str, object], context: PublishContext, media: MediaPayload | ImageGalleryPayload | None = None) -> PublishResult:
        # RC8 final policy: LinkedIn keeps the donation block in the root post.
        # CommentedLinkedInPublisher detects FUND_FOOTER in text and therefore
        # skips the separate /socialActions/.../comments call entirely.
        return super().publish(_with_inline_fund_footer(text), progress, context, media)
