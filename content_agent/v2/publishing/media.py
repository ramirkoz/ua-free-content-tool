from __future__ import annotations

from typing import Any


class GoogleDriveMediaService:
    """Google Drive media/storage boundary.

    Drive deliberately does not implement PlatformAdapter and therefore cannot be
    resolved by DestinationRegistry as a publication target.
    """

    def __init__(self, config: Any) -> None:
        self.config = config

    def ready(self) -> bool:
        try:
            return bool(self.config.platform_ready("google_drive"))
        except Exception:
            return bool(
                getattr(self.config, "google_client_id", "")
                and getattr(self.config, "google_client_secret", "")
                and getattr(self.config, "google_refresh_token", "")
            )


__all__ = ["GoogleDriveMediaService"]
