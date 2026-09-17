from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path

from ...database import _iso, redact_secrets
from ...paths import data_dir
from .compat import Database as CompatDatabase

logger = logging.getLogger("content_agent.v2.storage.reliable")


class Database(CompatDatabase):
    """RC9 storage boundary with an external-publication success journal.

    A platform can accept a post a few milliseconds before the local SQLite update.
    If that update fails, treating the target as failed is dangerous because the next
    retry can publish the same post again. RC9 writes a small durable receipt before
    committing `sent`. Pending receipts are reconciled before another queue claim.
    """

    _receipt_lock = threading.RLock()

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._uncertain_external_targets: set[int] = set()
        self.reconcile_external_successes(best_effort=True)

    @staticmethod
    def _receipt_dir() -> Path:
        path = data_dir() / "publication_recovery"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def _receipt_path(cls, target_id: int) -> Path:
        return cls._receipt_dir() / f"target_{int(target_id)}.json"

    def _write_receipt(self, target_id: int, remote_id: str | None) -> Path:
        target_id = int(target_id)
        path = self._receipt_path(target_id)
        payload = {
            "schema": "ua-free-content-tool-publication-receipt-v1",
            "target_id": target_id,
            "remote_id": str(remote_id or ""),
            "accepted_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        temp = path.with_suffix(".tmp")
        with self._receipt_lock:
            temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(path)
        return path

    @classmethod
    def _read_receipt(cls, path: Path) -> tuple[int, str] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return None
            if str(payload.get("schema") or "") != "ua-free-content-tool-publication-receipt-v1":
                return None
            target_id = int(payload.get("target_id") or 0)
            if target_id <= 0:
                return None
            return target_id, str(payload.get("remote_id") or "")
        except Exception:
            return None

    @classmethod
    def _pending_receipt_ids(cls) -> set[int]:
        out: set[int] = set()
        try:
            paths = list(cls._receipt_dir().glob("target_*.json"))
        except OSError:
            return out
        for path in paths:
            parsed = cls._read_receipt(path)
            if parsed is not None:
                out.add(parsed[0])
        return out

    def reconcile_external_successes(self, *, best_effort: bool = False) -> int:
        reconciled = 0
        try:
            paths = sorted(self._receipt_dir().glob("target_*.json"))
        except OSError:
            if best_effort:
                return 0
            raise
        for path in paths:
            parsed = self._read_receipt(path)
            if parsed is None:
                logger.warning("Ignoring malformed publication recovery receipt: %s", path.name)
                continue
            target_id, remote_id = parsed
            try:
                # Bypass this class' journaling override: the receipt already exists.
                super().mark_target_sent(target_id, remote_id or None)
            except Exception:
                if best_effort:
                    logger.warning("Publication receipt still pending: target=%s", target_id, exc_info=True)
                    continue
                raise
            try:
                path.unlink(missing_ok=True)
            except OSError:
                # A leftover receipt is idempotent. It will simply re-assert sent next time.
                logger.warning("Could not remove reconciled publication receipt: %s", path.name)
            self._uncertain_external_targets.discard(target_id)
            reconciled += 1
            logger.info("Reconciled external publication success target=%s remote_id=%s", target_id, remote_id[:120])
        return reconciled

    def claim_due_batch(self, owner: str | None = None, lease_seconds: int = 120):
        # No new external write is allowed while a previous accepted post is waiting
        # for its local `sent` commit. This is the anti-duplicate fail-closed gate.
        self.reconcile_external_successes(best_effort=False)
        return super().claim_due_batch(owner=owner, lease_seconds=lease_seconds)

    def mark_target_sent(self, target_id: int, remote_id: str | None) -> None:
        target_id = int(target_id)
        self._uncertain_external_targets.add(target_id)
        receipt_written = False
        receipt_error: Exception | None = None
        try:
            self._write_receipt(target_id, remote_id)
            receipt_written = True
        except Exception as exc:
            receipt_error = exc
            logger.exception("Could not persist external publication receipt target=%s", target_id)

        try:
            super().mark_target_sent(target_id, remote_id)
        except Exception:
            # Keep the receipt/in-memory guard. The worker may report a local commit
            # problem, but mark_target_failed below must not downgrade this target.
            raise

        self._uncertain_external_targets.discard(target_id)
        if receipt_written:
            try:
                self._receipt_path(target_id).unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not remove publication receipt target=%s", target_id)
        if receipt_error is not None:
            logger.warning(
                "Publication was committed to SQLite although recovery receipt could not be written target=%s: %s",
                target_id, receipt_error,
            )

    def mark_target_failed(self, target_id: int, error: object) -> None:
        target_id = int(target_id)
        receipt = self._read_receipt(self._receipt_path(target_id))
        if receipt is not None:
            try:
                super().mark_target_sent(target_id, receipt[1] or None)
                self._receipt_path(target_id).unlink(missing_ok=True)
                self._uncertain_external_targets.discard(target_id)
                logger.info("Recovered external success instead of marking failed target=%s", target_id)
            except Exception:
                # Fail closed. Leaving this target non-sent is imperfect but safer than
                # writing `failed`, because claim_due_batch will reconcile before retry.
                logger.exception("External success is pending local reconciliation target=%s", target_id)
            return
        if target_id in self._uncertain_external_targets:
            logger.error(
                "Suppressing failed downgrade for target=%s because external success outcome is already known",
                target_id,
            )
            return
        super().mark_target_failed(target_id, error)

    def mark_unsent_targets_failed(self, batch_id: int, error: object) -> None:
        # Reconcile known successes first, then exclude any receipt that still cannot
        # be committed. A batch-level exception must never turn an accepted post into
        # a retry candidate.
        self.reconcile_external_successes(best_effort=True)
        protected = self._pending_receipt_ids() | set(self._uncertain_external_targets)
        with self.connect() as db:
            if protected:
                placeholders = ",".join("?" for _ in protected)
                db.execute(
                    f"UPDATE publication_targets SET status='failed',last_error=?,updated_at=? "
                    f"WHERE batch_id=? AND status!='sent' AND id NOT IN ({placeholders})",
                    [redact_secrets(error)[:1000], _iso(), int(batch_id), *sorted(protected)],
                )
            else:
                db.execute(
                    "UPDATE publication_targets SET status='failed',last_error=?,updated_at=? "
                    "WHERE batch_id=? AND status!='sent'",
                    (redact_secrets(error)[:1000], _iso(), int(batch_id)),
                )


__all__ = ["Database"]
