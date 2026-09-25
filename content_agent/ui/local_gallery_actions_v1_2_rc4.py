from __future__ import annotations

from pathlib import Path

from ..google_drive import GoogleDriveError
from ..local_gallery_v1_2_rc4 import prepare_local_gallery


class LocalGalleryActionsMixin:
    def add_media_from_computer(self) -> None:
        group_id = getattr(self, "current_group_id", None)
        if group_id is None:
            self.msg.showinfo("Медіа", "Спочатку відкрийте новину в редакторі.", parent=self.root)
            return
        selected = self.files.askopenfilenames(
            parent=self.root,
            title="Оберіть фото або одне відео",
            filetypes=[
                ("Фото й відео", "*.jpg *.jpeg *.png *.gif *.webp *.mp4 *.webm"),
                ("Усі файли", "*.*"),
            ],
        )
        if not selected:
            return
        try:
            prepared = prepare_local_gallery([Path(value) for value in selected])
        except Exception as exc:
            self._show_error(exc)
            return
        if not prepared:
            return
        kinds = {getattr(media, "kind", "") for media, _name in prepared}
        if kinds != {"image"}:
            if self._attachment_rows(group_id):
                self._show_error(GoogleDriveError("Відео може бути лише єдиним медіафайлом. Спочатку приберіть фото."))
                return
            media, filename = prepared[0]
            self._upload_media(media, filename, label="Перевіряю локальне відео й додаю в Google Drive")
            return
        if len(self._attachment_rows(group_id)) + len(prepared) > 10:
            self._show_error(GoogleDriveError("До однієї публікації можна додати не більше 10 фото."))
            return
        self._upload_image_batch(prepared, group_id, label=f"Додаю фото в Google Drive: {len(prepared)}")
