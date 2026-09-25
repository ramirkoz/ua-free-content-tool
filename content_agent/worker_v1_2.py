from __future__ import annotations

import logging
from typing import Any

from .google_drive import DriveMediaInfo, GoogleDriveClient, GoogleDriveError
from .managed_media_registry import ManagedMediaRegistry, ManagedMediaRegistryError
from .worker import PublicationWorker

logger = logging.getLogger("content_agent.worker")


class ManagedCleanupDriveProxy:
    """Delegate Drive operations while limiting permanent deletion to managed files."""

    def __init__(self, client: GoogleDriveClient, registry: ManagedMediaRegistry):
        self.client = client
        self.registry = registry
        self._temporary_permissions: dict[str, str] = {}

    def __getattr__(self, name: str) -> Any:
        return getattr(self.client, name)

    def ensure_public_for_threads(self, info: DriveMediaInfo) -> str:
        permission_id = self.client.ensure_public_for_threads(info)
        if permission_id:
            self._temporary_permissions[info.file_id] = permission_id
        return permission_id

    def remove_permission(self, file_id: str, permission_id: str) -> None:
        self.client.remove_permission(file_id, permission_id)
        if self._temporary_permissions.get(file_id) == permission_id:
            self._temporary_permissions.pop(file_id, None)

    def delete_file(self, file_id: str) -> None:
        managed = False
        try:
            managed = self.registry.is_managed(file_id)
        except ManagedMediaRegistryError as exc:
            logger.error(
                "Managed-media registry could not be read; permanent Drive deletion was blocked: %s",
                exc,
            )

        if managed:
            self.client.delete_file(file_id)
            try:
                self.registry.remove(file_id)
            except ManagedMediaRegistryError as exc:
                logger.warning("Managed-media registry cleanup failed after Drive deletion: %s", exc)
            self._temporary_permissions.pop(file_id, None)
            return

        permission_id = self._temporary_permissions.pop(file_id, "")
        if permission_id:
            self.client.remove_permission(file_id, permission_id)
        logger.info(
            "Drive file %s was detached from the publication but not deleted because it is not managed by the application.",
            file_id,
        )


class ManagedMediaPublicationWorker(PublicationWorker):
    """v1.2 worker that never permanently deletes an unregistered Drive file."""

    def __init__(self, *args: Any, managed_media_registry: ManagedMediaRegistry | None = None, **kwargs: Any):
        self.managed_media_registry = managed_media_registry or ManagedMediaRegistry()
        super().__init__(*args, **kwargs)

    def _drive_client(self) -> ManagedCleanupDriveProxy:
        config = self.factory.config
        client = GoogleDriveClient(
            config.google_client_id,
            config.google_client_secret,
            config.google_refresh_token,
        )
        return ManagedCleanupDriveProxy(client, self.managed_media_registry)
