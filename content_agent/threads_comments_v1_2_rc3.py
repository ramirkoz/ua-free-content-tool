from __future__ import annotations

from .comment_phase_v1_2_rc3 import CommentPhaseKeys, begin_phase, finish_phase, unknown_phase_error
from .media_gallery_v1_2_rc4 import ImageGalleryPayload
from .models import MediaPayload
from .publication_policy_v1_2_rc3 import DONATION_COMMENT
from .publishers import PublishContext, PublishError, PublishResult, _post_form
from .safe_publishers_v1_2 import SafeThreadsPublisher

_KEYS = CommentPhaseKeys("threads_donation")
_CONTAINER = "threads_donation_container_id"
_PUBLISH_STARTED = "threads_donation_publish_started"


class CommentedThreadsPublisher(SafeThreadsPublisher):
    def _publish_gallery_root(
        self,
        text: str,
        progress: dict[str, object],
        context: PublishContext,
        gallery: ImageGalleryPayload,
    ) -> PublishResult:
        remote_id = str(progress.get("threads_gallery_remote_id") or "").strip()
        if remote_id:
            return PublishResult(remote_id=remote_id, progress=progress)
        child_ids = list(progress.get("threads_gallery_children") or [])
        for item in gallery.items[len(child_ids):]:
            if not item.public_url:
                raise PublishError("Threads потребує тимчасово доступне URL для кожного фото.")
            payload = _post_form(
                f"{self.base}/{self.user_id}/threads",
                {
                    "media_type": "IMAGE",
                    "image_url": item.public_url,
                    "is_carousel_item": "true",
                    "access_token": self.token,
                },
            )
            child_id = str(payload.get("id") or "").strip()
            if not child_id:
                raise PublishError("Threads не повернув ID елемента каруселі.")
            child_ids.append(child_id)
            progress = {**progress, "threads_gallery_children": child_ids}
            context.save_progress(progress)
        container_id = str(progress.get("threads_gallery_container_id") or "").strip()
        if not container_id:
            payload = _post_form(
                f"{self.base}/{self.user_id}/threads",
                {
                    "media_type": "CAROUSEL",
                    "children": ",".join(child_ids),
                    "text": text,
                    "access_token": self.token,
                },
            )
            container_id = str(payload.get("id") or "").strip()
            if not container_id:
                raise PublishError("Threads не повернув ID каруселі.")
            progress = {**progress, "threads_gallery_container_id": container_id}
            context.save_progress(progress)
        self._wait_until_ready(container_id)
        if progress.get("threads_gallery_publish_started") and not progress.get("threads_gallery_remote_id"):
            raise PublishError(
                "Threads: результат публікації каруселі невідомий; автоматичний повтор заблоковано.",
                retryable=False,
                outcome_unknown=True,
            )
        progress = {**progress, "threads_gallery_publish_started": True}
        context.save_progress(progress)
        context.before_write()
        payload = _post_form(
            f"{self.base}/{self.user_id}/threads_publish",
            {"creation_id": container_id, "access_token": self.token},
        )
        remote_id = str(payload.get("id") or "").strip()
        if not remote_id:
            raise PublishError("Threads не повернув ID опублікованої каруселі.")
        progress = {**progress, "threads_gallery_remote_id": remote_id}
        context.save_progress(progress)
        return PublishResult(remote_id=remote_id, progress=progress)

    def publish(self, text: str, progress: dict[str, object], context: PublishContext, media: MediaPayload | ImageGalleryPayload | None = None) -> PublishResult:
        main = self._publish_gallery_root(text, progress, context, media) if isinstance(media, ImageGalleryPayload) else super().publish(text, progress, context, media)
        progress = dict(main.progress)
        remote_ids = progress.get("remote_ids") if isinstance(progress.get("remote_ids"), list) else []
        root_id = str(main.remote_id or (remote_ids[0] if remote_ids else "")).strip()
        if not root_id:
            raise unknown_phase_error("Threads", "визначення кореневого поста")
        if DONATION_COMMENT in text:
            return PublishResult(remote_id=root_id, progress=progress)
        if bool(progress.get(_KEYS.comment_completed)):
            return PublishResult(remote_id=root_id, progress=progress)
        container_id = str(progress.get(_CONTAINER) or "").strip()
        if not container_id:
            progress = begin_phase(progress, context, started_key=_KEYS.comment_started, completed_key=_KEYS.comment_completed)
            payload = _post_form(
                f"{self.base}/{self.user_id}/threads",
                {"media_type": "TEXT", "text": DONATION_COMMENT, "reply_to_id": root_id, "access_token": self.token},
            )
            container_id = str(payload.get("id") or "").strip()
            if not container_id:
                raise unknown_phase_error("Threads", "створення донатної відповіді")
            progress = {**progress, _CONTAINER: container_id}
            context.save_progress(progress)
        if bool(progress.get(_PUBLISH_STARTED)) and not progress.get(_KEYS.comment_id):
            raise unknown_phase_error("Threads", "публікація донатної відповіді")
        progress = {**progress, _PUBLISH_STARTED: True}
        context.save_progress(progress)
        context.before_write()
        payload = _post_form(
            f"{self.base}/{self.user_id}/threads_publish",
            {"creation_id": container_id, "access_token": self.token},
        )
        comment_id = str(payload.get("id") or "").strip()
        progress = finish_phase(progress, context, completed_key=_KEYS.comment_completed, id_key=_KEYS.comment_id, remote_id=comment_id)
        return PublishResult(remote_id=root_id, progress=progress)
