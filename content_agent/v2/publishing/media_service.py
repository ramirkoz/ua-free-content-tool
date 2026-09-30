from __future__ import annotations

from ...google_drive import GoogleDriveClient


class GoogleDriveMediaService:
    """Media/storage boundary. Google Drive is deliberately not a publisher."""

    platform = "google_drive"

    def __init__(self, config) -> None:
        self.config = config

    def _client(self) -> GoogleDriveClient:
        return GoogleDriveClient(
            self.config.google_client_id,
            self.config.google_client_secret,
            self.config.google_refresh_token,
        )

    def inspect(self, file_id: str):
        return self._client().inspect_media(str(file_id or "").strip())

    def download(self, file_id: str):
        info = self.inspect(file_id)
        return self._client().download_media(info)

    def ensure_public_for_threads(self, file_id: str) -> str:
        client = self._client()
        info = client.inspect_media(str(file_id or "").strip())
        return client.ensure_public_for_threads(info)
