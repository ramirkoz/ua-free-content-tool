from __future__ import annotations

import json
from urllib.parse import quote

from .comment_phase_v1_2_rc3 import CommentPhaseKeys, begin_phase, finish_phase
from .media_gallery_v1_2_rc4 import ImageGalleryPayload
from .models import MediaPayload
from .publication_policy_v1_2_rc3 import DONATION_COMMENT
from .publishers import FacebookPagePublisher, PublishContext, PublishError, PublishResult, _post_form, _post_multipart

_KEYS = CommentPhaseKeys("facebook_donation")


def _reset_started(
    progress: dict[str, object],
    context: PublishContext,
    started_key: str,
) -> dict[str, object]:
    """Clear a write marker only after a definite API rejection.

    ``PublishError`` from the platform helpers means an HTTP/API response was
    received. In that case the request was explicitly rejected and a later
    retry may safely re-enter the phase after the user fixes permissions or a
    rate limit. Transport/programming failures keep the marker so Facebook is
    never called blindly a second time.
    """

    updated = {**progress, started_key: False}
    context.save_progress(updated)
    return updated


def _known_phase_error(phase: str, exc: PublishError) -> PublishError:
    return PublishError(
        f"Facebook · {phase}: {exc}",
        code=exc.code,
        subcode=exc.subcode,
        retryable=exc.retryable,
        auth_error=exc.auth_error,
        rate_limited=exc.rate_limited,
        outcome_unknown=False,
    )


def _local_unknown_phase_error(phase: str, exc: BaseException | None = None) -> PublishError:
    """Represent an ambiguous Facebook sub-write without killing other targets.

    The durable ``*_started`` marker remains set, therefore the Facebook write
    itself cannot be repeated automatically. ``outcome_unknown`` is deliberately
    false at worker level so independent Threads/LinkedIn/Telegram targets in
    the same package can still be processed. The ambiguity is contained by the
    Facebook phase marker instead of aborting the whole package.
    """

    detail = f" Причина: {exc}" if exc is not None and str(exc).strip() else ""
    return PublishError(
        f"Facebook: результат етапу «{phase}» невідомий. Facebook повторно не викликається автоматично; "
        f"інші платформи пакета можна продовжити.{detail}",
        retryable=False,
        outcome_unknown=False,
    )


def _unresolved_marker_error(phase: str) -> PublishError:
    return PublishError(
        f"Facebook: попередній етап «{phase}» почався без підтвердження завершення. "
        "Повтор саме цього Facebook-запису заблоковано, щоб не створити дубль; інші платформи пакета можна продовжити.",
        retryable=False,
        outcome_unknown=False,
    )


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
        if not post_id and bool(progress.get(_KEYS.main_started)) and not bool(progress.get(_KEYS.main_completed)):
            raise _unresolved_marker_error("основний пост")

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
            except PublishError as exc:
                _reset_started(progress, context, _KEYS.main_started)
                raise _known_phase_error("основний пост із фотогалереєю", exc) from exc
            except Exception as exc:
                raise _local_unknown_phase_error("основний пост із фотогалереєю", exc) from exc
            post_id = str(payload.get("post_id") or payload.get("id") or "").strip()
            progress = finish_phase(progress, context, completed_key=_KEYS.main_completed, id_key=_KEYS.main_id, remote_id=post_id)
        elif not post_id:
            progress = begin_phase(progress, context, started_key=_KEYS.main_started, completed_key=_KEYS.main_completed)
            try:
                main = super().publish(text, progress, context, media)
            except PublishError as exc:
                _reset_started(progress, context, _KEYS.main_started)
                raise _known_phase_error("основний пост", exc) from exc
            except Exception as exc:
                raise _local_unknown_phase_error("основний пост", exc) from exc
            post_id = str(main.remote_id or "")
            progress = finish_phase(progress, context, completed_key=_KEYS.main_completed, id_key=_KEYS.main_id, remote_id=post_id)

        if DONATION_COMMENT in text:
            return PublishResult(remote_id=post_id, progress=progress)
        if bool(progress.get(_KEYS.comment_completed)):
            return PublishResult(remote_id=post_id, progress=progress)
        if bool(progress.get(_KEYS.comment_started)) and not bool(progress.get(_KEYS.comment_completed)):
            raise _unresolved_marker_error("донатний коментар")

        progress = begin_phase(progress, context, started_key=_KEYS.comment_started, completed_key=_KEYS.comment_completed)
        try:
            payload = _post_form(
                f"https://graph.facebook.com/{self.graph_version}/{quote(post_id, safe='')}/comments",
                {"message": DONATION_COMMENT, "access_token": self.token},
            )
        except PublishError as exc:
            _reset_started(progress, context, _KEYS.comment_started)
            raise _known_phase_error("донатний коментар", exc) from exc
        except Exception as exc:
            raise _local_unknown_phase_error("донатний коментар", exc) from exc
        comment_id = str(payload.get("id") or "")
        progress = finish_phase(progress, context, completed_key=_KEYS.comment_completed, id_key=_KEYS.comment_id, remote_id=comment_id)
        return PublishResult(remote_id=post_id, progress=progress)
