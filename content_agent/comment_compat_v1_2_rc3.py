from __future__ import annotations

from .facebook_comments_v1_2_rc3 import CommentedFacebookPublisher
from .linkedin_comments_v1_2_rc3 import CommentedLinkedInPublisher
from .media_gallery_v1_2_rc4 import ImageGalleryPayload
from .models import MediaPayload
from .publication_text import FUND_FOOTER, footer_for
from .publishers import PublishContext, PublishError, PublishResult, TelegramBotPublisher
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


class CompatibleTelegramPublisher(TelegramBotPublisher):
    def publish(self, text: str, progress: dict[str, object], context: PublishContext, media: MediaPayload | ImageGalleryPayload | None = None) -> PublishResult:
        if not isinstance(media, ImageGalleryPayload):
            return super().publish(text, progress, context, media)
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


class CompatibleFacebookPublisher(CommentedFacebookPublisher):
    def publish(self, text: str, progress: dict[str, object], context: PublishContext, media: MediaPayload | ImageGalleryPayload | None = None) -> PublishResult:
        return super().publish(_without_legacy_footer(text, "facebook"), progress, context, media)


class CompatibleThreadsPublisher(CommentedThreadsPublisher):
    def publish(self, text: str, progress: dict[str, object], context: PublishContext, media: MediaPayload | None = None) -> PublishResult:
        return super().publish(_without_legacy_footer(text, "threads"), progress, context, media)


class CompatibleLinkedInPublisher(CommentedLinkedInPublisher):
    def publish(self, text: str, progress: dict[str, object], context: PublishContext, media: MediaPayload | ImageGalleryPayload | None = None) -> PublishResult:
        # RC8 final policy: LinkedIn keeps the donation block in the root post.
        # CommentedLinkedInPublisher detects FUND_FOOTER in text and therefore
        # skips the separate /socialActions/.../comments call entirely.
        return super().publish(_with_inline_fund_footer(text), progress, context, media)
