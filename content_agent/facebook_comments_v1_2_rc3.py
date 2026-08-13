from __future__ import annotations

import json
from urllib.parse import quote

from .comment_phase_v1_2_rc3 import CommentPhaseKeys, begin_phase, finish_phase, unknown_phase_error
from .media_gallery_v1_2_rc4 import ImageGalleryPayload
from .models import MediaPayload
from .publication_policy_v1_2_rc3 import DONATION_COMMENT
from .publishers import FacebookPagePublisher, PublishContext, PublishError, PublishResult, _post_form, _post_multipart

_KEYS = CommentPhaseKeys("facebook_donation")


class CommentedFacebookPublisher(FacebookPagePublisher):
    def _prepare_gallery(self, gallery: ImageGalleryPayload, progress: dict[str, object], context: PublishContext) -> tuple[list[str], dict[str, object]]:
        photo_ids = list(progress.get("facebook_gallery_photo_ids") or [])
        for item in gallery.items[len(photo_ids):]:
            payload = _post_multipart(
                f"https://graph.facebook.com/{self.graph_version}/{self.page_id}/photos",
                {"published": "false", "access_token": self.token},
                "source",
                item,
                timeout=300,
            )
            photo_id = str(payload.get("id") or "").strip()
            if not photo_id:
                raise PublishError("Facebook не повернув ID підготовленого фото.")
            photo_ids.append(photo_id)
            progress = {**progress, "facebook_gallery_photo_ids": photo_ids}
            context.save_progress(progress)
        return photo_ids, progress

    def publish(self, text: str, progress: dict[str, object], context: PublishContext, media: MediaPayload | ImageGalleryPayload | None = None) -> PublishResult:
        post_id = str(progress.get(_KEYS.main_id) or "").strip()
        if not post_id and isinstance(media, ImageGalleryPayload):
            photo_ids, progress = self._prepare_gallery(media, progress, context)
            progress = begin_phase(progress, context, started_key=_KEYS.main_started, completed_key=_KEYS.main_completed)
            fields: dict[str, object] = {"message": text, "access_token": self.token}
            for index, photo_id in enumerate(photo_ids):
                fields[f"attached_media[{index}]"] = json.dumps({"media_fbid": photo_id})
            try:
                payload = _post_form(
                    f"https://graph.facebook.com/{self.graph_version}/{self.page_id}/feed",
                    fields,
                    timeout=120,
                )
            except Exception as exc:
                raise unknown_phase_error("Facebook", "основний пост із фотогалереєю") from exc
            post_id = str(payload.get("post_id") or payload.get("id") or "").strip()
            progress = finish_phase(progress, context, completed_key=_KEYS.main_completed, id_key=_KEYS.main_id, remote_id=post_id)
        elif not post_id:
            progress = begin_phase(progress, context, started_key=_KEYS.main_started, completed_key=_KEYS.main_completed)
            try:
                main = super().publish(text, progress, context, media)
            except Exception as exc:
                raise unknown_phase_error("Facebook", "основний пост") from exc
            post_id = str(main.remote_id or "")
            progress = finish_phase(progress, context, completed_key=_KEYS.main_completed, id_key=_KEYS.main_id, remote_id=post_id)

        if DONATION_COMMENT in text:
            return PublishResult(remote_id=post_id, progress=progress)
        if bool(progress.get(_KEYS.comment_completed)):
            return PublishResult(remote_id=post_id, progress=progress)
        progress = begin_phase(progress, context, started_key=_KEYS.comment_started, completed_key=_KEYS.comment_completed)
        try:
            payload = _post_form(
                f"https://graph.facebook.com/{self.graph_version}/{quote(post_id, safe='')}/comments",
                {"message": DONATION_COMMENT, "access_token": self.token},
            )
        except Exception as exc:
            raise unknown_phase_error("Facebook", "донатний коментар") from exc
        comment_id = str(payload.get("id") or "")
        progress = finish_phase(progress, context, completed_key=_KEYS.comment_completed, id_key=_KEYS.comment_id, remote_id=comment_id)
        return PublishResult(remote_id=post_id, progress=progress)
