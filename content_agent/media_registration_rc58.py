from __future__ import annotations
from .google_drive import GoogleDriveError
from .managed_media_drive import ManagedMediaUpload
from .multi_image_store_v1_2_rc4 import MAX_IMAGE_ATTACHMENTS, MultiImageStore, StoredImageAttachment

def register_secondary_media(db, registry, store: MultiImageStore, upload: ManagedMediaUpload, group_id: int) -> None:
    if upload.info.kind not in {"image", "video"}:
        raise GoogleDriveError("Підтримуються тільки фото та відео.")
    group = db.get_group(group_id)
    rows = store.list_group(group_id)
    if rows and rows[0].file_id != group.media_file_id:
        rows = []
    if not rows and group.media_file_id and group.media_kind in {"image", "video"}:
        rows = [StoredImageAttachment(group.media_file_id, group.media_name or group.media_kind, group.media_mime or ("image/jpeg" if group.media_kind == "image" else "video/mp4"), int(group.media_size or 0), group.media_drive_url)]
    if not rows or group.media_kind != upload.info.kind:
        raise GoogleDriveError("Додаткове медіа має бути того самого типу, що й основне.")
    if len(rows) >= MAX_IMAGE_ATTACHMENTS:
        raise GoogleDriveError(f"До однієї публікації можна додати не більше {MAX_IMAGE_ATTACHMENTS} медіафайлів.")
    store.set_group(group_id, rows)
    registry.register(upload.info.file_id, folder_id=upload.folder_id, group_id=group_id, name=upload.info.name)
    store.append(group_id, StoredImageAttachment(upload.info.file_id, upload.info.name, upload.info.mime_type, upload.info.size, f"https://drive.google.com/file/d/{upload.info.file_id}/view"))
