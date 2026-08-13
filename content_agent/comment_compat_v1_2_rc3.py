from __future__ import annotations

from .facebook_comments_v1_2_rc3 import CommentedFacebookPublisher
from .linkedin_comments_v1_2_rc3 import CommentedLinkedInPublisher
from .media_gallery_v1_2_rc4 import ImageGalleryPayload
from .models import MediaPayload
from .publication_text import footer_for
from .publishers import FacebookPagePublisher, PublishContext, PublishError, PublishResult, TelegramBotPublisher
from .safe_publishers_v1_2 import SafeLinkedInPublisher, SafeThreadsPublisher
from .threads_comments_v1_2_rc3 import CommentedThreadsPublisher


def _legacy_payload(text: str, platform: str) -> bool:
    footer = footer_for(platform)
    return bool(footer and footer in str(text or ""))


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
            result = TelegramBotPublisher.publish(
                self,
                text if index == 0 else "",
                {},
                context,
                media.items[index],
            )
            if result.remote_id:
                remote_ids.append(str(result.remote_id))
            progress = {
                **progress,
                "telegram_gallery_started": None,
                "telegram_gallery_sent": index + 1,
                "telegram_gallery_remote_ids": remote_ids,
            }
            context.save_progress(progress)
        return PublishResult(remote_id=remote_ids[0] if remote_ids else None, progress=progress)


class CompatibleFacebookPublisher(CommentedFacebookPublisher):
    def publish(self, text: str, progress: dict[str, object], context: PublishContext, media: MediaPayload | None = None) -> PublishResult:
        if _legacy_payload(text, "facebook"):
            return FacebookPagePublisher.publish(self, text, progress, context, media)
        return super().publish(text, progress, context, media)


class CompatibleThreadsPublisher(CommentedThreadsPublisher):
    def publish(self, text: str, progress: dict[str, object], context: PublishContext, media: MediaPayload | None = None) -> PublishResult:
        if _legacy_payload(text, "threads"):
            return SafeThreadsPublisher.publish(self, text, progress, context, media)
        return super().publish(text, progress, context, media)


class CompatibleLinkedInPublisher(CommentedLinkedInPublisher):
    def publish(self, text: str, progress: dict[str, object], context: PublishContext, media: MediaPayload | None = None) -> PublishResult:
        if _legacy_payload(text, "linkedin"):
            return SafeLinkedInPublisher.publish(self, text, progress, context, media)
        return super().publish(text, progress, context, media)
