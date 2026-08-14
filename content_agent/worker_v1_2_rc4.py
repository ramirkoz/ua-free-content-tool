from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from .google_drive import DriveMediaInfo, GoogleDriveError
from .media_gallery_v1_2_rc4 import ImageGalleryPayload
from .models import MediaPayload
from .multi_image_store_v1_2_rc4 import MultiImageStore
from .worker import WorkerResult
from .worker_v1_2 import ManagedCleanupDriveProxy, ManagedMediaPublicationWorker

logger = logging.getLogger("content_agent.worker.rc4")


class Rc4CleanupDriveProxy(ManagedCleanupDriveProxy):
    def __init__(self, client, registry, image_store: MultiImageStore):
        super().__init__(client, registry)
        self.image_store = image_store

    def ensure_public_for_threads(self, info: DriveMediaInfo) -> str:
        existing = self._temporary_permissions.get(info.file_id, "")
        if existing:
            return existing
        return super().ensure_public_for_threads(info)

    def cleanup_permissions(self) -> None:
        for file_id, permission_id in list(self._temporary_permissions.items()):
            try:
                self.client.remove_permission(file_id, permission_id)
            except GoogleDriveError as exc:
                logger.warning("RC4 temporary media permission cleanup failed: %s", exc)
            finally:
                self._temporary_permissions.pop(file_id, None)

    def delete_file(self, file_id: str) -> None:
        details = self.registry.details(file_id)
        group_id = int(details.get("group_id") or 0) if isinstance(details, dict) else 0
        gallery = self.image_store.list_group(group_id) if group_id else []
        if gallery and any(item.file_id == file_id for item in gallery):
            for item in gallery:
                super().delete_file(item.file_id)
            self.image_store.clear_group(group_id)
            return
        super().delete_file(file_id)


class Rc4PublicationWorker(ManagedMediaPublicationWorker):
    """RC4 worker: gallery media plus a five-minute gap between overdue news batches."""

    CATCHUP_GAP_SECONDS = 5 * 60

    def __init__(self, *args: Any, image_store: MultiImageStore | None = None, **kwargs: Any):
        self.image_store = image_store or MultiImageStore()
        self._active_drive_proxy: Rc4CleanupDriveProxy | None = None
        self._catchup_not_before = 0.0
        super().__init__(*args, **kwargs)

    def _drive_client(self) -> Rc4CleanupDriveProxy:
        from .google_drive import GoogleDriveClient

        config = self.factory.config
        proxy = Rc4CleanupDriveProxy(
            GoogleDriveClient(config.google_client_id, config.google_client_secret, config.google_refresh_token),
            self.managed_media_registry,
            self.image_store,
        )
        self._active_drive_proxy = proxy
        return proxy

    def _load_media(self, batch_article_id: int):
        group_id = self.database.group_id_for_article(batch_article_id)
        group = self.database.get_group(group_id)
        if not group.media_file_id:
            return None, None, group_id, None

        client = self._drive_client()
        gallery_rows = self.image_store.list_group(group_id)
        if len(gallery_rows) >= 2:
            payloads: list[MediaPayload] = []
            infos: list[DriveMediaInfo] = []
            for stored in gallery_rows:
                info = client.inspect_media(stored.file_id)
                if info.kind != "image":
                    raise GoogleDriveError("RC4-галерея містить не зображення. Приберіть проблемний файл у редакторі.")
                client.ensure_public_for_threads(info)
                data = client.download_media(info)
                infos.append(info)
                payloads.append(
                    MediaPayload(
                        file_id=info.file_id,
                        name=info.name,
                        kind="image",
                        mime_type=info.mime_type,
                        data=data,
                        public_url=info.public_url,
                    )
                )
            return ImageGalleryPayload(payloads), client, group_id, infos[0]

        info = client.inspect_media(group.media_file_id)
        client.ensure_public_for_threads(info)
        data = client.download_media(info)
        return (
            MediaPayload(
                file_id=info.file_id,
                name=info.name,
                kind=info.kind,
                mime_type=info.mime_type,
                data=data,
                public_url=info.public_url,
            ),
            client,
            group_id,
            info,
        )

    def _due_backlog_exists(self) -> bool:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.database.connect() as db:
            row = db.execute(
                """
                SELECT 1 FROM publication_batches
                WHERE julianday(scheduled_at)<=julianday(?)
                  AND (status='pending'
                       OR (status='in_progress' AND (lease_until IS NULL OR julianday(lease_until)<julianday(?))))
                LIMIT 1
                """,
                (now, now),
            ).fetchone()
        return row is not None

    def run_once(self) -> WorkerResult:
        remaining = self._catchup_not_before - time.monotonic()
        if remaining > 0:
            return WorkerResult(
                claimed=False,
                busy=True,
                pause_reason=f"Наступна прострочена новина не раніше ніж через {max(1, int(remaining))} с.",
            )
        return super().run_once()

    def _run_once_locked(self) -> WorkerResult:
        try:
            result = super()._run_once_locked()
            if result.completed and result.sent_targets > 0 and self._due_backlog_exists():
                self._catchup_not_before = time.monotonic() + self.CATCHUP_GAP_SECONDS
                self._notify("Є прострочені новини. Наступний пакет буде відправлено не раніше ніж через 5 хвилин.")
            return result
        finally:
            proxy = self._active_drive_proxy
            self._active_drive_proxy = None
            if proxy is not None:
                proxy.cleanup_permissions()
