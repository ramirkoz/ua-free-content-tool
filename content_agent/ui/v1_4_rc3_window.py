from __future__ import annotations

import threading

from ..destinations_v1_4 import instagram_token_for, load_instagram_catalog
from ..worker_v1_4 import V14PublicationWorker
from .v1_4_rc2_window import MainWindow as Rc2MainWindow


def reconcile_instagram_runtime(config) -> bool:
    """Repair a stale RC2 enabled flag from the discovered Facebook-backed catalog.

    RC2 could persist the Instagram catalog and Page tokens while leaving the old
    single-profile ``instagram_enabled`` flag false. The editor then displayed the
    discovered accounts but disabled their checkboxes. The catalog plus an actual
    Page Access Token is the authoritative runtime signal for Facebook Login mode.
    """

    rows = load_instagram_catalog()
    ready = any(
        row.auth_mode == "facebook_login" and bool(instagram_token_for(config, row))
        for row in rows
    )
    if ready:
        config.instagram_enabled = True
    return ready


class Rc3PublicationWorker(V14PublicationWorker):
    """v1.4 RC3 worker without the inherited RC4 catch-up throttles."""

    CATCHUP_GAP_SECONDS = 0
    INTER_TARGET_DELAY_SECONDS = 0.0

    def __init__(self, *args, **kwargs):
        kwargs["inter_target_delay_seconds"] = self.INTER_TARGET_DELAY_SECONDS
        super().__init__(*args, **kwargs)
        self._catchup_not_before = 0.0


class MainWindow(Rc2MainWindow):
    """v1.4.0-rc3: active Instagram destinations and immediate independent queues."""

    VERSION_LABEL = "1.4.0-rc3"

    def __init__(self, root, database, config) -> None:
        # Reconcile before the inherited editor builds its target checkboxes.
        reconcile_instagram_runtime(config)
        super().__init__(root, database, config)

        # RC4 deliberately throttled overdue batches by five minutes. v1.4 made
        # every destination its own batch, so inheriting that throttle multiplied
        # one material across many accounts into an hour-long publication train.
        # Replace the not-yet-started worker before the startup gate fires.
        self.worker = Rc3PublicationWorker(
            self.db,
            self.publisher_factory,
            inter_target_delay_seconds=0.0,
            progress_callback=self._publication_progress_from_worker,
            result_callback=self._publication_result_from_worker,
            managed_media_registry=self.managed_media_registry,
            image_store=self.multi_image_store,
        )
        self.worker_thread = threading.Thread(
            target=self.worker.run_loop,
            args=(self.stop_event,),
            name="publication-worker-v14-rc3",
            daemon=True,
        )

    def _apply_v14_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v1.4.0-rc3")
