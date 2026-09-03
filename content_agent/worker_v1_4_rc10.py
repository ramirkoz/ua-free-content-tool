from __future__ import annotations

import logging

from .worker_v1_4 import V14PublicationWorker


logger = logging.getLogger("content_agent.worker.v14_rc10")


class Rc10PublicationWorker(V14PublicationWorker):
    """Publish-now batches jump ahead of the normal scheduler without moving it."""

    def run_once(self):
        # RC4 normally inserts a five-minute pause between overdue packages. A
        # manual publish-now request is an explicit operator action and must not
        # sit behind that catch-up throttle.
        try:
            try:
                if self.database.has_pending_immediate():
                    self._catchup_not_before = 0.0
            except Exception:
                logger.debug("Could not inspect immediate publication backlog.", exc_info=True)
            return super().run_once()
        finally:
            # Immediate batches use an old priority timestamp only while pending.
            # Once terminal, normalize it to the real click time so History shows
            # the publication honestly even after a handled worker exception.
            try:
                self.database._repair_terminal_immediate_timestamps()
            except Exception:
                logger.debug("Could not normalize immediate publication timestamps.", exc_info=True)

    def _run_once_locked(self):
        result = super()._run_once_locked()
        if result.batch_id is not None:
            try:
                if self.database.is_immediate_batch(int(result.batch_id)):
                    # Multiple destinations selected for «publish now» are still
                    # separate safe single-target batches. Do not insert the normal
                    # five-minute overdue-backlog pause between them.
                    self._catchup_not_before = 0.0
                    self.database.finalize_immediate_timestamp(int(result.batch_id))
                    logger.info("RC10 immediate batch completed batch=%s; catch-up throttle bypassed", result.batch_id)
            except Exception:
                logger.debug("Could not finalize immediate worker pacing.", exc_info=True)
        return result
