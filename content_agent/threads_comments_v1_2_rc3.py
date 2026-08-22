from __future__ import annotations

from urllib.parse import quote

from .comment_phase_v1_2_rc3 import CommentPhaseKeys, finish_phase, unknown_phase_error
from .editorial_memory import split_threads_chain
from .media_gallery_v1_2_rc4 import ImageGalleryPayload
from .models import MediaPayload
from .network import NetworkError, fetch_url
from .publication_text import THREADS_FUND_FOOTER
from .publishers import PublishContext, PublishError, PublishResult, _check_payload, _post_form
from .safe_publishers_v1_2 import SafeThreadsPublisher

_KEYS = CommentPhaseKeys("threads_donation")
_CONTAINER = "threads_donation_container_id"
_PUBLISH_STARTED = "threads_donation_publish_started"
_GALLERY_REPLY_IDS = "threads_gallery_text_reply_ids"
_GALLERY_REPLY_STARTED = "threads_gallery_text_reply_started"


class CommentedThreadsPublisher(SafeThreadsPublisher):
    def _container_status(self, container_id: str) -> str:
        response = fetch_url(
            f"{self.base}/{quote(container_id)}?fields=id,status,error_message",
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
            max_bytes=2 * 1024 * 1024,
            allowed_content_types={"application/json", "text/javascript"},
            timeout=30,
            max_redirects=0,
            allow_http_errors=True,
        )
        payload = response.json() if response.body else {}
        if response.status >= 400:
            _check_payload(payload, http_status=response.status)
            raise PublishError(
                f"Threads: перевірка контейнера завершилась HTTP {response.status}.",
                retryable=response.status == 429 or response.status >= 500,
                rate_limited=response.status == 429,
            )
        checked = _check_payload(payload)
        return str(checked.get("status") or "").upper()

    def _publish_text_reply_once(
        self,
        text: str,
        reply_to_id: str,
        progress: dict[str, object],
        context: PublishContext,
        *,
        started_key: str,
        completed_key: str,
        id_key: str,
        phase_name: str,
    ) -> tuple[str, dict[str, object]]:
        existing = str(progress.get(id_key) or "").strip()
        if bool(progress.get(completed_key)) and existing:
            return existing, progress
        if bool(progress.get(started_key)):
            raise unknown_phase_error("Threads", phase_name)

        progress = {**progress, started_key: True, completed_key: False}
        context.save_progress(progress)
        context.before_write()
        try:
            payload = _post_form(
                f"{self.base}/{self.user_id}/threads",
                {
                    "media_type": "TEXT",
                    "text": text,
                    "reply_to_id": reply_to_id,
                    "auto_publish_text": "true",
                    "access_token": self.token,
                },
            )
        except PublishError as exc:
            # A definitive API rejection means nothing was published, so the
            # marker can be cleared. Transport/5xx ambiguity remains fail-closed.
            if not exc.retryable and not exc.outcome_unknown:
                progress = {**progress, started_key: False}
                context.save_progress(progress)
                raise
            raise unknown_phase_error("Threads", phase_name) from exc
        except NetworkError as exc:
            raise unknown_phase_error("Threads", phase_name) from exc

        remote_id = str(payload.get("id") or "").strip()
        if not remote_id:
            raise unknown_phase_error("Threads", phase_name)
        progress = finish_phase(
            progress,
            context,
            completed_key=completed_key,
            id_key=id_key,
            remote_id=remote_id,
        )
        progress = {**progress, started_key: False}
        context.save_progress(progress)
        return remote_id, progress

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
            context.before_write()
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
            context.before_write()
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
            try:
                status = self._container_status(container_id)
            except Exception as exc:
                raise PublishError(
                    "Threads: не вдалося перевірити попередню спробу публікації каруселі; автоматичний повтор заблоковано.",
                    retryable=False,
                    outcome_unknown=True,
                ) from exc
            if status == "FINISHED":
                pass
            elif status == "PUBLISHED":
                raise PublishError(
                    "Threads: карусель уже опублікована, але ID опублікованого поста не був отриманий. Автоматичний дубль заблоковано.",
                    retryable=False,
                    outcome_unknown=True,
                )
            else:
                raise PublishError(
                    f"Threads: результат публікації каруселі невідомий (status={status or 'UNKNOWN'}); автоматичний повтор заблоковано.",
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
            raise PublishError(
                "Threads не повернув ID опублікованої каруселі.",
                retryable=False,
                outcome_unknown=True,
            )
        progress = {
            **progress,
            "threads_gallery_publish_started": False,
            "threads_gallery_remote_id": remote_id,
        }
        context.save_progress(progress)
        return PublishResult(remote_id=remote_id, progress=progress)

    def _publish_gallery_text_replies(
        self,
        parts: list[str],
        root_id: str,
        progress: dict[str, object],
        context: PublishContext,
    ) -> tuple[str, dict[str, object]]:
        reply_ids = [str(item) for item in list(progress.get(_GALLERY_REPLY_IDS) or []) if str(item)]
        if len(reply_ids) > max(0, len(parts) - 1):
            reply_ids = reply_ids[: len(parts) - 1]
        parent_id = reply_ids[-1] if reply_ids else root_id

        for part_index in range(1 + len(reply_ids), len(parts)):
            marker = int(progress.get(_GALLERY_REPLY_STARTED) or 0)
            if marker == part_index:
                raise unknown_phase_error("Threads", f"публікація частини {part_index + 1} каруселі")
            progress = {**progress, _GALLERY_REPLY_STARTED: part_index}
            context.save_progress(progress)
            context.before_write()
            try:
                payload = _post_form(
                    f"{self.base}/{self.user_id}/threads",
                    {
                        "media_type": "TEXT",
                        "text": parts[part_index],
                        "reply_to_id": parent_id,
                        "auto_publish_text": "true",
                        "access_token": self.token,
                    },
                )
            except PublishError as exc:
                if not exc.retryable and not exc.outcome_unknown:
                    progress = {**progress, _GALLERY_REPLY_STARTED: 0}
                    context.save_progress(progress)
                    raise
                raise unknown_phase_error("Threads", f"публікація частини {part_index + 1} каруселі") from exc
            except NetworkError as exc:
                raise unknown_phase_error("Threads", f"публікація частини {part_index + 1} каруселі") from exc

            reply_id = str(payload.get("id") or "").strip()
            if not reply_id:
                raise unknown_phase_error("Threads", f"публікація частини {part_index + 1} каруселі")
            reply_ids.append(reply_id)
            parent_id = reply_id
            progress = {
                **progress,
                _GALLERY_REPLY_STARTED: 0,
                _GALLERY_REPLY_IDS: reply_ids,
            }
            context.save_progress(progress)
        return parent_id, progress

    def _finish_legacy_donation_if_possible(
        self,
        root_id: str,
        progress: dict[str, object],
        context: PublishContext,
    ) -> PublishResult | None:
        container_id = str(progress.get(_CONTAINER) or "").strip()
        if not container_id:
            return None
        if bool(progress.get(_KEYS.comment_completed)):
            return PublishResult(remote_id=root_id, progress=progress)

        try:
            status = self._container_status(container_id)
        except (PublishError, NetworkError) as exc:
            raise unknown_phase_error("Threads", "перевірка донатної відповіді") from exc

        if status == "PUBLISHED":
            progress = finish_phase(
                progress,
                context,
                completed_key=_KEYS.comment_completed,
                id_key=_KEYS.comment_id,
                remote_id=container_id,
            )
            progress = {**progress, _PUBLISH_STARTED: False}
            context.save_progress(progress)
            return PublishResult(remote_id=root_id, progress=progress)

        if status in {"ERROR", "EXPIRED"}:
            progress = {
                **progress,
                _CONTAINER: "",
                _PUBLISH_STARTED: False,
                _KEYS.comment_started: False,
            }
            context.save_progress(progress)
            return None

        if status != "FINISHED":
            raise unknown_phase_error("Threads", "публікація донатної відповіді")

        progress = {**progress, _PUBLISH_STARTED: True}
        context.save_progress(progress)
        context.before_write()
        payload = _post_form(
            f"{self.base}/{self.user_id}/threads_publish",
            {"creation_id": container_id, "access_token": self.token},
        )
        comment_id = str(payload.get("id") or "").strip()
        if not comment_id:
            raise unknown_phase_error("Threads", "публікація донатної відповіді")
        progress = finish_phase(
            progress,
            context,
            completed_key=_KEYS.comment_completed,
            id_key=_KEYS.comment_id,
            remote_id=comment_id,
        )
        progress = {**progress, _PUBLISH_STARTED: False}
        context.save_progress(progress)
        return PublishResult(remote_id=root_id, progress=progress)

    def publish(
        self,
        text: str,
        progress: dict[str, object],
        context: PublishContext,
        media: MediaPayload | ImageGalleryPayload | None = None,
    ) -> PublishResult:
        gallery_parts = split_threads_chain(text, 500) if isinstance(media, ImageGalleryPayload) else []
        if isinstance(media, ImageGalleryPayload):
            main = self._publish_gallery_root(gallery_parts[0], progress, context, media)
        else:
            main = super().publish(text, progress, context, media)

        progress = dict(main.progress)
        remote_ids = progress.get("remote_ids") if isinstance(progress.get("remote_ids"), list) else []
        root_id = str(main.remote_id or (remote_ids[0] if remote_ids else "")).strip()
        if not root_id:
            raise unknown_phase_error("Threads", "визначення кореневого поста")

        if gallery_parts:
            _last_text_id, progress = self._publish_gallery_text_replies(
                gallery_parts,
                root_id,
                progress,
                context,
            )

        # v1.2.0 could lose the final publish response after Meta had already
        # published the donation reply. Reconcile that state before any new write.
        legacy_result = self._finish_legacy_donation_if_possible(root_id, progress, context)
        if legacy_result is not None:
            return legacy_result

        if THREADS_FUND_FOOTER in text:
            return PublishResult(remote_id=root_id, progress=progress)
        if bool(progress.get(_KEYS.comment_completed)):
            return PublishResult(remote_id=root_id, progress=progress)

        _reply_id, progress = self._publish_text_reply_once(
            THREADS_FUND_FOOTER,
            root_id,
            progress,
            context,
            started_key=_KEYS.comment_started,
            completed_key=_KEYS.comment_completed,
            id_key=_KEYS.comment_id,
            phase_name="публікація донатної відповіді",
        )
        return PublishResult(remote_id=root_id, progress=progress)
