from __future__ import annotations

from urllib.parse import quote

from .comment_phase_v1_2_rc3 import CommentPhaseKeys, begin_phase, finish_phase, unknown_phase_error
from .models import MediaPayload
from .publication_policy_v1_2_rc3 import DONATION_COMMENT
from .publishers import FacebookPagePublisher, PublishContext, PublishResult, _post_form

_KEYS = CommentPhaseKeys("facebook_donation")


class CommentedFacebookPublisher(FacebookPagePublisher):
    def publish(self, text: str, progress: dict[str, object], context: PublishContext, media: MediaPayload | None = None) -> PublishResult:
        post_id = str(progress.get(_KEYS.main_id) or "").strip()
        if not post_id:
            progress = begin_phase(
                progress,
                context,
                started_key=_KEYS.main_started,
                completed_key=_KEYS.main_completed,
            )
            try:
                main = super().publish(text, progress, context, media)
            except Exception as exc:
                raise unknown_phase_error("Facebook", "основний пост") from exc
            post_id = str(main.remote_id or "")
            progress = finish_phase(
                progress,
                context,
                completed_key=_KEYS.main_completed,
                id_key=_KEYS.main_id,
                remote_id=post_id,
            )

        # RC2 packages already queued before this policy change contain the
        # fundraiser in their root payload. Preserve them as-is and do not add a
        # second fundraiser below the post.
        if DONATION_COMMENT in text:
            return PublishResult(remote_id=post_id, progress=progress)
        if bool(progress.get(_KEYS.comment_completed)):
            return PublishResult(remote_id=post_id, progress=progress)
        progress = begin_phase(
            progress,
            context,
            started_key=_KEYS.comment_started,
            completed_key=_KEYS.comment_completed,
        )
        try:
            payload = _post_form(
                f"https://graph.facebook.com/{self.graph_version}/{quote(post_id, safe='')}/comments",
                {"message": DONATION_COMMENT, "access_token": self.token},
            )
        except Exception as exc:
            raise unknown_phase_error("Facebook", "донатний коментар") from exc
        comment_id = str(payload.get("id") or "")
        progress = finish_phase(
            progress,
            context,
            completed_key=_KEYS.comment_completed,
            id_key=_KEYS.comment_id,
            remote_id=comment_id,
        )
        return PublishResult(remote_id=post_id, progress=progress)
