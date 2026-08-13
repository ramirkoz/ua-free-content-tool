from __future__ import annotations

from urllib.parse import quote

from .comment_phase_v1_2_rc3 import CommentPhaseKeys, begin_phase, finish_phase, unknown_phase_error
from .models import MediaPayload
from .publication_policy_v1_2_rc3 import DONATION_COMMENT
from .publishers import PublishContext, PublishResult
from .safe_publishers_v1_2 import SafeLinkedInPublisher, _linkedin_post_json

_KEYS = CommentPhaseKeys("linkedin_donation")


class CommentedLinkedInPublisher(SafeLinkedInPublisher):
    def publish(self, text: str, progress: dict[str, object], context: PublishContext, media: MediaPayload | None = None) -> PublishResult:
        main = super().publish(text, progress, context, media)
        progress = dict(main.progress)
        post_id = str(main.remote_id or progress.get("linkedin_post_id") or "").strip()
        if not post_id:
            raise unknown_phase_error("LinkedIn", "визначення основного поста")
        if bool(progress.get(_KEYS.comment_completed)):
            return PublishResult(remote_id=post_id, progress=progress)

        progress = begin_phase(
            progress,
            context,
            started_key=_KEYS.comment_started,
            completed_key=_KEYS.comment_completed,
        )
        endpoint = f"https://api.linkedin.com/rest/socialActions/{quote(post_id, safe='')}/comments"
        try:
            payload, headers = _linkedin_post_json(
                endpoint,
                {
                    "actor": self.author_urn,
                    "object": post_id,
                    "message": {"text": DONATION_COMMENT},
                },
                self.headers,
                timeout=60,
            )
        except Exception as exc:
            raise unknown_phase_error("LinkedIn", "донатний коментар") from exc
        comment_id = str(headers.get("x-restli-id") or payload.get("id") or "").strip()
        progress = finish_phase(
            progress,
            context,
            completed_key=_KEYS.comment_completed,
            id_key=_KEYS.comment_id,
            remote_id=comment_id,
        )
        return PublishResult(remote_id=post_id, progress=progress)
