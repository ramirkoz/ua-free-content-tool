from __future__ import annotations

from .comment_phase_v1_2_rc3 import CommentPhaseKeys, begin_phase, finish_phase, unknown_phase_error
from .models import MediaPayload
from .publication_policy_v1_2_rc3 import DONATION_COMMENT
from .publishers import PublishContext, PublishResult, _post_form
from .safe_publishers_v1_2 import SafeThreadsPublisher

_KEYS = CommentPhaseKeys("threads_donation")
_CONTAINER = "threads_donation_container_id"
_PUBLISH_STARTED = "threads_donation_publish_started"


class CommentedThreadsPublisher(SafeThreadsPublisher):
    def publish(self, text: str, progress: dict[str, object], context: PublishContext, media: MediaPayload | None = None) -> PublishResult:
        main = super().publish(text, progress, context, media)
        progress = dict(main.progress)
        remote_ids = progress.get("remote_ids") if isinstance(progress.get("remote_ids"), list) else []
        root_id = str(remote_ids[0] if remote_ids else main.remote_id or "").strip()
        if not root_id:
            raise unknown_phase_error("Threads", "визначення кореневого поста")
        if DONATION_COMMENT in text:
            return PublishResult(remote_id=root_id, progress=progress)
        if bool(progress.get(_KEYS.comment_completed)):
            return PublishResult(remote_id=root_id, progress=progress)

        container_id = str(progress.get(_CONTAINER) or "").strip()
        if not container_id:
            progress = begin_phase(
                progress,
                context,
                started_key=_KEYS.comment_started,
                completed_key=_KEYS.comment_completed,
            )
            try:
                payload = _post_form(
                    f"{self.base}/{self.user_id}/threads",
                    {
                        "media_type": "TEXT",
                        "text": DONATION_COMMENT,
                        "reply_to_id": root_id,
                        "access_token": self.token,
                    },
                )
            except Exception as exc:
                raise unknown_phase_error("Threads", "створення донатної відповіді") from exc
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
        try:
            payload = _post_form(
                f"{self.base}/{self.user_id}/threads_publish",
                {"creation_id": container_id, "access_token": self.token},
            )
        except Exception as exc:
            raise unknown_phase_error("Threads", "публікація донатної відповіді") from exc
        comment_id = str(payload.get("id") or "").strip()
        progress = finish_phase(
            progress,
            context,
            completed_key=_KEYS.comment_completed,
            id_key=_KEYS.comment_id,
            remote_id=comment_id,
        )
        return PublishResult(remote_id=root_id, progress=progress)
