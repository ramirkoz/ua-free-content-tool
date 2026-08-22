from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlencode

from .google_drive import DriveMediaInfo, GoogleDriveClient, GoogleDriveError, _validate_file_id
from .media_candidates import ValidatedMedia, validate_media_bytes
from .network import NetworkError, fetch_url

DEFAULT_MEDIA_FOLDER_NAME = "UA FREE Content Tool Media"
_FOLDER_MIME = "application/vnd.google-apps.folder"
_SAFE_FILENAME_RE = re.compile(r"[^0-9A-Za-zА-Яа-яІіЇїЄєҐґ._ -]+")
_EXTENSION_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
}


@dataclass(frozen=True, slots=True)
class ManagedMediaUpload:
    folder_id: str
    info: DriveMediaInfo
    managed_by_application: bool = True


def safe_media_filename(value: str, mime_type: str) -> str:
    raw = Path(str(value or "media")).name.strip().replace("\x00", "")
    cleaned = _SAFE_FILENAME_RE.sub("_", raw).strip(" ._") or "media"
    extension = _EXTENSION_BY_MIME.get(mime_type.casefold(), "")
    current_suffix = Path(cleaned).suffix.casefold()
    if extension and current_suffix != extension:
        cleaned = Path(cleaned).stem.strip(" ._") or "media"
        cleaned += extension
    if len(cleaned) > 160:
        suffix = Path(cleaned).suffix
        cleaned = cleaned[: max(1, 160 - len(suffix))].rstrip(" ._") + suffix
    return cleaned


def validate_local_media(path: Path) -> tuple[ValidatedMedia, str]:
    source = Path(path)
    if not source.is_file():
        raise GoogleDriveError("Вибраний медіафайл не існує або недоступний.")
    try:
        data = source.read_bytes()
    except OSError as exc:
        raise GoogleDriveError("Не вдалося прочитати вибраний медіафайл.") from exc
    try:
        source_url = source.resolve().as_uri()
    except (ValueError, OSError):
        source_url = str(source)
    media = validate_media_bytes(data, source_url=source_url)
    return media, safe_media_filename(source.name, media.mime_type)


class ManagedGoogleDriveClient(GoogleDriveClient):
    """Google Drive upload operations for files created by this application."""

    def _request_json(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        timeout: float = 60,
    ) -> dict[str, object]:
        request_headers = {
            "Authorization": f"Bearer {self._token()}",
            "Accept": "application/json",
        }
        if headers:
            request_headers.update(headers)
        try:
            response = fetch_url(
                url,
                method=method,
                headers=request_headers,
                body=body,
                max_bytes=2 * 1024 * 1024,
                allowed_content_types={"application/json"},
                timeout=timeout,
                max_redirects=0,
                allow_http_errors=True,
            )
        except NetworkError as exc:
            raise GoogleDriveError(str(exc)) from exc
        payload = response.json() if response.body else {}
        if response.status >= 400 or not isinstance(payload, dict):
            message = "Google Drive відхилив запит."
            if isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, dict):
                    message = str(error.get("message") or error.get("status") or message)
                elif error:
                    message = str(error)
            raise GoogleDriveError(message)
        return payload

    def _inspect_folder(self, folder_id: str) -> str:
        candidate = _validate_file_id(folder_id)
        payload = self._request_json(
            f"https://www.googleapis.com/drive/v3/files/{quote(candidate)}?"
            + urlencode({"fields": "id,name,mimeType,trashed", "supportsAllDrives": "true"})
        )
        if payload.get("trashed") or str(payload.get("mimeType") or "") != _FOLDER_MIME:
            raise GoogleDriveError("Збережена папка медіа Google Drive недоступна або більше не є папкою.")
        return str(payload.get("id") or candidate)

    def ensure_media_folder(
        self,
        folder_id: str = "",
        folder_name: str = DEFAULT_MEDIA_FOLDER_NAME,
    ) -> str:
        if folder_id.strip():
            try:
                return self._inspect_folder(folder_id)
            except GoogleDriveError:
                pass

        escaped_name = folder_name.replace("'", "\\'")
        query = (
            f"name = '{escaped_name}' and mimeType = '{_FOLDER_MIME}' and trashed = false "
            "and appProperties has { key='uaFreePurpose' and value='publication-media-folder' }"
        )
        payload = self._request_json(
            "https://www.googleapis.com/drive/v3/files?"
            + urlencode(
                {
                    "q": query,
                    "fields": "files(id,name)",
                    "spaces": "drive",
                    "pageSize": "10",
                }
            )
        )
        files = payload.get("files")
        if isinstance(files, list):
            for item in files:
                if isinstance(item, dict) and item.get("id"):
                    return _validate_file_id(str(item["id"]))

        metadata = {
            "name": folder_name,
            "mimeType": _FOLDER_MIME,
            "appProperties": {
                "uaFreeManaged": "1",
                "uaFreePurpose": "publication-media-folder",
            },
        }
        created = self._request_json(
            "https://www.googleapis.com/drive/v3/files?" + urlencode({"fields": "id,name"}),
            method="POST",
            headers={"Content-Type": "application/json; charset=UTF-8"},
            body=json.dumps(metadata, ensure_ascii=False).encode("utf-8"),
        )
        new_id = str(created.get("id") or "")
        if not new_id:
            raise GoogleDriveError("Google Drive створив папку, але не повернув її ID.")
        return _validate_file_id(new_id)

    def upload_validated_media(
        self,
        media: ValidatedMedia,
        filename: str,
        *,
        folder_id: str = "",
        folder_name: str = DEFAULT_MEDIA_FOLDER_NAME,
    ) -> ManagedMediaUpload:
        target_folder = self.ensure_media_folder(folder_id, folder_name)
        safe_name = safe_media_filename(filename, media.mime_type)
        boundary = "ua_free_" + secrets.token_hex(18)
        metadata = {
            "name": safe_name,
            "parents": [target_folder],
            "appProperties": {
                "uaFreeManaged": "1",
                "uaFreePurpose": "publication-media",
            },
        }
        metadata_bytes = json.dumps(metadata, ensure_ascii=False).encode("utf-8")
        body = b"".join(
            (
                f"--{boundary}\r\n".encode("ascii"),
                b"Content-Type: application/json; charset=UTF-8\r\n\r\n",
                metadata_bytes,
                b"\r\n",
                f"--{boundary}\r\n".encode("ascii"),
                f"Content-Type: {media.mime_type}\r\n\r\n".encode("ascii"),
                media.data,
                b"\r\n",
                f"--{boundary}--\r\n".encode("ascii"),
            )
        )
        uploaded = self._request_json(
            "https://www.googleapis.com/upload/drive/v3/files?"
            + urlencode({"uploadType": "multipart", "fields": "id,name,mimeType,size"}),
            method="POST",
            headers={"Content-Type": f"multipart/related; boundary={boundary}"},
            body=body,
            timeout=240,
        )
        file_id = str(uploaded.get("id") or "")
        if not file_id:
            raise GoogleDriveError("Google Drive завантажив файл, але не повернув його ID.")
        info = self.inspect_media(file_id)
        if info.mime_type != media.mime_type or info.size != media.size:
            try:
                self.delete_file(file_id)
            except GoogleDriveError:
                pass
            raise GoogleDriveError("Google Drive повернув файл з іншим типом або розміром; завантаження скасовано.")
        return ManagedMediaUpload(folder_id=target_folder, info=info)
