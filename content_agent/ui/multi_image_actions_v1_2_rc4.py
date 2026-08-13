from __future__ import annotations

from pathlib import Path

from ..google_drive import GoogleDriveError
from ..image_registration_v1_2_rc4 import register_secondary_image
from ..local_gallery_v1_2_rc4 import prepare_local_gallery
from ..managed_media_drive import ManagedMediaUpload
from ..media_candidates import download_media_candidate
from .media_workflow import media_filename_from_url


class MultiImageActionsMixin:
    def register_extra_image(self, upload: ManagedMediaUpload, group_id: int) -> None:
        register_secondary_image(
            self.db,
            self.managed_media_registry,
            self.multi_image_store,
            upload,
            group_id,
        )
        self._refresh_attached_images()

    def _commit_uploaded_images(self, uploads: list[ManagedMediaUpload], group_id: int) -> None:
        if not uploads:
            return
        group = self.db.get_group(group_id)
        start = 0
        if not group.media_file_id:
            self._media_target_group_id = group_id
            self._attach_uploaded_media(uploads[0])
            start = 1
        elif group.media_kind != "image":
            raise GoogleDriveError("Не можна додавати фото до прикріпленого відео.")
        for upload in uploads[start:]:
            self.register_extra_image(upload, group_id)
        self._refresh_attached_images()

    def _upload_image_batch(self, prepared: list[tuple[object, str]], group_id: int, *, label: str) -> None:
        def action() -> object:
            client = self._managed_drive_client()
            uploaded: list[ManagedMediaUpload] = []
            try:
                for media, filename in prepared:
                    upload = client.upload_validated_media(media, filename)
                    uploaded.append(upload)
                return uploaded
            except Exception:
                for upload in uploaded:
                    try:
                        client.delete_file(upload.info.file_id)
                    except GoogleDriveError:
                        pass
                raise

        def success(result: object) -> None:
            uploads = list(result) if isinstance(result, list) else []
            self._commit_uploaded_images(uploads, group_id)
            self.media_candidates_status_var.set(f"Додано фото: {len(uploads)}. Google Drive: перевірено ✓")

        self.run_async(
            action,
            success,
            label=label,
            done_label="Фотогалерею оновлено",
        )
