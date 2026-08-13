from __future__ import annotations

from urllib.parse import quote

from .comment_phase_v1_2_rc3 import CommentPhaseKeys, begin_phase, finish_phase, unknown_phase_error
from .media_gallery_v1_2_rc4 import ImageGalleryPayload
from .models import MediaPayload
from .publication_policy_v1_2_rc3 import DONATION_COMMENT
from .publishers import PublishContext, PublishError, PublishResult, _upload_binary
from .safe_publishers_v1_2 import SafeLinkedInPublisher, _linkedin_post_json

_KEYS = CommentPhaseKeys("linkedin_donation")


class CommentedLinkedInPublisher(SafeLinkedInPublisher):
    def _publish_gallery_root(
        self,
        text: str,
        progress: dict[str, object],
        context: PublishContext,
        gallery: ImageGalleryPayload,
    ) -> PublishResult:
        existing = self._existing_result(progress)
        if existing is not None:
            return existing
        image_urns = list(progress.get("linkedin_image_urns") or [])
        for item in gallery.items[len(image_urns):]:
            context.before_write()
            payload, _headers = _linkedin_post_json(
                "https://api.linkedin.com/rest/images?action=initializeUpload",
                {"initializeUploadRequest": {"owner": self.author_urn}},
                self.headers,
                timeout=60,
            )
            value = payload.get("value") if isinstance(payload.get("value"), dict) else {}
            upload_url = str(value.get("uploadUrl") or "").strip()
            image_urn = str(value.get("image") or "").strip()
            if not upload_url or not image_urn:
                raise PublishError("LinkedIn не повернув upload URL або Image URN.")
            _upload_binary(upload_url, item, {"Authorization": f"Bearer {self.token}"})
            image_urns.append(image_urn)
            progress = {**progress, "linkedin_image_urns": image_urns}
            context.save_progress(progress)
        post_payload = {
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
            "content": {
                "multiImage": {
                    "images": [{"id": urn, "altText": "UA FREE news image"} for urn in image_urns]
                }
            },
        }
        body, headers, progress = self._post_safely(
            url="https://api.linkedin.com/rest/posts",
            payload=post_payload,
            headers=self.headers,
            progress=progress,
            context=context,
            timeout=120,
        )
        remote_id = str(headers.get("x-restli-id") or body.get("id") or "").strip()
        if not remote_id:
            raise self._unknown("успішна multi-image відповідь не містить post ID")
        return self._finish_write(progress, context, remote_id)

    def publish(self, text: str, progress: dict[str, object], context: PublishContext, media: MediaPayload | ImageGalleryPayload | None = None) -> PublishResult:
        main = self._publish_gallery_root(text, progress, context, media) if isinstance(media, ImageGalleryPayload) else super().publish(text, progress, context, media)
        progress = dict(main.progress)
        post_id = str(main.remote_id or progress.get("linkedin_post_id") or "").strip()
        if not post_id:
            raise unknown_phase_error("LinkedIn", "визначення основного поста")
        if DONATION_COMMENT in text:
            return PublishResult(remote_id=post_id, progress=progress)
        if bool(progress.get(_KEYS.comment_completed)):
            return PublishResult(remote_id=post_id, progress=progress)
        progress = begin_phase(progress, context, started_key=_KEYS.comment_started, completed_key=_KEYS.comment_completed)
        endpoint = f"https://api.linkedin.com/rest/socialActions/{quote(post_id, safe='')}/comments"
        try:
            payload, headers = _linkedin_post_json(
                endpoint,
                {"actor": self.author_urn, "object": post_id, "message": {"text": DONATION_COMMENT}},
                self.headers,
                timeout=60,
            )
        except Exception as exc:
            raise unknown_phase_error("LinkedIn", "донатний коментар") from exc
        comment_id = str(headers.get("x-restli-id") or payload.get("id") or "").strip()
        progress = finish_phase(progress, context, completed_key=_KEYS.comment_completed, id_key=_KEYS.comment_id, remote_id=comment_id)
        return PublishResult(remote_id=post_id, progress=progress)
