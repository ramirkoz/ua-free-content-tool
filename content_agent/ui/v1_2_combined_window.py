from __future__ import annotations

from tkinter import simpledialog

from ..google_drive import GoogleDriveError
from ..managed_media_drive import ManagedMediaUpload
from ..media_candidates import ValidatedMedia
from ..media_discovery import resolve_manual_media_url
from .media_workflow import MediaWorkflowMixin, media_filename_from_url
from .v1_2_window import MainWindow as EditorialMemoryMainWindow


class MainWindow(MediaWorkflowMixin, EditorialMemoryMainWindow):
    """Combined v1.2 window: clear editorial memory plus automatic media workflow."""

    def add_media_by_url(self) -> None:
        value = simpledialog.askstring(
            "Додати медіа за посиланням",
            "Вставте пряме посилання на фото/відео або адресу вебсторінки:",
            parent=self.root,
        )
        if not value:
            return
        requested_url = value.strip()

        def action() -> object:
            media, candidates = resolve_manual_media_url(requested_url)
            if isinstance(media, ValidatedMedia):
                filename = media_filename_from_url(media.source_url or requested_url, media.mime_type)
                upload = self._managed_drive_client().upload_validated_media(media, filename)
                return "uploaded", upload
            return "candidates", list(candidates)

        def success(result: object) -> None:
            mode, payload = result  # type: ignore[misc]
            if mode == "uploaded":
                if not isinstance(payload, ManagedMediaUpload):
                    raise GoogleDriveError("Google Drive не повернув результат завантаження.")
                self._attach_uploaded_media(payload)
                self.media_candidates_status_var.set(
                    "Файл за посиланням автоматично завантажено й перевірено."
                )
                return
            found = list(payload) if isinstance(payload, list) else []
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
