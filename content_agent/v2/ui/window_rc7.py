from __future__ import annotations

import json
from urllib.parse import quote, urlencode

from ...google_drive import DriveMediaInfo, GoogleDriveError, _validate_file_id
from ...managed_media_drive import ManagedGoogleDriveClient, ManagedMediaUpload
from ...media_candidates import ValidatedMedia
from ...readable_media_names import readable_post_media_filename
from ...ui.media_workflow import format_media_size
from .window import MainWindow as Rc6MainWindow


class _ReadableMediaDriveClient(ManagedGoogleDriveClient):
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        *,
        post_title: str = "",
        group_id: int = 0,
    ) -> None:
        super().__init__(client_id, client_secret, refresh_token)
        self._post_title = str(post_title or "")
        self._group_id = int(group_id or 0)

    def _publication_filename(self, mime_type: str) -> str:
        return readable_post_media_filename(
            self._post_title,
            self._group_id,
            mime_type,
        )

    def upload_validated_media(
        self,
        media: ValidatedMedia,
        filename: str,
        *,
        folder_id: str = "",
        folder_name: str = "UA FREE Content Tool Media",
    ) -> ManagedMediaUpload:
        del filename
        return super().upload_validated_media(
            media,
            self._publication_filename(media.mime_type),
            folder_id=folder_id,
            folder_name=folder_name,
        )

    def rename_media_file(self, file_id: str, filename: str) -> DriveMediaInfo:
        candidate = _validate_file_id(file_id)
        self._request_json(
            f"https://www.googleapis.com/drive/v3/files/{quote(candidate)}?"
            + urlencode({"fields": "id,name,mimeType,size"}),
            method="PATCH",
            headers={"Content-Type": "application/json; charset=UTF-8"},
            body=json.dumps({"name": filename}, ensure_ascii=False).encode("utf-8"),
        )
        return self.inspect_media(candidate)


class MainWindow(Rc6MainWindow):
    """RC7: readable media filenames for Drive and external platform uploads."""

    VERSION_LABEL = "2.0.0-rc7"

    def _apply_v2_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v2.0.0-rc7")

    def _media_name_context(self) -> tuple[int, str]:
        group_id = int(getattr(self, "current_group_id", 0) or 0)
        title = ""
        headline_var = getattr(self, "headline_var", None)
        if headline_var is not None:
            try:
                title = str(headline_var.get() or "").strip()
            except Exception:
                title = ""
        if not title and group_id:
            try:
                group = self.db.get_group(group_id)
                title = str(group.headline or group.canonical_title or "").strip()
            except Exception:
                title = ""
        return group_id, title

    def _managed_drive_client(self) -> ManagedGoogleDriveClient:
        if not self.config.platform_ready("google_drive"):
            raise GoogleDriveError("Спочатку підключіть Google Drive у налаштуваннях.")
        group_id, title = self._media_name_context()
        return _ReadableMediaDriveClient(
            self.config.google_client_id,
            self.config.google_client_secret,
            self.config.google_refresh_token,
            post_title=title,
            group_id=group_id,
        )

    def load_group(self, group_id: int) -> None:
        super().load_group(group_id)
        try:
            group = self.db.get_group(group_id)
        except Exception:
            return
        if not group.media_file_id or not group.media_mime:
            return
        desired = readable_post_media_filename(
            str(group.headline or group.canonical_title or ""),
            group_id,
            group.media_mime,
        )
        if str(group.media_name or "") == desired:
            return
        if not self.config.platform_ready("google_drive"):
            return

        file_id = str(group.media_file_id)

        def action() -> object:
            client = self._managed_drive_client()
            if not isinstance(client, _ReadableMediaDriveClient):
                raise GoogleDriveError("Не вдалося підготувати кероване медіа Google Drive.")
            return client.rename_media_file(file_id, desired)

        def success(result: object) -> None:
            if not isinstance(result, DriveMediaInfo):
                return
            drive_url = f"https://drive.google.com/file/d/{result.file_id}/view"
            self.db.set_group_media(
                group_id,
                drive_url=drive_url,
                file_id=result.file_id,
                name=result.name,
                kind=result.kind,
                mime=result.mime_type,
                size=result.size,
            )
            if getattr(self, "current_group_id", None) != group_id:
                return
            self.media_url_var.set(drive_url)
            self.media_status_var.set(
                f"Медіа готове ✓ {result.name} · {result.kind.upper()} · "
                f"{format_media_size(result.size)} · Google Drive: перевірено ✓"
            )

        self.run_async(
            action,
            success,
            label="Надаю медіафайлу зрозумілу назву",
            done_label="Назву медіафайлу оновлено",
        )
