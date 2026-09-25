from __future__ import annotations

from .google_drive import GoogleDriveError
from .managed_media_drive import ManagedMediaUpload
from .multi_image_store_v1_2_rc4 import MAX_IMAGE_ATTACHMENTS, MultiImageStore, StoredImageAttachment


def register_secondary_image(db, registry, store: MultiImageStore, upload: ManagedMediaUpload, group_id: int) -> None:
    if upload.info.kind != "image":
        raise GoogleDriveError("До фотогалереї можна додавати тільки зображення.")
    group = db.get_group(group_id)
    rows = store.list_group(group_id)
    if rows and rows[0].file_id != group.media_file_id:
        rows = []
    if not rows and group.media_file_id and group.media_kind == "image":
        rows = [StoredImageAttachment(
            group.media_file_id,
            group.media_name or "image",
            group.media_mime or "image/jpeg",
            int(group.media_size or 0),
            group.media_drive_url,
        )]
    if not rows or group.media_kind != "image":
        raise GoogleDriveError("Спочатку має бути прикріплене основне фото.")
    if len(rows) >= MAX_IMAGE_ATTACHMENTS:
        raise GoogleDriveError(f"До однієї публікації можна додати не більше {MAX_IMAGE_ATTACHMENTS} фото.")
    store.set_group(group_id, rows)
    registry.register(upload.info.file_id, folder_id=upload.folder_id, group_id=group_id, name=upload.info.name)
    store.append(group_id, StoredImageAttachment(
        upload.info.file_id,
        upload.info.name,
        upload.info.mime_type,
        upload.info.size,
        f"https://drive.google.com/file/d/{upload.info.file_id}/view",
    ))
