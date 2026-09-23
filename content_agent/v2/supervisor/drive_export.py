from __future__ import annotations

import json
import mimetypes
import secrets
from pathlib import Path
from urllib.parse import quote, urlencode

from ...google_drive import GoogleDriveError, refresh_access_token
from ...network import fetch_url


class SupervisorDriveExporter:
    """Small Drive client for diagnostics and narrow supervisor control.

    It reuses the already-authorized Google Drive account, never changes file
    permissions and never executes arbitrary remote content.  Control consumers
    may read JSON from the dedicated per-instance CONTROL folder only.
    """

    def __init__(self, config) -> None:
        self.client_id = str(getattr(config, "google_client_id", "") or "").strip()
        self.client_secret = str(getattr(config, "google_client_secret", "") or "").strip()
        self.refresh_token = str(getattr(config, "google_refresh_token", "") or "").strip()
        self._access_token = ""
        if not self.client_id or not self.refresh_token:
            raise GoogleDriveError("Google Drive не підключено.")

    def _token(self) -> str:
        if not self._access_token:
            self._access_token = refresh_access_token(
                self.client_id, self.client_secret, self.refresh_token, timeout=20
            )
        return self._access_token

    def _json_request(self, url: str, *, method: str = "GET", payload: dict | None = None) -> dict:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        for attempt in range(2):
            headers = {"Authorization": f"Bearer {self._token()}", "Accept": "application/json"}
            if body is not None:
                headers["Content-Type"] = "application/json; charset=utf-8"
            response = fetch_url(
                url,
                method=method,
                headers=headers,
                body=body,
                max_bytes=3 * 1024 * 1024,
                allowed_content_types={"application/json"},
                timeout=30,
                max_redirects=0,
                allow_http_errors=True,
            )
            if response.status == 401 and attempt == 0:
                # Access tokens expire. RC22 cached one forever, so the first 401
                # permanently silenced the heartbeat despite a valid refresh token.
                self._access_token = ""
                continue
            data = response.json() if response.body else {}
            if response.status >= 400 or not isinstance(data, dict):
                raise GoogleDriveError(f"Google Drive API HTTP {response.status}.")
            return data
        raise GoogleDriveError("Google Drive API authentication retry failed.")

    @staticmethod
    def _escape_q(value: str) -> str:
        return str(value).replace("\\", "\\\\").replace("'", "\\'")

    def find_child(self, parent_id: str, name: str, *, folder: bool | None = None) -> str:
        parts = [
            f"name='{self._escape_q(name)}'",
            f"'{self._escape_q(parent_id)}' in parents",
            "trashed=false",
        ]
        if folder is True:
            parts.append("mimeType='application/vnd.google-apps.folder'")
        elif folder is False:
            parts.append("mimeType!='application/vnd.google-apps.folder'")
        url = "https://www.googleapis.com/drive/v3/files?" + urlencode({
            "q": " and ".join(parts),
            "fields": "files(id,name,mimeType,modifiedTime,size)",
            "pageSize": "10",
            "orderBy": "modifiedTime desc",
            "spaces": "drive",
        })
        data = self._json_request(url)
        files = data.get("files")
        if isinstance(files, list) and files:
            item = files[0]
            if isinstance(item, dict):
                return str(item.get("id") or "")
        return ""

    def ensure_folder(self, name: str, parent_id: str = "root") -> str:
        found = self.find_child(parent_id, name, folder=True)
        if found:
            return found
        data = self._json_request(
            "https://www.googleapis.com/drive/v3/files?fields=id,name",
            method="POST",
            payload={
                "name": name,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [parent_id],
            },
        )
        folder_id = str(data.get("id") or "")
        if not folder_id:
            raise GoogleDriveError(f"Не вдалося створити папку {name}.")
        return folder_id

    def download_bytes(self, file_id: str, *, max_bytes: int = 512 * 1024) -> bytes:
        candidate = str(file_id or "").strip()
        if not candidate or len(candidate) > 256:
            raise GoogleDriveError("Неправильний Google Drive file id.")
        for attempt in range(2):
            response = fetch_url(
                f"https://www.googleapis.com/drive/v3/files/{quote(candidate, safe='')}?alt=media",
                method="GET",
                headers={"Authorization": f"Bearer {self._token()}", "Accept": "application/json, text/plain, */*"},
                max_bytes=max(1024, int(max_bytes)),
                allowed_content_types=None,
                timeout=30,
                max_redirects=0,
                allow_http_errors=True,
            )
            if response.status == 401 and attempt == 0:
                self._access_token = ""
                continue
            if response.status >= 400:
                raise GoogleDriveError(f"Не вдалося прочитати файл Google Drive: HTTP {response.status}.")
            return bytes(response.body)
        raise GoogleDriveError("Не вдалося оновити Google Drive access token.")

    def download_json(self, file_id: str, *, max_bytes: int = 256 * 1024) -> dict:
        raw = self.download_bytes(file_id, max_bytes=max_bytes)
        try:
            value = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise GoogleDriveError("Керуючий файл Google Drive не є валідним JSON.") from exc
        if not isinstance(value, dict):
            raise GoogleDriveError("Керуючий JSON повинен бути об'єктом.")
        return value

    def upload_bytes(self, name: str, data: bytes, parent_id: str, *, mime_type: str = "application/octet-stream", replace: bool = False) -> str:
        existing = self.find_child(parent_id, name, folder=False) if replace else ""
        boundary = "ua_free_" + secrets.token_hex(12)
        metadata = {"name": name}
        if not existing:
            metadata["parents"] = [parent_id]
        body = (
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
            + json.dumps(metadata, ensure_ascii=False)
            + f"\r\n--{boundary}\r\nContent-Type: {mime_type}\r\n\r\n"
        ).encode("utf-8") + data + f"\r\n--{boundary}--\r\n".encode("utf-8")
        if existing:
            url = f"https://www.googleapis.com/upload/drive/v3/files/{quote(existing)}?uploadType=multipart&fields=id,name,webViewLink"
            method = "PATCH"
        else:
            url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,name,webViewLink"
            method = "POST"
        for attempt in range(2):
            response = fetch_url(
                url,
                method=method,
                headers={
                    "Authorization": f"Bearer {self._token()}",
                    "Accept": "application/json",
                    "Content-Type": f"multipart/related; boundary={boundary}",
                },
                body=body,
                max_bytes=3 * 1024 * 1024,
                allowed_content_types={"application/json"},
                timeout=45,
                max_redirects=0,
                allow_http_errors=True,
            )
            if response.status == 401 and attempt == 0:
                self._access_token = ""
                continue
            payload = response.json() if response.body else {}
            if response.status >= 400 or not isinstance(payload, dict):
                raise GoogleDriveError(f"Не вдалося вивантажити {name}: HTTP {response.status}.")
            file_id = str(payload.get("id") or existing)
            if not file_id:
                raise GoogleDriveError(f"Google Drive не повернув ID для {name}.")
            return file_id
        raise GoogleDriveError(f"Не вдалося оновити Google Drive access token для {name}.")

    def upload_json(self, name: str, payload: dict, parent_id: str, *, replace: bool = True) -> str:
        return self.upload_bytes(
            name,
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"),
            parent_id,
            mime_type="application/json",
            replace=replace,
        )

    def upload_path(self, path: Path, parent_id: str, *, replace: bool = False) -> str:
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return self.upload_bytes(path.name, path.read_bytes(), parent_id, mime_type=mime, replace=replace)
