from __future__ import annotations

from ..google_drive import GoogleDriveError
from ..image_registration_v1_2_rc4 import register_secondary_image
from ..managed_media_drive import ManagedMediaUpload
from ..multi_image_store_v1_2_rc4 import StoredImageAttachment


class MultiImageActionsMixin:
    def _attachment_rows(self, group_id: int | None = None) -> list[StoredImageAttachment]:
        target = int(group_id or getattr(self, "current_group_id", 0) or 0)
        if not target:
            return []
        group = self.db.get_group(target)
        if not group.media_file_id:
            return []
        rows = self.multi_image_store.list_group(target)
        if rows and rows[0].file_id == group.media_file_id:
            return rows
        if group.media_kind == "image":
            return [StoredImageAttachment(
                file_id=group.media_file_id,
                name=group.media_name or "image",
                mime_type=group.media_mime or "image/jpeg",
                size=int(group.media_size or 0),
                drive_url=group.media_drive_url,
            )]
        return []

    def _refresh_attached_images(self) -> None:
        rows = self._attachment_rows()
        if len(rows) > 1 and hasattr(self, "media_status_var"):
            self.media_status_var.set(f"Прикріплено фото: {len(rows)} із 10. Google Drive: перевірено ✓")

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
                    uploaded.append(client.upload_validated_media(media, filename))
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
            total = len(self._attachment_rows(group_id))
            self.media_candidates_status_var.set(f"Прикріплено фото: {total}. Google Drive: перевірено ✓")

        self.run_async(action, success, label=label, done_label="Фотогалерею оновлено")
