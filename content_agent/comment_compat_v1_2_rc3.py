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
