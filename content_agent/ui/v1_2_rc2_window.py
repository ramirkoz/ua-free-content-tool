from __future__ import annotations

import logging
import threading

from ..google_drive import GoogleDriveError
from ..managed_media_drive import ManagedMediaUpload
from ..media_candidates import MediaCandidate, MediaCandidateError, ValidatedMedia, download_media_candidate
from ..media_discovery import discover_group_media
from ..media_priority_v1_2 import prioritize_media_candidates
from ..safe_publishers_v1_2 import SafePublisherFactory
from ..security import redact_url
from ..worker_v1_2 import ManagedMediaPublicationWorker
from .media_workflow import media_filename_from_url
from .v1_2_combined_window import MainWindow as RC1MainWindow

logger = logging.getLogger("content_agent.media")


class MainWindow(RC1MainWindow):
    """RC2: duplicate-safe publishing plus video-first media recovery."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)

        # RC1 creates its worker before the delayed startup gate. Replace it here
        # before that thread can start so LinkedIn and Threads use the hardened
        # publisher implementations.
        self.publisher_factory = SafePublisherFactory(self.config)
        self.worker = ManagedMediaPublicationWorker(
            self.db,
            self.publisher_factory,
            inter_target_delay_seconds=5.0,
            max_automatic_attempts=3,
            progress_callback=self._publication_progress_from_worker,
            result_callback=self._publication_result_from_worker,
            managed_media_registry=self.managed_media_registry,
        )
        self.worker_thread = threading.Thread(
            target=self.worker.run_loop,
            args=(self.stop_event,),
            name="publication-worker",
            daemon=True,
        )
        self.root.title("UA FREE Content Tool — v1.3.1-rc7")

    @staticmethod
    def _prioritize(candidates: list[MediaCandidate]) -> list[MediaCandidate]:
        return prioritize_media_candidates(candidates)

    def discover_current_group_media(self) -> None:
        group_id = getattr(self, "current_group_id", None)
        articles = list(getattr(self, "current_group_articles", []))
        if group_id is None:
            self.msg.showinfo("Медіа", "Спочатку відкрийте новину в редакторі.", parent=self.root)
            return
        self._media_discovery_group_id = group_id
        self.media_candidates_status_var.set(
            f"Перевіряю джерела: {len(articles)}. Відео має пріоритет над заставкою або скриншотом."
        )

        def action() -> object:
            try:
                candidates = self._prioritize(discover_group_media(articles))
                self.media_candidate_store.save_group(group_id, candidates)
                logger.info("Media discovery completed for group=%s candidates=%s", group_id, len(candidates))
                return candidates
            except Exception as exc:
                logger.warning("Media discovery failed for group=%s: %s", group_id, exc)
                raise

        def success(result: object) -> None:
            if self.current_group_id != group_id:
                return
            candidates = list(result) if isinstance(result, list) else []
            self._set_media_candidates(candidates)
            videos = sum(item.kind == "video" for item in candidates)
            if candidates:
                suffix = f" Відео: {videos}." if videos else ""
                self.media_candidates_status_var.set(
                    f"Знайдено медіафайлів: {len(candidates)}.{suffix} "
                    "Якщо є відео, воно показується вище заставок і прев’ю."
                )
            else:
                self.media_candidates_status_var.set(
                    "У джерелах не знайдено придатного медіа. Додайте файл із комп’ютера або за посиланням."
                )

        self.run_async(
            action,
            success,
            label=f"Шукаю медіа для блоку #{group_id}",
            done_label="Пошук медіа завершено",
        )

    @staticmethod
    def _replacement_candidate(
        original: MediaCandidate,
        fresh: list[MediaCandidate],
    ) -> MediaCandidate | None:
        same_source = [
            item
            for item in fresh
            if (item.source_label or "").strip().casefold()
            == (original.source_label or "").strip().casefold()
        ]
        pool = same_source or fresh
        # If the source now exposes a real video, prefer it even when the stale
        # candidate was its JPEG poster/thumbnail.
        for item in pool:
            if item.kind == "video":
                return item
        for item in pool:
            if item.kind == original.kind:
                return item
        return pool[0] if pool else None

    def use_selected_media_candidate(self) -> None:
        candidate = self._selected_media_candidate()
        if candidate is None:
            self.msg.showinfo("Медіа", "Оберіть файл у списку знайдених медіа.", parent=self.root)
            return
        group_id = getattr(self, "current_group_id", None)
        articles = list(getattr(self, "current_group_articles", []))
        if group_id is None:
            self.msg.showinfo("Медіа", "Спочатку відкрийте новину в редакторі.", parent=self.root)
            return
        self._media_target_group_id = group_id

        def action() -> object:
            selected = candidate
            refreshed: list[MediaCandidate] | None = None
            try:
                media = download_media_candidate(selected)
            except MediaCandidateError as exc:
                if "HTTP 404" not in str(exc):
                    logger.warning(
                        "Media candidate failed group=%s kind=%s url=%s: %s",
                        group_id,
                        selected.kind,
                        redact_url(selected.url),
                        exc,
                    )
                    raise
                logger.info(
                    "Stale media URL detected group=%s kind=%s url=%s; refreshing source page",
                    group_id,
                    selected.kind,
                    redact_url(selected.url),
                )
                refreshed = self._prioritize(discover_group_media(articles))
                replacement = self._replacement_candidate(selected, refreshed)
                if replacement is None:
                    raise MediaCandidateError(
                        "Старе медіапосилання вже недоступне (HTTP 404), а після повторного відкриття новини "
                        "свіжого фото або відео не знайдено."
                    ) from exc
                selected = replacement
                media = download_media_candidate(selected)
                logger.info(
                    "Stale media replaced group=%s kind=%s url=%s",
                    group_id,
                    selected.kind,
                    redact_url(selected.url),
                )

            filename = media_filename_from_url(media.source_url or selected.url, media.mime_type)
            upload = self._managed_drive_client().upload_validated_media(media, filename)
            return upload, selected, refreshed

        def success(result: object) -> None:
            upload, selected, refreshed = result  # type: ignore[misc]
            if not isinstance(upload, ManagedMediaUpload):
                raise GoogleDriveError("Google Drive не повернув результат завантаження.")
            if isinstance(refreshed, list):
                prioritized = self._prioritize(list(refreshed))
                self.media_candidate_store.save_group(group_id, prioritized)
                if self.current_group_id == group_id:
                    self._set_media_candidates(prioritized)
            self._attach_uploaded_media(upload)
            if self.current_group_id == group_id:
                kind_label = "відео" if getattr(selected, "kind", "") == "video" else "фото"
                self.media_candidates_status_var.set(
                    f"Використано {kind_label} з джерела «{getattr(selected, 'source_label', '') or 'новина'}». "
                    "Файл завантажено в Google Drive і перевірено."
                )

        self.run_async(
            action,
            success,
            label="Перевіряю вибране медіа та додаю в Google Drive",
            done_label="Вибране медіа готове",
        )
