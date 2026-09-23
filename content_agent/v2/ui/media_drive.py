from __future__ import annotations

import json
from urllib.parse import quote, urlencode

from ...google_drive import DriveMediaInfo, _validate_file_id
from ...managed_media_drive import ManagedGoogleDriveClient, ManagedMediaUpload
from ...media_candidates import ValidatedMedia
from ...readable_media_names import readable_post_media_filename


class ReadableMediaDriveClient(ManagedGoogleDriveClient):
    """Google Drive client that gives publication media deterministic human names."""

    def __init__(self, client_id: str, client_secret: str, refresh_token: str, *, post_title: str = "", group_id: int = 0) -> None:
        super().__init__(client_id, client_secret, refresh_token)
        self._post_title = str(post_title or "")
        self._group_id = int(group_id or 0)

    def _publication_filename(self, mime_type: str) -> str:
        return readable_post_media_filename(self._post_title, self._group_id, mime_type)

    def upload_validated_media(self, media: ValidatedMedia, filename: str, *, folder_id: str = "", folder_name: str = "UA FREE Content Tool Media") -> ManagedMediaUpload:
        del filename
        return super().upload_validated_media(media, self._publication_filename(media.mime_type), folder_id=folder_id, folder_name=folder_name)

    def rename_media_file(self, file_id: str, filename: str) -> DriveMediaInfo:
        candidate = _validate_file_id(file_id)
        self._request_json(
            f"https://www.googleapis.com/drive/v3/files/{quote(candidate)}?" + urlencode({"fields": "id,name,mimeType,size"}),
            method="PATCH",
            headers={"Content-Type": "application/json; charset=UTF-8"},
            body=json.dumps({"name": filename}, ensure_ascii=False).encode("utf-8"),
        )
        return self.inspect_media(candidate)
