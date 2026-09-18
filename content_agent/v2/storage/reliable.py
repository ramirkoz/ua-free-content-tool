from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path

from ...database import redact_secrets
from ...paths import data_dir
from .compat import Database as CompatDatabase

logger = logging.getLogger('content_agent.v2.storage.reliable')


class Database(CompatDatabase):
    """RC10 durable publication-success boundary.

    External success is journalled before SQLite is updated.  Receipts are replayed
    before another claim and before History is read, so a local commit failure cannot
    silently hide an already-published post or cause an automatic duplicate retry.
    """
    _receipt_lock = threading.RLock()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._uncertain_external_targets: set[int] = set()
        self.reconcile_external_successes(best_effort=True)

    @staticmethod
    def _receipt_dir() -> Path:
        path = data_dir() / 'publication_recovery'
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def _receipt_path(cls, target_id: int) -> Path:
        return cls._receipt_dir() / f'target_{int(target_id)}.json'

    def _write_receipt(self, target_id: int, remote_id: str | None) -> None:
        path = self._receipt_path(target_id)
        payload = {
            'schema': 'ua-free-content-tool-publication-receipt-v1',
            'target_id': int(target_id),
            'remote_id': str(remote_id or ''),
            'accepted_at': datetime.now().astimezone().isoformat(timespec='seconds'),
        }
        tmp = path.with_suffix('.tmp')
        with self._receipt_lock:
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
            tmp.replace(path)

    @classmethod
    def _read_receipt(cls, path: Path):
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(value, dict) or value.get('schema') != 'ua-free-content-tool-publication-receipt-v1':
                return None
            target_id = int(value.get('target_id') or 0)
            if target_id <= 0:
                return None
            return target_id, str(value.get('remote_id') or '')
        except Exception:
            return None

    def reconcile_external_successes(self, *, best_effort: bool = False) -> int:
        count = 0
        for path in sorted(self._receipt_dir().glob('target_*.json')):
            parsed = self._read_receipt(path)
            if parsed is None:
                continue
            target_id, remote_id = parsed
            try:
                super().mark_target_sent(target_id, remote_id or None)
            except Exception:
                if best_effort:
                    logger.warning('Publication receipt still pending target=%s', target_id, exc_info=True)
                    continue
                raise
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            self._uncertain_external_targets.discard(target_id)
            count += 1
        return count

    def claim_due_batch(self, owner: str | None = None, lease_seconds: int = 120):
        self.reconcile_external_successes(best_effort=False)
        return super().claim_due_batch(owner=owner, lease_seconds=lease_seconds)

    def list_publication_history(self, limit: int = 500):
        # History is a read boundary too: reconcile accepted external posts first.
        self.reconcile_external_successes(best_effort=True)
        return super().list_publication_history(limit=limit)

    def mark_target_sent(self, target_id: int, remote_id: str | None) -> None:
        target_id = int(target_id)
        self._uncertain_external_targets.add(target_id)
        self._write_receipt(target_id, remote_id)
        super().mark_target_sent(target_id, remote_id)
        self._uncertain_external_targets.discard(target_id)
        try:
            self._receipt_path(target_id).unlink(missing_ok=True)
        except OSError:
            pass

    def mark_target_failed(self, target_id: int, error: object) -> None:
        target_id = int(target_id)
        receipt = self._read_receipt(self._receipt_path(target_id))
        if receipt is not None:
            try:
                super().mark_target_sent(target_id, receipt[1] or None)
                self._receipt_path(target_id).unlink(missing_ok=True)
                self._uncertain_external_targets.discard(target_id)
            except Exception:
                logger.exception('External success pending reconciliation target=%s', target_id)
            return
        if target_id in self._uncertain_external_targets:
            logger.error('Suppressing failed downgrade for known external success target=%s', target_id)
            return
        super().mark_target_failed(target_id, error)

    def mark_unsent_targets_failed(self, batch_id: int, error: object) -> None:
        self.reconcile_external_successes(best_effort=True)
        protected = set(self._uncertain_external_targets)
        for path in self._receipt_dir().glob('target_*.json'):
            parsed = self._read_receipt(path)
            if parsed:
                protected.add(parsed[0])
        with self.connect() as db:
            if protected:
                placeholders = ','.join('?' for _ in protected)
                db.execute(
                    f"UPDATE publication_targets SET status='failed',last_error=?,updated_at=datetime('now') "
                    f"WHERE batch_id=? AND status!='sent' AND id NOT IN ({placeholders})",
                    [redact_secrets(error)[:1000], int(batch_id), *sorted(protected)],
                )
            else:
                super().mark_unsent_targets_failed(batch_id, error)
