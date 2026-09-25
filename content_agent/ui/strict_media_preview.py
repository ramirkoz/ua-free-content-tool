from __future__ import annotations

from ..google_drive import GoogleDriveError
from ..strict_media_drive import StrictManagedGoogleDriveClient
from .media_preview import MediaPreviewMixin


class StrictMediaPreviewMixin(MediaPreviewMixin):
    """Use the strict decodable-image Drive client for every editor upload path."""

    def _managed_drive_client(self) -> StrictManagedGoogleDriveClient:
        if not self.config.platform_ready("google_drive"):
            raise GoogleDriveError("Спочатку підключіть Google Drive у налаштуваннях.")
        return StrictManagedGoogleDriveClient(
            self.config.google_client_id,
            self.config.google_client_secret,
            self.config.google_refresh_token,
        )
