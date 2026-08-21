from __future__ import annotations

import threading
from tkinter import simpledialog

from ..google_drive import GoogleDriveError
from ..managed_media_drive import ManagedMediaUpload
from ..managed_media_registry import ManagedMediaRegistry, ManagedMediaRegistryError
from ..media_candidate_store import MediaCandidateStore, MediaCandidateStoreError
from ..media_candidates import ValidatedMedia
from ..media_discovery import discover_group_media, resolve_manual_media_url
from ..worker_v1_2 import ManagedMediaPublicationWorker
from .strict_media_preview import StrictMediaPreviewMixin
from .media_workflow import format_media_size, media_filename_from_url
from .v1_2_window import MainWindow as EditorialMemoryMainWindow


class MainWindow(StrictMediaPreviewMixin, EditorialMemoryMainWindow):
    """Combined v1.2 window: Editorial Memory plus automatic visual media workflow."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.media_candidate_store = MediaCandidateStore()
        self.managed_media_registry = ManagedMediaRegistry()
        self._media_target_group_id: int | None = None
        super().__init__(*args, **kwargs)

        # The base window creates its worker before the delayed startup gate. Swap
        # it here, while the original thread has not started, so v1.2 cleanup can
        # distinguish application-managed files from old user-owned Drive links.
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

    def load_group(self, group_id: int) -> None:
        super().load_group(group_id)
        try:
            cached = self.media_candidate_store.list_group(group_id)
        except MediaCandidateStoreError as exc:
            self.media_candidates_status_var.set(str(exc))
            return
        if cached:
            self._set_media_candidates(cached)
            self.media_candidates_status_var.set(
                f"Показано раніше знайдених медіафайлів: {len(cached)}. Джерела оновлюються у фоні."
            )

    def discover_current_group_media(self) -> None:
        group_id = getattr(self, "current_group_id", None)
        articles = list(getattr(self, "current_group_articles", []))
        if group_id is None:
            self.msg.showinfo("Медіа", "Спочатку відкрийте новину в редакторі.", parent=self.root)
            return
        self._media_discovery_group_id = group_id
        self.media_candidates_status_var.set(
            f"Перевіряю джерела: {len(articles)}. Це не змінює вже прикріплене медіа."
        )

        def action() -> object:
            candidates = discover_group_media(articles)
            self.media_candidate_store.save_group(group_id, candidates)
            return candidates

        def success(result: object) -> None:
            if self.current_group_id != group_id:
                return
            candidates = list(result) if isinstance(result, list) else []
            self._set_media_candidates(candidates)
            if candidates:
                self.media_candidates_status_var.set(
                    f"Знайдено медіафайлів: {len(candidates)}. Виберіть один і натисніть «Використати вибране»."
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

    def _schedule_old_managed_file_delete(self, file_id: str, group_id: int) -> None:
        def start() -> None:
            if self.operation_running:
                self.root.after(250, start)
                return

            def action() -> object:
                if not self.managed_media_registry.is_managed(file_id):
                    return False
                self._managed_drive_client().delete_file(file_id)
                self.managed_media_registry.remove(file_id)
                return True

            def success(result: object) -> None:
                if bool(result):
                    self.set_status(
                        f"Попередній керований медіафайл блока #{group_id} видалено з Google Drive."
                    )

            self.run_async(
                action,
                success,
                label="Видаляю попередній керований медіафайл",
                done_label="Попередній медіафайл опрацьовано",
            )

        self.root.after(250, start)

    def _delete_unattached_upload(self, file_id: str) -> None:
        try:
            self._managed_drive_client().delete_file(file_id)
        except GoogleDriveError:
            pass

    def _attach_uploaded_media(self, upload: ManagedMediaUpload) -> None:
        target_group_id = self._media_target_group_id
        if target_group_id is None:
            target_group_id = getattr(self, "current_group_id", None)
        if target_group_id is None:
            self._delete_unattached_upload(upload.info.file_id)
            raise GoogleDriveError("Новину було закрито до завершення завантаження; файл видалено з Drive.")

        previous = self.db.get_group(target_group_id)
        previous_file_id = str(previous.media_file_id or "")
        try:
            previous_was_managed = bool(
                previous_file_id
                and previous_file_id != upload.info.file_id
                and self.managed_media_registry.is_managed(previous_file_id)
            )
        except ManagedMediaRegistryError:
            self._media_target_group_id = None
            self._delete_unattached_upload(upload.info.file_id)
            raise

        drive_url = f"https://drive.google.com/file/d/{upload.info.file_id}/view"
        try:
            self.managed_media_registry.register(
                upload.info.file_id,
                folder_id=upload.folder_id,
                group_id=target_group_id,
                name=upload.info.name,
            )
            self.db.set_group_media(
                target_group_id,
                drive_url=drive_url,
                file_id=upload.info.file_id,
                name=upload.info.name,
                kind=upload.info.kind,
                mime=upload.info.mime_type,
                size=upload.info.size,
            )
        except Exception:
            try:
                self.managed_media_registry.remove(upload.info.file_id)
            except ManagedMediaRegistryError:
                pass
            self._delete_unattached_upload(upload.info.file_id)
            raise
        finally:
            self._media_target_group_id = None

        if getattr(self, "current_group_id", None) == target_group_id:
            self.media_url_var.set(drive_url)
            self.media_status_var.set(
                f"Медіа готове ✓ {upload.info.name} · {upload.info.kind.upper()} · "
                f"{format_media_size(upload.info.size)} · Google Drive: перевірено ✓"
            )
        else:
            self.set_status(
                f"Медіафайл автоматично додано й перевірено для блока #{target_group_id}. "
                "Відкрийте цей блок, щоб побачити прикріплення."
            )

        if previous_was_managed and previous_file_id != upload.info.file_id:
            should_delete = self.msg.askyesno(
                "Попередній медіафайл",
                f"До блока #{target_group_id} був прикріплений інший файл, який програма раніше "
                "завантажила в Google Drive.\n\nВидалити попередній файл із Google Drive?",
                parent=self.root,
            )
            if should_delete:
                self._schedule_old_managed_file_delete(previous_file_id, target_group_id)

    def _upload_media(self, media: ValidatedMedia, filename: str, *, label: str) -> None:
        self._media_target_group_id = getattr(self, "current_group_id", None)
        super()._upload_media(media, filename, label=label)

    def use_selected_media_candidate(self) -> None:
        if self._selected_media_candidate() is None:
            self._media_target_group_id = None
            super().use_selected_media_candidate()
            return
        self._media_target_group_id = getattr(self, "current_group_id", None)
        super().use_selected_media_candidate()

    def add_media_by_url(self) -> None:
        value = simpledialog.askstring(
            "Додати медіа за посиланням",
            "Вставте пряме посилання на фото/відео або адресу вебсторінки:",
            parent=self.root,
        )
        if not value:
            return
        requested_url = value.strip()
        group_id = getattr(self, "current_group_id", None)
        if group_id is None:
            self.msg.showinfo("Медіа", "Спочатку відкрийте новину в редакторі.", parent=self.root)
            return
        self._media_target_group_id = group_id

        def action() -> object:
            media, candidates = resolve_manual_media_url(requested_url)
            if isinstance(media, ValidatedMedia):
                filename = media_filename_from_url(media.source_url or requested_url, media.mime_type)
                upload = self._managed_drive_client().upload_validated_media(media, filename)
                return "uploaded", upload
            found = list(candidates)
            self.media_candidate_store.save_group(group_id, found)
            return "candidates", found

        def success(result: object) -> None:
            mode, payload = result  # type: ignore[misc]
            if mode == "uploaded":
                if not isinstance(payload, ManagedMediaUpload):
                    raise GoogleDriveError("Google Drive не повернув результат завантаження.")
                self._attach_uploaded_media(payload)
                if self.current_group_id == group_id:
                    self.media_candidates_status_var.set(
                        "Файл за посиланням автоматично завантажено й перевірено."
                    )
                return
            self._media_target_group_id = None
            found = list(payload) if isinstance(payload, list) else []
            if self.current_group_id != group_id:
                return
            self._set_media_candidates(found)
            self.media_candidates_status_var.set(
                f"На сторінці знайдено медіафайлів: {len(found)}. Оберіть потрібний."
            )

        self.run_async(
            action,
            success,
            label="Перевіряю посилання та готую медіа",
            done_label="Посилання опрацьовано",
        )
