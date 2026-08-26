from __future__ import annotations

import json
from datetime import timedelta
from typing import Iterable

from .database import Database as BaseDatabase, _iso, _now
from .models import PublicationBatch, PublicationTarget, QueueUpdateResult
from .news_logic import is_today_kyiv

PUBLICATION_HISTORY_RETENTION_DAYS = 7


class Database(BaseDatabase):
    """RC14 database layer with a seven-day operational publication window."""

    def recover_abandoned_batches(self, *args, **kwargs):
        if getattr(self, "_rc14_defer_startup_maintenance", False):
            return []
        return super().recover_abandoned_batches(*args, **kwargs)

    def archive_stale_groups(self) -> int:
        """Archive stale editorial blocks with one write transaction, not per-row commits."""
        if getattr(self, "_rc14_defer_startup_maintenance", False):
            return 0
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT g.id,a.published_at
                FROM news_groups g
                JOIN articles a ON a.group_id=g.id
                WHERE g.status IN ('new','draft','rejected')
                ORDER BY g.id
                """
            ).fetchall()
            by_group: dict[int, list[str | None]] = {}
            for row in rows:
                by_group.setdefault(int(row["id"]), []).append(row["published_at"])
            stale_ids = [
                group_id
                for group_id, dates in by_group.items()
                if not any(is_today_kyiv(value) for value in dates)
            ]
            if not stale_ids:
                return 0
            now = _iso()
            db.execute("BEGIN IMMEDIATE")
            try:
                for start in range(0, len(stale_ids), 400):
                    chunk = stale_ids[start:start + 400]
                    placeholders = ",".join("?" for _ in chunk)
                    db.execute(
                        f"UPDATE news_groups SET status='archived',updated_at=? "
                        f"WHERE status IN ('new','draft','rejected') AND id IN ({placeholders})",
                        [now, *chunk],
                    )
                    db.execute(
                        f"UPDATE articles SET status='archived' WHERE group_id IN ({placeholders})",
                        chunk,
                    )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return len(stale_ids)

    @staticmethod
    def _ensure_publication_archive(db) -> None:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS archived_publication_batches (
                batch_id INTEGER PRIMARY KEY,
                article_id INTEGER NOT NULL,
                group_id INTEGER NOT NULL,
                scheduled_at TEXT NOT NULL,
                batch_status TEXT NOT NULL,
                headline TEXT NOT NULL DEFAULT '',
                canonical_title TEXT NOT NULL DEFAULT '',
                rewrite_text TEXT NOT NULL DEFAULT '',
                published_at TEXT NOT NULL DEFAULT '',
                archived_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_archived_publication_group
                ON archived_publication_batches(group_id,batch_id);
            CREATE TABLE IF NOT EXISTS archived_publication_targets (
                target_id INTEGER PRIMARY KEY,
                batch_id INTEGER NOT NULL,
                platform TEXT NOT NULL,
                payload_text TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                remote_id TEXT,
                last_error TEXT,
                progress_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_archived_target_batch
                ON archived_publication_targets(batch_id,target_id);
            CREATE INDEX IF NOT EXISTS idx_archived_target_platform
                ON archived_publication_targets(platform,status);
            """
        )

    def archive_old_publication_history(
        self,
        retention_days: int = PUBLICATION_HISTORY_RETENTION_DAYS,
        *,
        limit: int = 5000,
    ) -> int:
        """Move sent publication packages older than the retention window to archive tables.

        Archive and deletion happen in the same SQLite transaction. Articles/news groups stay
        in place, while heavy publication target rows leave the operational queue/history tables.
        """
        days = max(1, int(retention_days))
        cutoff = _iso(_now() - timedelta(days=days))
        with self.connect() as db:
            self._ensure_publication_archive(db)
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute("CREATE TEMP TABLE IF NOT EXISTS rc14_archive_ids(id INTEGER PRIMARY KEY)")
                db.execute("DELETE FROM rc14_archive_ids")
                db.execute(
                    """
                    INSERT INTO rc14_archive_ids(id)
                    SELECT b.id
                    FROM publication_batches b
                    WHERE b.status IN ('completed','cancelled')
                      AND EXISTS (
                          SELECT 1 FROM publication_targets s
                          WHERE s.batch_id=b.id AND s.status='sent'
                      )
                      AND julianday(COALESCE((
                          SELECT MAX(s.updated_at) FROM publication_targets s
                          WHERE s.batch_id=b.id AND s.status='sent'
                      ), b.updated_at, b.scheduled_at)) < julianday(?)
                    ORDER BY b.id
                    LIMIT ?
                    """,
                    (cutoff, max(1, int(limit))),
                )
                count = int(db.execute("SELECT COUNT(*) FROM rc14_archive_ids").fetchone()[0])
                if not count:
                    db.execute("COMMIT")
                    return 0
                archived_at = _iso()
                db.execute(
                    """
                    INSERT OR REPLACE INTO archived_publication_batches(
                        batch_id,article_id,group_id,scheduled_at,batch_status,headline,
                        canonical_title,rewrite_text,published_at,archived_at
                    )
                    SELECT b.id,b.article_id,a.group_id,b.scheduled_at,b.status,g.headline,
                           g.canonical_title,g.rewrite_text,
                           COALESCE((SELECT MAX(s.updated_at) FROM publication_targets s
                                     WHERE s.batch_id=b.id AND s.status='sent'), b.updated_at), ?
                    FROM publication_batches b
                    JOIN articles a ON a.id=b.article_id
                    JOIN news_groups g ON g.id=a.group_id
                    WHERE b.id IN (SELECT id FROM rc14_archive_ids)
                    """,
                    (archived_at,),
                )
                db.execute(
                    """
                    INSERT OR REPLACE INTO archived_publication_targets(
                        target_id,batch_id,platform,payload_text,status,remote_id,last_error,
                        progress_json,updated_at
                    )
                    SELECT t.id,t.batch_id,t.platform,t.payload_text,t.status,t.remote_id,
                           t.last_error,t.progress_json,t.updated_at
                    FROM publication_targets t
                    WHERE t.batch_id IN (SELECT id FROM rc14_archive_ids)
                    """
                )
                db.execute(
                    "DELETE FROM publication_batches WHERE id IN (SELECT id FROM rc14_archive_ids)"
                )
                db.execute("DELETE FROM rc14_archive_ids")
                db.execute("COMMIT")
                return count
            except Exception:
                db.execute("ROLLBACK")
                raise

    def _archived_sent_for_group(self, group_id: int) -> dict[str, tuple[int, str]]:
        with self.connect() as db:
            self._ensure_publication_archive(db)
            rows = db.execute(
                """
                SELECT t.platform,b.batch_id,b.scheduled_at
                FROM archived_publication_targets t
                JOIN archived_publication_batches b ON b.batch_id=t.batch_id
                WHERE b.group_id=? AND t.status='sent'
                ORDER BY b.batch_id
                """,
                (group_id,),
            ).fetchall()
        return {
            str(row["platform"]): (int(row["batch_id"]), str(row["scheduled_at"]))
            for row in rows
        }

    def queue_targets(
        self,
        article_id: int,
        scheduled_at: str,
        targets: dict[str, str],
    ) -> QueueUpdateResult:
        """Preserve deduplication after old sent targets leave the live queue tables."""
        group_id = self.group_id_for_article(article_id)
        archived = self._archived_sent_for_group(group_id)
        archived_sent = sorted(set(targets) & set(archived))
        remaining = {k: v for k, v in targets.items() if k not in archived}
        if not remaining:
            if not archived_sent:
                return super().queue_targets(article_id, scheduled_at, targets)
            latest = max((archived[p] for p in archived_sent), key=lambda item: item[0])
            return QueueUpdateResult(
                batch_id=latest[0],
                scheduled_at=latest[1],
                status="completed",
                created=False,
                already_sent=archived_sent,
            )
        result = super().queue_targets(article_id, scheduled_at, remaining)
        result.already_sent = sorted(set(result.already_sent) | set(archived_sent))
        return result

    def target_statuses_for_group(self, group_id: int) -> dict[str, str]:
        statuses = {platform: "sent" for platform in self._archived_sent_for_group(group_id)}
        statuses.update(super().target_statuses_for_group(group_id))
        return statuses

    def list_publication_history(
        self,
        limit: int = 500,
        *,
        retention_days: int = PUBLICATION_HISTORY_RETENTION_DAYS,
    ) -> list[dict[str, object]]:
        """Return only the rolling operational history, bounded before rows leave SQLite."""
        cutoff = _iso(_now() - timedelta(days=max(1, int(retention_days))))
        with self.connect() as db:
            rows = db.execute(
                """
                WITH recent AS (
                    SELECT b.id
                    FROM publication_batches b
                    WHERE EXISTS (
                        SELECT 1 FROM publication_targets s
                        WHERE s.batch_id=b.id AND s.status='sent'
                    )
                      AND julianday(COALESCE((
                          SELECT MAX(s.updated_at) FROM publication_targets s
                          WHERE s.batch_id=b.id AND s.status='sent'
                      ), b.updated_at, b.scheduled_at)) >= julianday(?)
                    ORDER BY b.id DESC
                    LIMIT ?
                )
                SELECT b.id AS batch_id,b.scheduled_at,b.status AS batch_status,
                       a.group_id,g.headline,g.canonical_title,g.rewrite_text,
                       t.id AS target_id,t.platform,t.status AS target_status,t.remote_id,
                       t.last_error,t.progress_json,t.updated_at
                FROM recent r
                JOIN publication_batches b ON b.id=r.id
                JOIN articles a ON a.id=b.article_id
                JOIN news_groups g ON g.id=a.group_id
                JOIN publication_targets t ON t.batch_id=b.id
                ORDER BY b.id DESC,t.id
                """,
                (cutoff, max(1, int(limit))),
            ).fetchall()
        grouped: dict[int, dict[str, object]] = {}
        for row in rows:
            batch_id = int(row["batch_id"])
            item = grouped.setdefault(
                batch_id,
                {
                    "batch_id": batch_id,
                    "group_id": int(row["group_id"]),
                    "headline": str(row["headline"] or row["canonical_title"] or ""),
                    "rewrite_text": str(row["rewrite_text"] or ""),
                    "scheduled_at": str(row["scheduled_at"] or ""),
                    "batch_status": str(row["batch_status"] or ""),
                    "published_at": "",
                    "targets": [],
                },
            )
            try:
                progress = json.loads(str(row["progress_json"] or "{}"))
            except json.JSONDecodeError:
                progress = {}
            if not isinstance(progress, dict):
                progress = {}
            target = {
                "id": int(row["target_id"]),
                "platform": str(row["platform"]),
                "status": str(row["target_status"]),
                "remote_id": str(row["remote_id"] or ""),
                "last_error": str(row["last_error"] or ""),
                "updated_at": str(row["updated_at"] or ""),
                "progress": progress,
            }
            item["targets"].append(target)  # type: ignore[union-attr]
            if target["status"] == "sent" and target["updated_at"] > item["published_at"]:
                item["published_at"] = target["updated_at"]
        return list(grouped.values())[: max(1, int(limit))]

    def list_batches(
        self,
        limit: int = 200,
        statuses: set[str] | None = None,
    ) -> list[PublicationBatch]:
        query = "SELECT * FROM publication_batches"
        params: list[object] = []
        if statuses is not None:
            allowed = {"pending", "in_progress", "paused", "completed", "cancelled"}
            unknown = set(statuses) - allowed
            if unknown:
                raise ValueError(f"Unknown batch statuses: {sorted(unknown)}")
            if not statuses:
                return []
            placeholders = ",".join("?" for _ in statuses)
            query += f" WHERE status IN ({placeholders})"
            params.extend(sorted(statuses))
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, int(limit)))
        with self.connect() as db:
            batch_rows = db.execute(query, params).fetchall()
            if not batch_rows:
                return []
            ids = [int(row["id"]) for row in batch_rows]
            target_map: dict[int, list[PublicationTarget]] = {batch_id: [] for batch_id in ids}
            for start in range(0, len(ids), 400):
                chunk = ids[start:start + 400]
                placeholders = ",".join("?" for _ in chunk)
                target_rows = db.execute(
                    f"SELECT * FROM publication_targets WHERE batch_id IN ({placeholders}) ORDER BY batch_id,id",
                    chunk,
                ).fetchall()
                for row in target_rows:
                    try:
                        progress = json.loads(str(row["progress_json"] or "{}"))
                    except json.JSONDecodeError:
                        progress = {}
                    if not isinstance(progress, dict):
                        progress = {}
                    target_map[int(row["batch_id"])].append(
                        PublicationTarget(
                            id=int(row["id"]),
                            batch_id=int(row["batch_id"]),
                            platform=str(row["platform"]),
                            status=str(row["status"]),
                            remote_id=row["remote_id"],
                            last_error=row["last_error"],
                            progress=progress,
                        )
                    )
        return [
            PublicationBatch(
                id=int(row["id"]),
                article_id=int(row["article_id"]),
                scheduled_at=str(row["scheduled_at"]),
                status=str(row["status"]),
                lease_owner=row["lease_owner"],
                lease_until=row["lease_until"],
                attempts=int(row["attempts"]),
                targets=target_map.get(int(row["id"]), []),
                cleanup_error=row["cleanup_error"],
            )
            for row in batch_rows
        ]

    def group_labels_for_batches(self, batch_ids: Iterable[int]) -> dict[int, str]:
        ids = sorted({int(item) for item in batch_ids if int(item) > 0})
        if not ids:
            return {}
        labels: dict[int, str] = {}
        with self.connect() as db:
            for start in range(0, len(ids), 400):
                chunk = ids[start:start + 400]
                placeholders = ",".join("?" for _ in chunk)
                rows = db.execute(
                    f"""
                    SELECT b.id AS batch_id,g.id AS group_id,g.canonical_title
                    FROM publication_batches b
                    JOIN articles a ON a.id=b.article_id
                    JOIN news_groups g ON g.id=a.group_id
                    WHERE b.id IN ({placeholders})
                    """,
                    chunk,
                ).fetchall()
                for row in rows:
                    labels[int(row["batch_id"])] = f"#{int(row['group_id'])} · {str(row['canonical_title'])}"
        return labels
