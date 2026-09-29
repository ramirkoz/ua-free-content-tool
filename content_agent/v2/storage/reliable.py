from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path

from ...database import redact_secrets
from ...paths import data_dir
from ..publishing.outcomes import PublicationOutcome, derive_outcome, normalize_outcome
from ..publishing.retry import uncertain_publication_reason
from .compat import Database as CompatDatabase
from .manual_topics import ManualTopicsMixin
from .migrations import apply_v2_migrations

logger = logging.getLogger('content_agent.v2.storage.reliable')


class Database(ManualTopicsMixin, CompatDatabase):
    """Durable publication boundary plus V2 product metadata and migrations."""

    _receipt_lock = threading.RLock()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_v2_migrations(self)
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

    def _set_target_outcome(self, target_id: int, outcome: PublicationOutcome) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE publication_targets SET outcome=?,updated_at=datetime('now') WHERE id=?",
                (outcome.value, int(target_id)),
            )

    def _refresh_target_outcome(self, target_id: int) -> PublicationOutcome:
        with self.connect() as db:
            row = db.execute(
                "SELECT status,remote_id,last_error,progress_json,outcome "
                "FROM publication_targets WHERE id=?",
                (int(target_id),),
            ).fetchone()
            if row is None:
                raise KeyError(int(target_id))
            outcome = derive_outcome(
                status=row['status'],
                remote_id=row['remote_id'],
                last_error=row['last_error'],
                progress_json=row['progress_json'],
                current=row['outcome'],
            )
            db.execute(
                "UPDATE publication_targets SET outcome=? WHERE id=?",
                (outcome.value, int(target_id)),
            )
        return outcome

    def _refresh_batch_outcomes(self, batch_id: int) -> None:
        with self.connect() as db:
            rows = db.execute(
                "SELECT id FROM publication_targets WHERE batch_id=?",
                (int(batch_id),),
            ).fetchall()
        for row in rows:
            self._refresh_target_outcome(int(row['id']))

    def publication_target_outcome(self, target_id: int) -> PublicationOutcome:
        with self.connect() as db:
            row = db.execute(
                "SELECT outcome FROM publication_targets WHERE id=?",
                (int(target_id),),
            ).fetchone()
        if row is None:
            raise KeyError(int(target_id))
        return normalize_outcome(row['outcome'])

    def confirm_target_not_sent(self, target_id: int) -> None:
        """Record an explicit operator resolution for a previously unknown outcome."""
        target_id = int(target_id)
        with self.connect() as db:
            row = db.execute(
                "SELECT status,progress_json FROM publication_targets WHERE id=?",
                (target_id,),
            ).fetchone()
            if row is None:
                raise KeyError(target_id)
            if str(row['status'] or '') == 'sent':
                raise ValueError('Підтверджену успішну публікацію не можна позначити як не відправлену.')
            try:
                progress = json.loads(str(row['progress_json'] or '{}'))
                progress = dict(progress) if isinstance(progress, dict) else {}
            except Exception:
                progress = {}
            progress['operator_confirmed_not_sent_at'] = datetime.now().astimezone().isoformat(timespec='seconds')
            db.execute(
                "UPDATE publication_targets SET outcome=?,progress_json=?,updated_at=datetime('now') WHERE id=?",
                (
                    PublicationOutcome.CONFIRMED_NOT_SENT.value,
                    json.dumps(progress, ensure_ascii=False, sort_keys=True),
                    target_id,
                ),
            )

    def reconcile_external_successes(self, *, best_effort: bool = False) -> int:
        count = 0
        for path in sorted(self._receipt_dir().glob('target_*.json')):
            parsed = self._read_receipt(path)
            if parsed is None:
                continue
            target_id, remote_id = parsed
            try:
                super().mark_target_sent(target_id, remote_id or None)
                self._set_target_outcome(target_id, PublicationOutcome.SENT)
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
        self.reconcile_external_successes(best_effort=True)
        return super().list_publication_history(limit=limit)

    def mark_target_sent(self, target_id: int, remote_id: str | None) -> None:
        target_id = int(target_id)
        self._uncertain_external_targets.add(target_id)
        self._write_receipt(target_id, remote_id)
        super().mark_target_sent(target_id, remote_id)
        self._set_target_outcome(target_id, PublicationOutcome.SENT)
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
                self._set_target_outcome(target_id, PublicationOutcome.SENT)
                self._receipt_path(target_id).unlink(missing_ok=True)
                self._uncertain_external_targets.discard(target_id)
            except Exception:
                logger.exception('External success pending reconciliation target=%s', target_id)
            return
        if target_id in self._uncertain_external_targets:
            logger.error('Suppressing failed downgrade for known external success target=%s', target_id)
            return
        super().mark_target_failed(target_id, error)
        self._refresh_target_outcome(target_id)

    def _assert_batches_safe_to_retry(self, batch_ids) -> None:
        ids = sorted({int(value) for value in batch_ids if int(value) > 0})
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        with self.connect() as db:
            rows = db.execute(
                f"SELECT id,batch_id,last_error,progress_json,outcome FROM publication_targets "
                f"WHERE batch_id IN ({placeholders}) AND status!='sent'",
                ids,
            ).fetchall()
        for row in rows:
            outcome = normalize_outcome(row['outcome'])
            if outcome is PublicationOutcome.CONFIRMED_NOT_SENT:
                continue
            reason = uncertain_publication_reason(row['last_error'], row['progress_json'])
            if outcome is PublicationOutcome.UNKNOWN and not reason:
                reason = 'Результат попередньої зовнішньої операції позначено як невідомий.'
            if reason:
                raise ValueError(
                    f"Пакет #{int(row['batch_id'])}, ціль #{int(row['id'])}: {reason} "
                    "Повтор заблоковано до ручної перевірки платформи."
                )

    def _reschedule_batches(self, schedules, *, allowed_statuses):
        self._assert_batches_safe_to_retry(schedules.keys())
        return super()._reschedule_batches(schedules, allowed_statuses=allowed_statuses)

    def resume_batch(self, batch_id: int, *, reset_attempts: bool = True) -> None:
        self._assert_batches_safe_to_retry([batch_id])
        return super().resume_batch(batch_id, reset_attempts=reset_attempts)

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
        self._refresh_batch_outcomes(int(batch_id))
