from __future__ import annotations

import logging

from .google_drive import GoogleDriveClient
from .worker import WorkerResult
from .worker_v1_2_rc4 import Rc4CleanupDriveProxy, Rc4PublicationWorker


logger = logging.getLogger("content_agent.worker.v14")


class V14CleanupDriveProxy(Rc4CleanupDriveProxy):
    """Do not delete shared media while another destination still needs it."""

    def __init__(self, client, registry, image_store, database):
        super().__init__(client, registry, image_store)
        self.database = database

    def delete_file(self, file_id: str) -> None:
        try:
            details = self.registry.details(file_id)
        except Exception:
            details = {}
        group_id = int(details.get("group_id") or 0) if isinstance(details, dict) else 0
        if group_id and not self.database.media_cleanup_ready_for_group(group_id):
            logger.info(
                "Drive media %s kept for group=%s because another destination is still active.",
                file_id,
                group_id,
            )
            return
        super().delete_file(file_id)


class V14PublicationWorker(Rc4PublicationWorker):
    """One destination per batch, no automatic re-publication after an error."""

    def __init__(self, *args, **kwargs):
        kwargs["max_automatic_attempts"] = 1
        super().__init__(*args, **kwargs)

    @staticmethod
    def _is_meta_platform(platform: str) -> bool:
        value = str(platform or "")
        return value.startswith("facebook:") or value.startswith("instagram:") or value == "threads"

    def _drive_client(self) -> V14CleanupDriveProxy:
        config = self.factory.config
        proxy = V14CleanupDriveProxy(
            GoogleDriveClient(
                config.google_client_id,
                config.google_client_secret,
                config.google_refresh_token,
            ),
            self.managed_media_registry,
            self.image_store,
            self.database,
        )
        self._active_drive_proxy = proxy
        return proxy

    def _cleanup_terminal_group_media(self, batch_id: int) -> None:
        try:
            group_id = self.database.group_id_for_batch(batch_id)
            if not self.database.media_cleanup_ready_for_group(group_id):
                return
            group = self.database.get_group(group_id)
            if not group.media_file_id:
                return
            client = self._drive_client()
            client.delete_file(group.media_file_id)
            self.database.clear_group_media(group_id)
            logger.info("v1.4 terminal group media cleaned group=%s batch=%s", group_id, batch_id)
        except Exception as exc:
            logger.warning("v1.4 terminal group media cleanup deferred batch=%s: %s", batch_id, exc)
            try:
                with self.database.connect() as db:
                    db.execute(
                        "UPDATE publication_batches SET cleanup_error=?,updated_at=datetime('now') WHERE id=?",
                        (str(exc)[:1000], int(batch_id)),
                    )
            except Exception:
                logger.debug("Could not persist terminal cleanup error.", exc_info=True)

    def _run_once_locked(self) -> WorkerResult:
        result = super()._run_once_locked()
        if result.batch_id is not None:
            # Successful last destination is normally cleaned by the inherited
            # worker. Failed last destination also reaches this point now because
            # v1.4 treats the error as terminal history instead of a retry queue.
            self._cleanup_terminal_group_media(int(result.batch_id))
        return result
