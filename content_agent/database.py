from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator

from .maintenance import DATA_MAINTENANCE_LOCK
from .editorial_memory import matches_content_exclusion
from .models import (
    Article,
    CollectedArticle,
    NewsGroup,
    PublicationBatch,
    PublicationTarget,
    QueueUpdateResult,
    Source,
)
from .news_logic import calculate_explosiveness, is_today_kyiv, parse_published_at
from .paths import config_path, database_path, portable_key_path
from .security import redact_secrets, sha256_bytes

UTC = timezone.utc
DATABASE_SCHEMA_VERSION = 8


class LeaseLost(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).astimezone(UTC).isoformat(timespec="seconds")


def _parse_aware_iso(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError("Некоректний час публікації.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Час публікації повинен містити часовий пояс.")
    return parsed.astimezone(UTC)


def _normalize_scheduled_at(value: str) -> str:
    # Store every new/updated schedule in one canonical UTC representation.
    # Older portable databases may still contain +02:00/+03:00 rows; query
    # paths use SQLite julianday() so those rows remain comparable by instant.
    return _iso(_parse_aware_iso(value))


class Database:
    def __init__(self, path: Path | None = None):
        self.path = path or database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate_existing_database_safely()
        self.initialize()

    @contextmanager
    def _connect_path(self, path: Path) -> Iterator[sqlite3.Connection]:
        with DATA_MAINTENANCE_LOCK:
            connection = sqlite3.connect(path, timeout=15, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA busy_timeout=15000")
            try:
                yield connection
            finally:
                connection.close()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        with self._connect_path(self.path) as connection:
            yield connection

    @staticmethod
    def _fsync_file(path: Path) -> None:
        with path.open("rb+") as handle:
            handle.flush()
            os.fsync(handle.fileno())

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        if os.name == "nt":
            return
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _remove_sidecars(path: Path) -> None:
        for suffix in ("-wal", "-shm", "-journal"):
            try:
                Path(str(path) + suffix).unlink()
            except FileNotFoundError:
                pass

    def _schema_version(self, path: Path) -> int:
        if not path.exists() or path.stat().st_size == 0:
            return 0
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            return int(connection.execute("PRAGMA user_version").fetchone()[0])
        finally:
            connection.close()

    def _sqlite_snapshot(self, source: Path, destination: Path) -> None:
        source_db = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        destination_db = sqlite3.connect(destination)
        try:
            source_db.backup(destination_db)
            destination_db.commit()
            if destination_db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("Pre-migration SQLite snapshot failed quick_check.")
        finally:
            destination_db.close()
            source_db.close()
        self._fsync_file(destination)

    def _write_pre_migration_backup(self, snapshot: Path, old_version: int) -> Path:
        backup_dir = self.path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = _now().strftime("%Y%m%dT%H%M%SZ")
        final = backup_dir / f"UA_FREE_pre_R8_schema_{old_version}_{stamp}.zip"
        temporary = final.with_suffix(".zip.tmp")
        files: list[tuple[str, Path]] = [("content_agent.sqlite3", snapshot)]
        try:
            default_db = database_path().resolve()
        except OSError:
            default_db = database_path().absolute()
        if self.path.resolve() == default_db:
            cfg = config_path()
            if cfg.exists():
                files.append((cfg.name, cfg))
                if cfg.name == "config.portable":
                    key = portable_key_path()
                    if not key.exists():
                        raise RuntimeError("Portable configuration key is missing before migration.")
                    files.append(("portable.key", key))
        manifest = {
            "application": "UA_FREE_Content_Tool",
            "purpose": "pre_R8_migration_rollback",
            "source_schema": old_version,
            "created_at": _iso(),
            "files": {
                name: {
                    "size": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
                for name, path in files
            },
        }
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, path in files:
                archive.write(path, name)
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2))
        self._fsync_file(temporary)
        os.replace(temporary, final)
        self._fsync_directory(backup_dir)
        return final

    def _migrate_existing_database_safely(self) -> None:
        old_version = self._schema_version(self.path)
        if old_version == 0 or old_version == DATABASE_SCHEMA_VERSION:
            return
        if old_version > DATABASE_SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema {old_version} is newer than supported {DATABASE_SCHEMA_VERSION}."
            )
        stage = self.path.with_name(f".{self.path.name}.r8-migration-{uuid.uuid4().hex}")
        rollback_snapshot = self.path.with_name(f".{self.path.name}.r8-rollback-{uuid.uuid4().hex}")
        try:
            # First create a durable rollback snapshot. If this fails, the live R7
            # database has not been opened for writing and startup stops.
            self._sqlite_snapshot(self.path, rollback_snapshot)
            self._write_pre_migration_backup(rollback_snapshot, old_version)
            # Migrate a second snapshot, validate it, then atomically replace the
            # live file. A failed migration therefore leaves R7 bytes untouched.
            self._sqlite_snapshot(self.path, stage)
            self.initialize(stage)
            check = sqlite3.connect(f"file:{stage}?mode=ro", uri=True)
            try:
                result = check.execute("PRAGMA quick_check").fetchone()[0]
                version = int(check.execute("PRAGMA user_version").fetchone()[0])
            finally:
                check.close()
            if result != "ok" or version != DATABASE_SCHEMA_VERSION:
                raise RuntimeError("R8 staged database migration did not validate.")
            checkpoint = sqlite3.connect(stage)
            try:
                checkpoint.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                checkpoint.close()
            self._remove_sidecars(stage)
            self._fsync_file(stage)
            self._remove_sidecars(self.path)
            os.replace(stage, self.path)
            self._fsync_file(self.path)
            self._fsync_directory(self.path.parent)
        finally:
            for candidate in (stage, rollback_snapshot):
                try:
                    candidate.unlink()
                except FileNotFoundError:
                    pass
            self._remove_sidecars(stage)
            self._remove_sidecars(rollback_snapshot)

    @staticmethod
    def _columns(db: sqlite3.Connection, table: str) -> set[str]:
        return {str(row[1]) for row in db.execute(f"PRAGMA table_info({table})").fetchall()}

    @staticmethod
    def _ensure_paused_batch_status(db: sqlite3.Connection) -> None:
        row = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='publication_batches'"
        ).fetchone()
        schema_sql = str(row[0] or "") if row else ""
        if "'paused'" in schema_sql:
            return
        # SQLite cannot alter a CHECK constraint in place. Rebuild only the parent
        # table while foreign-key enforcement is temporarily disabled; child rows
        # keep referencing the unchanged final table name.
        db.execute("PRAGMA foreign_keys=OFF")
        try:
            db.executescript(
                """
                DROP INDEX IF EXISTS idx_batches_due;
                DROP INDEX IF EXISTS idx_batches_article;
                CREATE TABLE publication_batches_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
                    scheduled_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending','in_progress','paused','completed','cancelled')),
                    lease_owner TEXT,
                    lease_until TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    cleanup_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO publication_batches_new(
                    id,article_id,scheduled_at,status,lease_owner,lease_until,attempts,
                    cleanup_error,created_at,updated_at
                )
                SELECT id,article_id,scheduled_at,status,lease_owner,lease_until,attempts,
                       cleanup_error,created_at,updated_at
                FROM publication_batches;
                DROP TABLE publication_batches;
                ALTER TABLE publication_batches_new RENAME TO publication_batches;
                CREATE INDEX idx_batches_due
                    ON publication_batches(status, scheduled_at, lease_until);
                CREATE INDEX idx_batches_article
                    ON publication_batches(article_id, status);
                """
            )
        finally:
            db.execute("PRAGMA foreign_keys=ON")
        if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise RuntimeError("Publication queue migration failed foreign_key_check.")

    def initialize(self, path: Path | None = None) -> None:
        target = path or self.path
        with self._connect_path(target) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL CHECK(kind IN ('rss','telegram','url')),
                    name TEXT NOT NULL,
                    url TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_checked_at TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(kind, url)
                );

                CREATE TABLE IF NOT EXISTS news_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    canonical_title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'new'
                        CHECK(status IN ('new','draft','approved','rejected','archived')),
                    headline TEXT NOT NULL DEFAULT '',
                    fact_card TEXT NOT NULL DEFAULT '',
                    rewrite_text TEXT NOT NULL DEFAULT '',
                    ai_draft_text TEXT NOT NULL DEFAULT '',
                    platform_texts_json TEXT NOT NULL DEFAULT '{}',
                    include_source_link INTEGER NOT NULL DEFAULT 0,
                    media_drive_url TEXT NOT NULL DEFAULT '',
                    media_file_id TEXT NOT NULL DEFAULT '',
                    media_name TEXT NOT NULL DEFAULT '',
                    media_kind TEXT NOT NULL DEFAULT '' CHECK(media_kind IN ('','image','video')),
                    media_mime TEXT NOT NULL DEFAULT '',
                    media_size INTEGER NOT NULL DEFAULT 0,
                    explosiveness_score INTEGER NOT NULL DEFAULT 0,
                    explosiveness_confidence INTEGER NOT NULL DEFAULT 0,
                    explosiveness_details_json TEXT NOT NULL DEFAULT '{}',
                    recommended_platforms_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                    group_id INTEGER REFERENCES news_groups(id) ON DELETE CASCADE,
                    external_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    raw_text TEXT NOT NULL,
                    published_at TEXT,
                    discovered_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'new' CHECK(status IN ('new','draft','approved','archived')),
                    headline TEXT NOT NULL DEFAULT '',
                    fact_card TEXT NOT NULL DEFAULT '',
                    rewrite_text TEXT NOT NULL DEFAULT '',
                    platform_texts_json TEXT NOT NULL DEFAULT '{}',
                    UNIQUE(source_id, external_id),
                    UNIQUE(content_hash)
                );

                CREATE TABLE IF NOT EXISTS publication_batches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
                    scheduled_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','in_progress','paused','completed','cancelled')),
                    lease_owner TEXT,
                    lease_until TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    cleanup_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_batches_due
                    ON publication_batches(status, scheduled_at, lease_until);
                CREATE INDEX IF NOT EXISTS idx_batches_article
                    ON publication_batches(article_id, status);
                CREATE TABLE IF NOT EXISTS publication_targets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id INTEGER NOT NULL REFERENCES publication_batches(id) ON DELETE CASCADE,
                    platform TEXT NOT NULL,
                    payload_text TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','sent','failed')),
                    remote_id TEXT,
                    last_error TEXT,
                    progress_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL,
                    UNIQUE(batch_id, platform)
                );

                CREATE TABLE IF NOT EXISTS editorial_examples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id INTEGER,
                    source_fingerprint TEXT NOT NULL,
                    source_text TEXT NOT NULL,
                    ai_draft_text TEXT NOT NULL DEFAULT '',
                    final_text TEXT NOT NULL,
                    headline TEXT NOT NULL DEFAULT '',
                    language TEXT NOT NULL DEFAULT 'uk' CHECK(language IN ('uk','en')),
                    created_at TEXT NOT NULL,
                    UNIQUE(source_fingerprint, final_text, language)
                );
                CREATE INDEX IF NOT EXISTS idx_editorial_examples_created
                    ON editorial_examples(created_at DESC, id DESC);

                CREATE TABLE IF NOT EXISTS topic_merge_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    anchor_signature TEXT NOT NULL,
                    candidate_signature TEXT NOT NULL,
                    decision TEXT NOT NULL DEFAULT 'merged'
                        CHECK(decision IN ('merged','not_related')),
                    anchor_text TEXT NOT NULL,
                    candidate_text TEXT NOT NULL,
                    language TEXT NOT NULL DEFAULT 'uk' CHECK(language IN ('uk','en')),
                    created_at TEXT NOT NULL,
                    UNIQUE(anchor_signature, candidate_signature, decision, language)
                );
                CREATE INDEX IF NOT EXISTS idx_topic_feedback_created
                    ON topic_merge_feedback(created_at DESC, id DESC);

                CREATE TABLE IF NOT EXISTS content_exclusions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id INTEGER,
                    signature TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    source_text TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_content_exclusions_active
                    ON content_exclusions(active, updated_at DESC, id DESC);

                CREATE TABLE IF NOT EXISTS learning_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    language TEXT NOT NULL DEFAULT 'uk' CHECK(language IN ('uk','en')),
                    group_id INTEGER,
                    anchor_group_id INTEGER,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_learning_events_lookup
                    ON learning_events(language,event_type,created_at DESC,id DESC);

                CREATE TABLE IF NOT EXISTS queue_text_migrations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    migration_key TEXT NOT NULL UNIQUE,
                    backup_path TEXT NOT NULL DEFAULT '',
                    summary_json TEXT NOT NULL DEFAULT '{}',
                    completed_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS queue_text_migration_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    migration_id INTEGER NOT NULL REFERENCES queue_text_migrations(id) ON DELETE CASCADE,
                    batch_id INTEGER NOT NULL,
                    group_id INTEGER NOT NULL,
                    old_text TEXT NOT NULL,
                    new_text TEXT NOT NULL,
                    old_length INTEGER NOT NULL,
                    new_length INTEGER NOT NULL,
                    limit_value INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_queue_text_migration_items_batch
                    ON queue_text_migration_items(batch_id, migration_id);
                """
            )
            version = int(db.execute("PRAGMA user_version").fetchone()[0])
            if version > DATABASE_SCHEMA_VERSION:
                raise RuntimeError(f"Database schema {version} is newer than supported {DATABASE_SCHEMA_VERSION}.")
            article_columns = self._columns(db, "articles")
            if "group_id" not in article_columns:
                db.execute("ALTER TABLE articles ADD COLUMN group_id INTEGER REFERENCES news_groups(id) ON DELETE CASCADE")
            group_columns = self._columns(db, "news_groups")
            if "ai_draft_text" not in group_columns:
                db.execute("ALTER TABLE news_groups ADD COLUMN ai_draft_text TEXT NOT NULL DEFAULT ''")
            editorial_columns = self._columns(db, "editorial_examples")
            if "language" not in editorial_columns:
                db.execute("ALTER TABLE editorial_examples ADD COLUMN language TEXT NOT NULL DEFAULT 'uk'")
            topic_columns = self._columns(db, "topic_merge_feedback")
            if "language" not in topic_columns:
                db.execute("ALTER TABLE topic_merge_feedback ADD COLUMN language TEXT NOT NULL DEFAULT 'uk'")
            batch_columns = self._columns(db, "publication_batches")
            if "cleanup_error" not in batch_columns:
                db.execute("ALTER TABLE publication_batches ADD COLUMN cleanup_error TEXT")
            self._ensure_paused_batch_status(db)
            # This index must be created only after an R7 database has received
            # the new group_id column. Creating it inside the initial script would
            # make the first R8 launch fail before migration even started.
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_articles_group ON articles(group_id,published_at,id)"
            )
            self._migrate_legacy_articles(db)
            db.execute(f"PRAGMA user_version={DATABASE_SCHEMA_VERSION}")

    def _migrate_legacy_articles(self, db: sqlite3.Connection) -> None:
        rows = db.execute(
            """
            SELECT id,title,status,headline,fact_card,rewrite_text,platform_texts_json,
                   discovered_at,published_at
            FROM articles WHERE group_id IS NULL ORDER BY id
            """
        ).fetchall()
        for row in rows:
            status = str(row["status"])
            group_status = status if status in {"new", "draft", "approved", "archived"} else "new"
            created = str(row["discovered_at"] or _iso())
            cursor = db.execute(
                """
                INSERT INTO news_groups(
                    canonical_title,status,headline,fact_card,rewrite_text,platform_texts_json,
                    created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    str(row["title"] or "Без заголовка"),
                    group_status,
                    str(row["headline"] or ""),
                    str(row["fact_card"] or ""),
                    str(row["rewrite_text"] or ""),
                    str(row["platform_texts_json"] or "{}"),
                    created,
                    created,
                ),
            )
            db.execute("UPDATE articles SET group_id=? WHERE id=?", (int(cursor.lastrowid), int(row["id"])))

    def queue_text_migration_completed(self, migration_key: str) -> bool:
        with self.connect() as db:
            row = db.execute(
                "SELECT 1 FROM queue_text_migrations WHERE migration_key=?",
                (str(migration_key),),
            ).fetchone()
        return row is not None

    def record_empty_queue_text_migration(self, migration_key: str) -> None:
        now = _iso()
        with self.connect() as db:
            db.execute(
                """
                INSERT OR IGNORE INTO queue_text_migrations(
                    migration_key,backup_path,summary_json,completed_at
                ) VALUES(?,?,?,?)
                """,
                (str(migration_key), "", json.dumps({"items": 0}, sort_keys=True), now),
            )

    def apply_queue_text_migration(
        self,
        migration_key: str,
        updates: list[dict[str, object]],
        *,
        backup_path: str,
    ) -> int:
        """Atomically replace only unsent future payload texts after a safety backup.

        Schedules, package/target IDs, statuses, attempts, remote IDs, media and
        platform selection are immutable in this operation. Every expected old
        value is checked again inside the write transaction so a late worker or
        manual edit cannot be overwritten.
        """

        if not updates:
            self.record_empty_queue_text_migration(migration_key)
            return 0
        now = _iso()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                if db.execute(
                    "SELECT 1 FROM queue_text_migrations WHERE migration_key=?",
                    (str(migration_key),),
                ).fetchone():
                    raise ValueError("Це разове оновлення черги вже застосовано.")
                checked: list[tuple[dict[str, object], sqlite3.Row]] = []
                for item in updates:
                    batch_id = int(item["batch_id"])
                    group_id = int(item["group_id"])
                    row = db.execute(
                        """
                        SELECT b.status,b.scheduled_at,a.group_id,g.rewrite_text
                        FROM publication_batches b
                        JOIN articles a ON a.id=b.article_id
                        JOIN news_groups g ON g.id=a.group_id
                        WHERE b.id=?
                        """,
                        (batch_id,),
                    ).fetchone()
                    if not row:
                        raise KeyError(batch_id)
                    if str(row["status"]) not in {"pending", "paused"}:
                        raise ValueError(f"Пакет #{batch_id} змінив статус і не може бути оновлений.")
                    if int(row["group_id"]) != group_id:
                        raise ValueError(f"Пакет #{batch_id} змінив прив'язку до новини.")
                    if str(row["scheduled_at"]) != str(item["scheduled_at"]):
                        raise ValueError(f"Час пакета #{batch_id} змінився під час перевірки.")
                    expected_old = str(item["old_text"]).strip()
                    current_old = str(row["rewrite_text"] or "").strip()
                    if current_old and current_old != expected_old:
                        raise ValueError(f"Текст пакета #{batch_id} уже змінено в іншому вікні.")
                    payloads = item.get("payloads")
                    if not isinstance(payloads, dict) or not payloads:
                        raise ValueError(f"Пакет #{batch_id} не має підготовлених цільових текстів.")
                    for raw_target_id, new_payload in payloads.items():
                        target_id = int(raw_target_id)
                        target = db.execute(
                            "SELECT batch_id,status,payload_text FROM publication_targets WHERE id=?",
                            (target_id,),
                        ).fetchone()
                        if not target or int(target["batch_id"]) != batch_id:
                            raise ValueError(f"Ціль #{target_id} пакета #{batch_id} зникла.")
                        if str(target["status"]) == "sent":
                            raise ValueError(f"Ціль #{target_id} пакета #{batch_id} вже опублікована.")
                        expected_payloads = item.get("expected_payloads", {})
                        if isinstance(expected_payloads, dict):
                            expected_payload = expected_payloads.get(target_id, expected_payloads.get(str(target_id)))
                            if expected_payload is not None and str(target["payload_text"]) != str(expected_payload):
                                raise ValueError(f"Текст цілі #{target_id} уже змінено.")
                        if not str(new_payload).strip():
                            raise ValueError(f"Новий текст цілі #{target_id} порожній.")
                    checked.append((item, row))

                cursor = db.execute(
                    """
                    INSERT INTO queue_text_migrations(
                        migration_key,backup_path,summary_json,completed_at
                    ) VALUES(?,?,?,?)
                    """,
                    (
                        str(migration_key),
                        str(backup_path),
                        json.dumps({"items": len(checked)}, ensure_ascii=False, sort_keys=True),
                        now,
                    ),
                )
                migration_id = int(cursor.lastrowid)
                for item, _row in checked:
                    batch_id = int(item["batch_id"])
                    group_id = int(item["group_id"])
                    old_text = str(item["old_text"]).strip()
                    new_text = str(item["new_text"]).strip()
                    limit_value = int(item["limit"])
                    platforms = item.get("platforms", [])
                    platform_texts = {str(platform): new_text for platform in platforms}
                    platform_json = json.dumps(platform_texts, ensure_ascii=False, sort_keys=True)
                    db.execute(
                        """
                        UPDATE news_groups SET rewrite_text=?,platform_texts_json=?,updated_at=?
                        WHERE id=?
                        """,
                        (new_text, platform_json, now, group_id),
                    )
                    db.execute(
                        """
                        UPDATE articles SET rewrite_text=?,platform_texts_json=? WHERE group_id=?
                        """,
                        (new_text, platform_json, group_id),
                    )
                    payloads = item["payloads"]
                    assert isinstance(payloads, dict)
                    for raw_target_id, new_payload in payloads.items():
                        db.execute(
                            """
                            UPDATE publication_targets SET payload_text=?,updated_at=?
                            WHERE id=? AND batch_id=? AND status!='sent'
                            """,
                            (str(new_payload), now, int(raw_target_id), batch_id),
                        )
                    db.execute(
                        """
                        INSERT INTO queue_text_migration_items(
                            migration_id,batch_id,group_id,old_text,new_text,old_length,
                            new_length,limit_value,created_at
                        ) VALUES(?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            migration_id,batch_id,group_id,old_text,new_text,len(old_text),
                            len(new_text),limit_value,now,
                        ),
                    )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        self.quick_check()
        return len(updates)

    def quick_check(self) -> None:
        with self.connect() as db:
            result = db.execute("PRAGMA quick_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"SQLite quick_check failed: {result}")

    def archive_stale_groups(self) -> int:
        """Archive unqueued editorial blocks that contain no Kyiv-today article."""
        archived = 0
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT g.id,g.status,a.published_at FROM news_groups g
                JOIN articles a ON a.group_id=g.id
                WHERE g.status IN ('new','draft','rejected')
                ORDER BY g.id
                """
            ).fetchall()
            by_group: dict[int, list[str | None]] = {}
            for row in rows:
                by_group.setdefault(int(row["id"]), []).append(row["published_at"])
            for group_id, dates in by_group.items():
                if any(is_today_kyiv(value) for value in dates):
                    continue
                db.execute(
                    "UPDATE news_groups SET status='archived',updated_at=? WHERE id=?",
                    (_iso(), group_id),
                )
                db.execute("UPDATE articles SET status='archived' WHERE group_id=?", (group_id,))
                archived += 1
        return archived

    # Sources
    def add_source(self, kind: str, name: str, url: str) -> int:
        with self.connect() as db:
            cursor = db.execute(
                "INSERT INTO sources(kind,name,url,created_at) VALUES(?,?,?,?)",
                (kind, name.strip(), url.strip(), _iso()),
            )
            return int(cursor.lastrowid)

    def update_source(self, source_id: int, *, name: str, url: str, enabled: bool) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE sources SET name=?, url=?, enabled=? WHERE id=?",
                (name.strip(), url.strip(), int(enabled), source_id),
            )

    def delete_source(self, source_id: int) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM sources WHERE id=?", (source_id,))
            db.execute("DELETE FROM news_groups WHERE id NOT IN (SELECT DISTINCT group_id FROM articles WHERE group_id IS NOT NULL)")

    def list_sources(self, *, enabled_only: bool = False) -> list[Source]:
        query = "SELECT * FROM sources"
        if enabled_only:
            query += " WHERE enabled=1"
        query += " ORDER BY name COLLATE NOCASE"
        with self.connect() as db:
            rows = db.execute(query).fetchall()
        return [
            Source(row["id"], row["kind"], row["name"], row["url"], bool(row["enabled"]), row["last_checked_at"])
            for row in rows
        ]

    def mark_source_checked(self, source_id: int) -> None:
        with self.connect() as db:
            db.execute("UPDATE sources SET last_checked_at=? WHERE id=?", (_iso(), source_id))

    # Collection and grouping
    def _candidate_groups(self, db: sqlite3.Connection) -> list[tuple[int, list[Article]]]:
        group_rows = db.execute(
            "SELECT id FROM news_groups WHERE status!='archived' ORDER BY updated_at DESC LIMIT 300"
        ).fetchall()
        result: list[tuple[int, list[Article]]] = []
        for row in group_rows:
            articles = self._articles_for_group_connection(db, int(row["id"]))
            if articles and any(is_today_kyiv(item.published_at) for item in articles):
                result.append((int(row["id"]), articles))
        return result

    def insert_collected(
        self,
        source_id: int,
        items: list[CollectedArticle],
        *,
        enforce_today: bool = True,
    ) -> int:
        inserted = 0
        affected_groups: set[int] = set()
        # Enforce the workflow at the database boundary as well as in collectors.
        # This prevents a buggy feed parser or future import path from quietly
        # filling the inbox with yesterday's material.
        today_items = [item for item in items if (not enforce_today or is_today_kyiv(item.published_at))]
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                exclusion_rows = db.execute(
                    "SELECT source_text FROM content_exclusions WHERE active=1 ORDER BY updated_at DESC LIMIT 500"
                ).fetchall()
                exclusion_texts = [str(row["source_text"] or "") for row in exclusion_rows]
                # FIX26: automatic semantic grouping is disabled. Every collected
                # material gets its own editorial block; the user can merge blocks
                # manually when the relationship is genuinely clear.
                for item in today_items:
                    normalized = "\n".join(line.strip() for line in item.raw_text.splitlines() if line.strip())
                    if not normalized:
                        continue
                    candidate_for_exclusion = f"{item.title.strip()}\n{normalized}"
                    if any(
                        matches_content_exclusion(candidate_for_exclusion, excluded)
                        for excluded in exclusion_texts
                        if excluded
                    ):
                        # This is a deliberate editor preference, not an API error
                        # and not a duplicate. The source is still marked checked,
                        # but the item never enters the inbox.
                        continue
                    content_hash = sha256_bytes((item.title.strip() + "\n" + normalized).encode("utf-8"))
                    duplicate = db.execute(
                        "SELECT 1 FROM articles WHERE (source_id=? AND external_id=?) OR content_hash=? LIMIT 1",
                        (source_id, item.external_id, content_hash),
                    ).fetchone()
                    if duplicate:
                        continue
                    now = _iso()
                    cursor = db.execute(
                        "INSERT INTO news_groups(canonical_title,created_at,updated_at) VALUES(?,?,?)",
                        (item.title.strip() or "Без заголовка", now, now),
                    )
                    group_id = int(cursor.lastrowid)
                    cursor = db.execute(
                        """
                        INSERT INTO articles(
                            source_id,group_id,external_id,content_hash,title,url,raw_text,published_at,discovered_at
                        ) VALUES(?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            source_id,
                            group_id,
                            item.external_id,
                            content_hash,
                            item.title.strip() or "Без заголовка",
                            item.url,
                            normalized,
                            item.published_at,
                            _iso(),
                        ),
                    )
                    # The inserted article intentionally remains the only source in
                    # this new block until the user performs a manual merge.
                    db.execute(
                        """
                        UPDATE news_groups SET updated_at=?,explosiveness_score=0,
                            explosiveness_confidence=0,explosiveness_details_json='{}',
                            recommended_platforms_json='[]' WHERE id=?
                        """,
                        (_iso(), group_id),
                    )
                    affected_groups.add(group_id)
                    inserted += 1
                db.execute("UPDATE sources SET last_checked_at=? WHERE id=?", (_iso(), source_id))
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        # Give every new/updated block an immediate local score. A later editor
        # refresh may enrich it with Threads keyword search, but the inbox is
        # never left with a decorative dash pretending to be analysis.
        for group_id in sorted(affected_groups):
            group = self.get_group(group_id)
            score, confidence, details, recommendations = calculate_explosiveness(group, None)
            self.set_group_analysis(
                group_id,
                score=score,
                confidence=confidence,
                details=details,
                recommendations=recommendations,
            )
        return inserted

    # Groups
    def list_groups(self, status: str | None = None, limit: int = 200) -> list[NewsGroup]:
        query = """
            SELECT g.*,
                   COUNT(a.id) AS source_count,
                   MIN(a.published_at) AS first_published_at,
                   MAX(a.published_at) AS last_published_at
            FROM news_groups g JOIN articles a ON a.group_id=g.id
        """
        params: list[object] = []
        if status == "approved":
            # Approved stories leave the working inbox after 24 hours. They remain
            # available in Publication History, while still-active queue packages
            # stay reachable for editing and recovery.
            query += """
                WHERE g.status='approved' AND (
                    julianday(g.updated_at) >= julianday('now','-1 day') OR EXISTS (
                        SELECT 1 FROM publication_batches b
                        JOIN articles qa ON qa.id=b.article_id
                        WHERE qa.group_id=g.id AND b.status IN ('pending','in_progress','paused')
                    )
                )
            """
        elif status:
            query += " WHERE g.status=?"
            params.append(status)
        else:
            query += """
                WHERE g.status IN ('new','draft') OR (g.status='approved' AND (
                    julianday(g.updated_at) >= julianday('now','-1 day') OR EXISTS (
                        SELECT 1 FROM publication_batches b
                        JOIN articles qa ON qa.id=b.article_id
                        WHERE qa.group_id=g.id AND b.status IN ('pending','in_progress','paused')
                    )
                ))
            """
        query += " GROUP BY g.id ORDER BY COALESCE(MAX(a.published_at),g.updated_at) DESC LIMIT ?"
        params.append(limit)
        with self.connect() as db:
            rows = db.execute(query, params).fetchall()
        return [self._group_from_row(row, []) for row in rows]

    def get_group(self, group_id: int) -> NewsGroup:
        with self.connect() as db:
            row = db.execute(
                """
                SELECT g.*, COUNT(a.id) AS source_count,
                       MIN(a.published_at) AS first_published_at,
                       MAX(a.published_at) AS last_published_at
                FROM news_groups g JOIN articles a ON a.group_id=g.id
                WHERE g.id=? GROUP BY g.id
                """,
                (group_id,),
            ).fetchone()
            if not row:
                raise KeyError(group_id)
            articles = self._articles_for_group_connection(db, group_id)
        return self._group_from_row(row, articles)

    @staticmethod
    def _safe_json(value: str, fallback: object) -> object:
        try:
            parsed = json.loads(value or "")
        except json.JSONDecodeError:
            return fallback
        return parsed

    def _group_from_row(self, row: sqlite3.Row, articles: list[Article]) -> NewsGroup:
        platform_texts = self._safe_json(str(row["platform_texts_json"] or "{}"), {})
        details = self._safe_json(str(row["explosiveness_details_json"] or "{}"), {})
        recommendations = self._safe_json(str(row["recommended_platforms_json"] or "[]"), [])
        return NewsGroup(
            id=int(row["id"]),
            canonical_title=str(row["canonical_title"]),
            status=str(row["status"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            source_count=int(row["source_count"] or 0),
            first_published_at=row["first_published_at"],
            last_published_at=row["last_published_at"],
            headline=str(row["headline"] or ""),
            fact_card=str(row["fact_card"] or ""),
            rewrite_text=str(row["rewrite_text"] or ""),
            ai_draft_text=str(row["ai_draft_text"] or "") if "ai_draft_text" in row.keys() else "",
            platform_texts=platform_texts if isinstance(platform_texts, dict) else {},
            include_source_link=bool(row["include_source_link"]),
            media_drive_url=str(row["media_drive_url"] or ""),
            media_file_id=str(row["media_file_id"] or ""),
            media_name=str(row["media_name"] or ""),
            media_kind=str(row["media_kind"] or ""),
            media_mime=str(row["media_mime"] or ""),
            media_size=int(row["media_size"] or 0),
            explosiveness_score=int(row["explosiveness_score"] or 0),
            explosiveness_confidence=int(row["explosiveness_confidence"] or 0),
            explosiveness_details=details if isinstance(details, dict) else {},
            recommended_platforms=[str(item) for item in recommendations] if isinstance(recommendations, list) else [],
            articles=articles,
        )

    def _articles_for_group_connection(self, db: sqlite3.Connection, group_id: int) -> list[Article]:
        rows = db.execute(
            """
            SELECT a.*, s.name AS source_name FROM articles a
            JOIN sources s ON s.id=a.source_id
            WHERE a.group_id=? ORDER BY COALESCE(a.published_at,a.discovered_at),a.id
            """,
            (group_id,),
        ).fetchall()
        return [self._article_from_row(row) for row in rows]

    def set_group_status(self, group_id: int, status: str) -> None:
        if status not in {"new", "draft", "approved", "rejected", "archived"}:
            raise ValueError(status)
        legacy_status = "archived" if status in {"rejected", "archived"} else status
        with self.connect() as db:
            cursor = db.execute("UPDATE news_groups SET status=?,updated_at=? WHERE id=?", (status, _iso(), group_id))
            if cursor.rowcount != 1:
                raise KeyError(group_id)
            db.execute("UPDATE articles SET status=? WHERE group_id=?", (legacy_status, group_id))

    def set_groups_status(self, group_ids: Iterable[int], status: str) -> int:
        """Atomically apply one editorial status to several blocks."""
        if status not in {"new", "draft", "approved", "rejected", "archived"}:
            raise ValueError(status)
        ordered: list[int] = []
        for raw in group_ids:
            group_id = int(raw)
            if group_id not in ordered:
                ordered.append(group_id)
        if not ordered:
            return 0
        placeholders = ",".join("?" for _ in ordered)
        legacy_status = "archived" if status in {"rejected", "archived"} else status
        now = _iso()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                found = {
                    int(row[0])
                    for row in db.execute(
                        f"SELECT id FROM news_groups WHERE id IN ({placeholders})", ordered
                    ).fetchall()
                }
                missing = [group_id for group_id in ordered if group_id not in found]
                if missing:
                    raise KeyError(missing[0])
                db.execute(
                    f"UPDATE news_groups SET status=?,updated_at=? WHERE id IN ({placeholders})",
                    [status, now, *ordered],
                )
                db.execute(
                    f"UPDATE articles SET status=? WHERE group_id IN ({placeholders})",
                    [legacy_status, *ordered],
                )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return len(ordered)

    def merge_groups(self, target_group_id: int, group_ids: Iterable[int]) -> int:
        """Merge several editorial blocks into one pre-publication block.

        The target keeps its canonical title, publication options and attached
        media. Every article from the other blocks is moved into the target.
        Derived editorial content is cleared because a rewrite made for only a
        subset of sources is no longer trustworthy after the merge.

        Blocks with publication history are deliberately rejected. Moving an
        article that anchors a queue package would silently change the package's
        group identity and could make already-sent targets appear to belong to a
        different story.
        """
        target_group_id = int(target_group_id)
        ordered_ids: list[int] = []
        for raw in group_ids:
            group_id = int(raw)
            if group_id not in ordered_ids:
                ordered_ids.append(group_id)
        if target_group_id not in ordered_ids:
            ordered_ids.insert(0, target_group_id)
        if len(ordered_ids) < 2:
            raise ValueError("Оберіть щонайменше два блоки для об’єднання.")

        placeholders = ",".join("?" for _ in ordered_ids)
        source_ids = [group_id for group_id in ordered_ids if group_id != target_group_id]
        source_placeholders = ",".join("?" for _ in source_ids)

        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                rows = db.execute(
                    f"""
                    SELECT id,status,canonical_title,media_drive_url,media_file_id
                    FROM news_groups WHERE id IN ({placeholders})
                    """,
                    ordered_ids,
                ).fetchall()
                found = {int(row["id"]): row for row in rows}
                missing = [group_id for group_id in ordered_ids if group_id not in found]
                if missing:
                    raise KeyError(missing[0])

                queued_rows = db.execute(
                    f"""
                    SELECT DISTINCT a.group_id
                    FROM publication_batches b
                    JOIN articles a ON a.id=b.article_id
                    WHERE a.group_id IN ({placeholders})
                    ORDER BY a.group_id
                    """,
                    ordered_ids,
                ).fetchall()
                if queued_rows:
                    shown = ", ".join(f"#{int(row[0])}" for row in queued_rows[:8])
                    raise ValueError(
                        f"Не можна об’єднати блоки з історією публікації або чергою: {shown}. "
                        "Це захищає вже опубліковані цілі від дублювання."
                    )

                protected = [
                    group_id
                    for group_id in ordered_ids
                    if str(found[group_id]["status"]) in {"approved", "archived"}
                ]
                if protected:
                    shown = ", ".join(f"#{item}" for item in protected[:8])
                    raise ValueError(
                        f"Не можна об’єднати схвалені або архівні блоки: {shown}. "
                        "Об’єднання виконуйте до постановки новини в чергу."
                    )

                media_sources = [
                    group_id
                    for group_id in source_ids
                    if str(found[group_id]["media_file_id"] or "").strip()
                    or str(found[group_id]["media_drive_url"] or "").strip()
                ]
                if media_sources:
                    shown = ", ".join(f"#{item}" for item in media_sources[:8])
                    raise ValueError(
                        f"У додаткових блоках уже прикріплено медіа: {shown}. "
                        "Щоб не втратити файл, приберіть медіа з цих блоків або зробіть потрібний блок основним."
                    )

                moved_articles = int(
                    db.execute(
                        f"SELECT COUNT(*) FROM articles WHERE group_id IN ({source_placeholders})",
                        source_ids,
                    ).fetchone()[0]
                    or 0
                )
                if moved_articles <= 0:
                    raise ValueError("У вибраних додаткових блоках немає джерел для об’єднання.")

                db.execute(
                    f"UPDATE articles SET group_id=? WHERE group_id IN ({source_placeholders})",
                    [target_group_id, *source_ids],
                )
                db.execute(
                    f"DELETE FROM news_groups WHERE id IN ({source_placeholders})",
                    source_ids,
                )

                now = _iso()
                db.execute(
                    """
                    UPDATE news_groups
                    SET status='new',headline='',fact_card='',rewrite_text='',ai_draft_text='',platform_texts_json='{}',
                        explosiveness_score=0,explosiveness_confidence=0,
                        explosiveness_details_json='{}',recommended_platforms_json='[]',updated_at=?
                    WHERE id=?
                    """,
                    (now, target_group_id),
                )
                db.execute(
                    """
                    UPDATE articles
                    SET status='new',headline='',fact_card='',rewrite_text='',platform_texts_json='{}'
                    WHERE group_id=?
                    """,
                    (target_group_id,),
                )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise

        merged = self.get_group(target_group_id)
        score, confidence, details, recommendations = calculate_explosiveness(merged, None)
        self.set_group_analysis(
            target_group_id,
            score=score,
            confidence=confidence,
            details=details,
            recommendations=recommendations,
        )
        return moved_articles

    def save_group_rewrite(
        self,
        group_id: int,
        *,
        headline: str,
        fact_card: str,
        rewrite_text: str,
        platform_texts: dict[str, str],
    ) -> None:
        with self.connect() as db:
            cursor = db.execute(
                """
                UPDATE news_groups SET headline=?,fact_card=?,rewrite_text=?,platform_texts_json=?,
                       status='draft',updated_at=? WHERE id=?
                """,
                (
                    headline.strip(),
                    fact_card.strip(),
                    rewrite_text.strip(),
                    json.dumps(platform_texts, ensure_ascii=False, sort_keys=True),
                    _iso(),
                    group_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(group_id)
            # Keep the legacy article projection synchronized. Older UI/tests and
            # existing backups still read these fields directly from the lead article.
            db.execute(
                """
                UPDATE articles SET headline=?,fact_card=?,rewrite_text=?,platform_texts_json=?,status='draft'
                WHERE group_id=?
                """,
                (
                    headline.strip(),
                    fact_card.strip(),
                    rewrite_text.strip(),
                    json.dumps(platform_texts, ensure_ascii=False, sort_keys=True),
                    group_id,
                ),
            )

    def set_group_ai_draft(self, group_id: int, ai_draft_text: str) -> None:
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE news_groups SET ai_draft_text=?,updated_at=? WHERE id=?",
                (str(ai_draft_text or "").strip(), _iso(), int(group_id)),
            )
        if cursor.rowcount != 1:
            raise KeyError(group_id)

    def list_editorial_examples(
        self,
        limit: int = 500,
        *,
        language: str | None = None,
    ) -> list[dict[str, object]]:
        query = (
            "SELECT id,group_id,source_text,ai_draft_text,final_text,headline,language,created_at "
            "FROM editorial_examples"
        )
        params: list[object] = []
        if language is not None:
            query += " WHERE language=?"
            params.append("en" if str(language).lower() == "en" else "uk")
        query += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, int(limit)))
        with self.connect() as db:
            rows = db.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def editorial_example_count(self, *, language: str | None = None) -> int:
        with self.connect() as db:
            if language is None:
                row = db.execute("SELECT COUNT(*) FROM editorial_examples").fetchone()
            else:
                row = db.execute(
                    "SELECT COUNT(*) FROM editorial_examples WHERE language=?",
                    ("en" if str(language).lower() == "en" else "uk",),
                ).fetchone()
        return int(row[0] or 0)

    def record_editorial_example(
        self,
        group_id: int,
        *,
        final_text: str,
        headline: str,
        language: str = "uk",
    ) -> bool:
        group = self.get_group(int(group_id))
        source_text = group.combined_text.strip()
        final = str(final_text or "").strip()
        if not source_text or not final:
            return False
        lang = "en" if str(language).lower() == "en" else "uk"
        fingerprint = hashlib.sha256(f"{lang}\0{source_text}".encode("utf-8")).hexdigest()
        with self.connect() as db:
            cursor = db.execute(
                """
                INSERT OR IGNORE INTO editorial_examples(
                    group_id,source_fingerprint,source_text,ai_draft_text,final_text,headline,language,created_at
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    int(group_id),
                    fingerprint,
                    source_text,
                    group.ai_draft_text,
                    final,
                    str(headline or "").strip(),
                    lang,
                    _iso(),
                ),
            )
        return cursor.rowcount == 1

    @staticmethod
    def _group_learning_text_connection(db: sqlite3.Connection, group_id: int) -> str:
        rows = db.execute(
            """
            SELECT a.title,a.raw_text,s.name AS source_name
            FROM articles a JOIN sources s ON s.id=a.source_id
            WHERE a.group_id=? ORDER BY a.id
            """,
            (int(group_id),),
        ).fetchall()
        blocks = [
            f"{str(row['source_name'] or '')}: {str(row['title'] or '')}. {str(row['raw_text'] or '')}"
            for row in rows
        ]
        return "\n".join(blocks).strip()

    def record_topic_feedback(
        self,
        anchor_text: str,
        candidate_text: str,
        *,
        decision: str = "merged",
        language: str = "uk",
    ) -> bool:
        if decision not in {"merged", "not_related"}:
            raise ValueError(decision)
        left = " ".join(str(anchor_text or "").split())
        right = " ".join(str(candidate_text or "").split())
        if not left or not right:
            return False
        lang = "en" if str(language).lower() == "en" else "uk"
        left_sig = hashlib.sha256(f"{lang}\0{left}".encode("utf-8")).hexdigest()
        right_sig = hashlib.sha256(f"{lang}\0{right}".encode("utf-8")).hexdigest()
        if right_sig < left_sig:
            left_sig, right_sig = right_sig, left_sig
            left, right = right, left
        with self.connect() as db:
            cursor = db.execute(
                """
                INSERT OR IGNORE INTO topic_merge_feedback(
                    anchor_signature,candidate_signature,decision,anchor_text,candidate_text,language,created_at
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    left_sig, right_sig, decision, left, right,
                    lang, _iso(),
                ),
            )
        return cursor.rowcount == 1

    def list_topic_feedback(
        self,
        limit: int = 1000,
        *,
        language: str | None = None,
    ) -> list[dict[str, object]]:
        query = "SELECT id,decision,anchor_text,candidate_text,language,created_at FROM topic_merge_feedback"
        params: list[object] = []
        if language is not None:
            query += " WHERE language=?"
            params.append("en" if str(language).lower() == "en" else "uk")
        query += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, int(limit)))
        with self.connect() as db:
            rows = db.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def topic_candidate_rows(self, anchor_group_id: int, limit: int = 250) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for group in self.list_groups(limit=max(1, int(limit))):
            if group.id == int(anchor_group_id):
                continue
            rows.append(
                {
                    "group_id": group.id,
                    "title": group.canonical_title,
                    "text": group.combined_text or group.canonical_title,
                    "source_count": group.source_count,
                    "published_at": group.last_published_at or "",
                    "url": group.primary_url,
                }
            )
        return rows

    def remember_content_exclusions(self, group_ids: Iterable[int]) -> int:
        """Remember selected blocks as future inbox exclusions and reject them now.

        A merged block can contain several differently worded reports. Store one
        local example per article so a future item can match any of them instead of
        being diluted against one enormous concatenated text.
        """

        ids = [int(value) for value in group_ids]
        if not ids:
            return 0
        remembered = 0
        now = _iso()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                for group_id in ids:
                    group_row = db.execute(
                        "SELECT canonical_title FROM news_groups WHERE id=?",
                        (group_id,),
                    ).fetchone()
                    if not group_row:
                        continue
                    articles = self._articles_for_group_connection(db, group_id)
                    for article in articles:
                        source_text = f"{article.title}\n{article.raw_text}".strip()
                        if not source_text:
                            continue
                        signature = sha256_bytes(source_text.casefold().encode("utf-8"))
                        cursor = db.execute(
                            """
                            INSERT INTO content_exclusions(
                                group_id,signature,title,source_text,active,created_at,updated_at
                            ) VALUES(?,?,?,?,1,?,?)
                            ON CONFLICT(signature) DO UPDATE SET
                                group_id=excluded.group_id,
                                title=excluded.title,
                                source_text=excluded.source_text,
                                active=1,
                                updated_at=excluded.updated_at
                            """,
                            (group_id, signature, article.title, source_text, now, now),
                        )
                        remembered += 1 if cursor.rowcount else 0
                    db.execute(
                        "UPDATE news_groups SET status='rejected',updated_at=? WHERE id=?",
                        (now, group_id),
                    )
                    db.execute("UPDATE articles SET status='archived' WHERE group_id=?", (group_id,))
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return remembered

    def forget_content_exclusion_for_group(self, group_id: int) -> int:
        """Deactivate an exclusion when the editor restores the old block."""

        with self.connect() as db:
            cursor = db.execute(
                "UPDATE content_exclusions SET active=0,updated_at=? WHERE group_id=? AND active=1",
                (_iso(), int(group_id)),
            )
        return int(cursor.rowcount or 0)

    def list_content_exclusions(self, *, active_only: bool = True, limit: int = 500) -> list[dict[str, object]]:
        query = "SELECT id,group_id,signature,title,source_text,active,created_at,updated_at FROM content_exclusions"
        params: list[object] = []
        if active_only:
            query += " WHERE active=1"
        query += " ORDER BY updated_at DESC,id DESC LIMIT ?"
        params.append(max(1, int(limit)))
        with self.connect() as db:
            rows = db.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def content_exclusion_count(self) -> int:
        with self.connect() as db:
            row = db.execute("SELECT COUNT(*) FROM content_exclusions WHERE active=1").fetchone()
        return int(row[0] or 0)

    def deactivate_content_exclusions(self, exclusion_ids: Iterable[int]) -> int:
        ids = sorted({int(value) for value in exclusion_ids if int(value) > 0})
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        with self.connect() as db:
            cursor = db.execute(
                f"UPDATE content_exclusions SET active=0,updated_at=? "
                f"WHERE active=1 AND id IN ({placeholders})",
                [_iso(), *ids],
            )
        return int(cursor.rowcount or 0)

    def clear_content_exclusions(self) -> int:
        """Deactivate all future-content exclusions without erasing audit history."""

        with self.connect() as db:
            cursor = db.execute(
                "UPDATE content_exclusions SET active=0,updated_at=? WHERE active=1",
                (_iso(),),
            )
        return int(cursor.rowcount or 0)

    def record_learning_event(
        self,
        event_type: str,
        *,
        language: str = "uk",
        group_id: int | None = None,
        anchor_group_id: int | None = None,
        payload: dict[str, object] | None = None,
    ) -> int:
        event = str(event_type or "").strip()
        if not event:
            raise ValueError("event_type is required")
        lang = "en" if str(language).lower() == "en" else "uk"
        with self.connect() as db:
            cursor = db.execute(
                """
                INSERT INTO learning_events(
                    event_type,language,group_id,anchor_group_id,payload_json,created_at
                ) VALUES(?,?,?,?,?,?)
                """,
                (
                    event, lang, group_id, anchor_group_id,
                    json.dumps(payload or {}, ensure_ascii=False, sort_keys=True), _iso(),
                ),
            )
        return int(cursor.lastrowid)

    def list_learning_events(
        self,
        *,
        language: str | None = None,
        event_type: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, object]]:
        query = "SELECT * FROM learning_events"
        clauses: list[str] = []
        params: list[object] = []
        if language is not None:
            clauses.append("language=?")
            params.append("en" if str(language).lower() == "en" else "uk")
        if event_type:
            clauses.append("event_type=?")
            params.append(str(event_type))
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, int(limit)))
        with self.connect() as db:
            rows = db.execute(query, params).fetchall()
        result: list[dict[str, object]] = []
        for row in rows:
            item = dict(row)
            item["payload"] = self._safe_json(str(item.pop("payload_json", "{}")), {})
            result.append(item)
        return result

    def learning_stats(self) -> dict[str, object]:
        with self.connect() as db:
            events = int(db.execute("SELECT COUNT(*) FROM learning_events").fetchone()[0] or 0)
            examples = {
                str(row["language"]): int(row["count"] or 0)
                for row in db.execute(
                    "SELECT language,COUNT(*) AS count FROM editorial_examples GROUP BY language"
                ).fetchall()
            }
            feedback = int(db.execute("SELECT COUNT(*) FROM topic_merge_feedback").fetchone()[0] or 0)
            exclusions = int(db.execute("SELECT COUNT(*) FROM content_exclusions WHERE active=1").fetchone()[0] or 0)
        return {
            "events": events,
            "editorial_examples": examples,
            "topic_feedback": feedback,
            "active_exclusions": exclusions,
        }

    def export_learning_data(self, path: Path) -> Path:
        payload = {
            "format": "UA_FREE_LEARNING_V1",
            "exported_at": _iso(),
            "editorial_examples": self.list_editorial_examples(limit=100000),
            "topic_feedback": self.list_topic_feedback(limit=100000),
            "content_exclusions": self.list_content_exclusions(active_only=False, limit=100000),
            "learning_events": self.list_learning_events(limit=100000),
        }
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        return target

    def import_learning_data(self, path: Path) -> dict[str, int]:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("format") != "UA_FREE_LEARNING_V1":
            raise ValueError("Unsupported learning-data file.")
        counts = {"editorial_examples": 0, "topic_feedback": 0, "content_exclusions": 0, "learning_events": 0}
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                for row in payload.get("editorial_examples", []):
                    if not isinstance(row, dict):
                        continue
                    cursor = db.execute(
                        """
                        INSERT OR IGNORE INTO editorial_examples(
                            group_id,source_fingerprint,source_text,ai_draft_text,final_text,headline,language,created_at
                        ) VALUES(?,?,?,?,?,?,?,?)
                        """,
                        (
                            row.get("group_id"),
                            hashlib.sha256(str(row.get("source_text") or "").encode("utf-8")).hexdigest(),
                            str(row.get("source_text") or ""),
                            str(row.get("ai_draft_text") or ""),
                            str(row.get("final_text") or ""),
                            str(row.get("headline") or ""),
                            "en" if str(row.get("language") or "uk").lower() == "en" else "uk",
                            str(row.get("created_at") or _iso()),
                        ),
                    )
                    counts["editorial_examples"] += int(bool(cursor.rowcount))
                for row in payload.get("topic_feedback", []):
                    if not isinstance(row, dict):
                        continue
                    left = " ".join(str(row.get("anchor_text") or "").split())
                    right = " ".join(str(row.get("candidate_text") or "").split())
                    if not left or not right:
                        continue
                    left_sig = hashlib.sha256(left.encode("utf-8")).hexdigest()
                    right_sig = hashlib.sha256(right.encode("utf-8")).hexdigest()
                    if right_sig < left_sig:
                        left_sig, right_sig, left, right = right_sig, left_sig, right, left
                    cursor = db.execute(
                        """
                        INSERT OR IGNORE INTO topic_merge_feedback(
                            anchor_signature,candidate_signature,decision,anchor_text,candidate_text,language,created_at
                        ) VALUES(?,?,?,?,?,?,?)
                        """,
                        (left_sig, right_sig, str(row.get("decision") or "merged"), left, right,
                         "en" if str(row.get("language") or "uk").lower() == "en" else "uk",
                         str(row.get("created_at") or _iso())),
                    )
                    counts["topic_feedback"] += int(bool(cursor.rowcount))
                for row in payload.get("content_exclusions", []):
                    if not isinstance(row, dict):
                        continue
                    source_text = str(row.get("source_text") or "").strip()
                    if not source_text:
                        continue
                    signature = str(row.get("signature") or "").strip()
                    if not signature:
                        signature = sha256_bytes(source_text.casefold().encode("utf-8"))
                    cursor = db.execute(
                        """
                        INSERT INTO content_exclusions(
                            group_id,signature,title,source_text,active,created_at,updated_at
                        ) VALUES(?,?,?,?,?,?,?)
                        ON CONFLICT(signature) DO UPDATE SET
                            title=excluded.title,
                            source_text=excluded.source_text,
                            active=excluded.active,
                            updated_at=excluded.updated_at
                        """,
                        (
                            row.get("group_id"), signature, str(row.get("title") or ""), source_text,
                            1 if bool(row.get("active", True)) else 0,
                            str(row.get("created_at") or _iso()),
                            str(row.get("updated_at") or _iso()),
                        ),
                    )
                    counts["content_exclusions"] += int(bool(cursor.rowcount))
                for row in payload.get("learning_events", []):
                    if not isinstance(row, dict):
                        continue
                    cursor = db.execute(
                        """
                        INSERT INTO learning_events(
                            event_type,language,group_id,anchor_group_id,payload_json,created_at
                        ) VALUES(?,?,?,?,?,?)
                        """,
                        (str(row.get("event_type") or "imported"),
                         "en" if str(row.get("language") or "uk").lower() == "en" else "uk",
                         row.get("group_id"), row.get("anchor_group_id"),
                         json.dumps(row.get("payload") or {}, ensure_ascii=False, sort_keys=True),
                         str(row.get("created_at") or _iso())),
                    )
                    counts["learning_events"] += int(bool(cursor.rowcount))
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return counts

    def clear_learning_history(self) -> None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute("DELETE FROM editorial_examples")
                db.execute("DELETE FROM topic_merge_feedback")
                db.execute("DELETE FROM learning_events")
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise

    def set_group_options(self, group_id: int, *, include_source_link: bool) -> None:
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE news_groups SET include_source_link=?,updated_at=? WHERE id=?",
                (int(include_source_link), _iso(), group_id),
            )
        if cursor.rowcount != 1:
            raise KeyError(group_id)

    def set_group_media(self, group_id: int, *, drive_url: str, file_id: str, name: str, kind: str, mime: str, size: int) -> None:
        with self.connect() as db:
            cursor = db.execute(
                """
                UPDATE news_groups SET media_drive_url=?,media_file_id=?,media_name=?,media_kind=?,
                       media_mime=?,media_size=?,updated_at=? WHERE id=?
                """,
                (drive_url.strip(), file_id, name, kind, mime, int(size), _iso(), group_id),
            )
        if cursor.rowcount != 1:
            raise KeyError(group_id)

    def clear_group_media(self, group_id: int) -> None:
        self.set_group_media(group_id, drive_url="", file_id="", name="", kind="", mime="", size=0)

    def set_group_analysis(self, group_id: int, *, score: int, confidence: int, details: dict[str, object], recommendations: list[str]) -> None:
        with self.connect() as db:
            cursor = db.execute(
                """
                UPDATE news_groups SET explosiveness_score=?,explosiveness_confidence=?,
                    explosiveness_details_json=?,recommended_platforms_json=?,updated_at=? WHERE id=?
                """,
                (
                    int(score),
                    int(confidence),
                    json.dumps(details, ensure_ascii=False, sort_keys=True),
                    json.dumps(recommendations, ensure_ascii=False),
                    _iso(),
                    group_id,
                ),
            )
        if cursor.rowcount != 1:
            raise KeyError(group_id)

    def lead_article_id(self, group_id: int) -> int:
        with self.connect() as db:
            row = db.execute("SELECT id FROM articles WHERE group_id=? ORDER BY id LIMIT 1", (group_id,)).fetchone()
        if not row:
            raise KeyError(group_id)
        return int(row[0])

    def group_id_for_article(self, article_id: int) -> int:
        with self.connect() as db:
            row = db.execute("SELECT group_id FROM articles WHERE id=?", (article_id,)).fetchone()
        if not row or row[0] is None:
            raise KeyError(article_id)
        return int(row[0])

    # Legacy article-facing helpers retained for tests and backup compatibility.
    def list_articles(self, status: str | None = None, limit: int = 200) -> list[Article]:
        query = "SELECT a.*,s.name AS source_name FROM articles a JOIN sources s ON s.id=a.source_id"
        params: list[object] = []
        if status:
            query += " WHERE a.status=?"
            params.append(status)
        query += " ORDER BY a.discovered_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as db:
            rows = db.execute(query, params).fetchall()
        return [self._article_from_row(row) for row in rows]

    def get_article(self, article_id: int) -> Article:
        with self.connect() as db:
            row = db.execute(
                "SELECT a.*,s.name AS source_name FROM articles a JOIN sources s ON s.id=a.source_id WHERE a.id=?",
                (article_id,),
            ).fetchone()
        if not row:
            raise KeyError(f"Article {article_id} not found")
        return self._article_from_row(row)

    @staticmethod
    def _article_from_row(row: sqlite3.Row) -> Article:
        keys = set(row.keys())
        return Article(
            id=int(row["id"]),
            source_id=int(row["source_id"]),
            title=str(row["title"]),
            url=str(row["url"]),
            raw_text=str(row["raw_text"]),
            status=str(row["status"]),
            rewrite_text=str(row["rewrite_text"] or ""),
            fact_card=str(row["fact_card"] or ""),
            headline=str(row["headline"] or ""),
            discovered_at=str(row["discovered_at"]),
            published_at=row["published_at"],
            group_id=int(row["group_id"]) if "group_id" in keys and row["group_id"] is not None else None,
            source_name=str(row["source_name"] or "") if "source_name" in keys else "",
        )

    def save_rewrite(self, article_id: int, *, headline: str, fact_card: str, rewrite_text: str, platform_texts: dict[str, str]) -> None:
        group_id = self.group_id_for_article(article_id)
        self.save_group_rewrite(
            group_id,
            headline=headline,
            fact_card=fact_card,
            rewrite_text=rewrite_text,
            platform_texts=platform_texts,
        )

    def get_platform_texts(self, article_id: int) -> dict[str, str]:
        return self.get_group(self.group_id_for_article(article_id)).platform_texts

    # Queue
    def latest_scheduled_at(self) -> str | None:
        with self.connect() as db:
            row = db.execute(
                """
                SELECT scheduled_at FROM publication_batches
                WHERE status!='cancelled'
                ORDER BY julianday(scheduled_at) DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
        return str(row[0]) if row and row[0] else None

    def queue_targets(
        self,
        article_id: int,
        scheduled_at: str,
        targets: dict[str, str],
    ) -> QueueUpdateResult:
        """Create or synchronize the one visible publication package for a news block.

        Sent targets are immutable and never duplicated. Pending/failed targets are
        updated to exactly match the current editor selection, so a user can add
        Facebook/Threads/LinkedIn after accidentally queueing only Telegram, or
        remove an unsent target before the worker reaches it.
        """
        if not targets:
            raise ValueError("Оберіть хоча б одну платформу для публікації.")
        scheduled_at = _normalize_scheduled_at(scheduled_at)
        cleaned = {str(platform).strip(): str(text).strip() for platform, text in targets.items()}
        if any(not platform or not text for platform, text in cleaned.items()):
            raise ValueError("Кожна вибрана платформа повинна мати непорожній текст.")
        group_id = self.group_id_for_article(article_id)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                existing = db.execute(
                    """
                    SELECT b.* FROM publication_batches b
                    JOIN articles a ON a.id=b.article_id
                    WHERE a.group_id=? AND b.status!='cancelled'
                    ORDER BY b.id DESC LIMIT 1
                    """,
                    (group_id,),
                ).fetchone()
                if existing and str(existing["status"]) == "in_progress":
                    raise ValueError(
                        f"Пакет #{existing['id']} зараз публікується. Дочекайтеся завершення операції й повторіть зміну."
                    )

                historical_sent = {
                    str(row["platform"])
                    for row in db.execute(
                        """
                        SELECT DISTINCT t.platform FROM publication_targets t
                        JOIN publication_batches b ON b.id=t.batch_id
                        JOIN articles a ON a.id=b.article_id
                        WHERE a.group_id=? AND t.status='sent'
                        """,
                        (group_id,),
                    ).fetchall()
                }
                requested = set(cleaned)
                preexisting_sent: list[str] = []
                if existing is None:
                    preexisting_sent = sorted(requested & historical_sent)
                    cleaned = {platform: text for platform, text in cleaned.items() if platform not in historical_sent}
                    if not cleaned:
                        previous = db.execute(
                            """
                            SELECT b.id,b.scheduled_at FROM publication_batches b
                            JOIN articles a ON a.id=b.article_id
                            WHERE a.group_id=? ORDER BY b.id DESC LIMIT 1
                            """,
                            (group_id,),
                        ).fetchone()
                        if not previous:
                            raise RuntimeError("Не вдалося знайти історію вже опублікованих платформ.")
                        db.execute("COMMIT")
                        return QueueUpdateResult(
                            batch_id=int(previous["id"]),
                            scheduled_at=str(previous["scheduled_at"]),
                            status="completed",
                            created=False,
                            already_sent=preexisting_sent,
                        )

                now = _iso()
                created = existing is None
                if existing is None:
                    cursor = db.execute(
                        """
                        INSERT INTO publication_batches(article_id,scheduled_at,status,created_at,updated_at)
                        VALUES(?,?,'pending',?,?)
                        """,
                        (article_id, scheduled_at, now, now),
                    )
                    batch_id = int(cursor.lastrowid)
                    current_schedule = scheduled_at
                    prior_status = "pending"
                    existing_targets: dict[str, sqlite3.Row] = {}
                else:
                    batch_id = int(existing["id"])
                    current_schedule = str(existing["scheduled_at"])
                    prior_status = str(existing["status"])
                    existing_targets = {
                        str(row["platform"]): row
                        for row in db.execute(
                            "SELECT * FROM publication_targets WHERE batch_id=? ORDER BY id",
                            (batch_id,),
                        ).fetchall()
                    }

                desired = set(cleaned)
                added: list[str] = []
                updated: list[str] = []
                removed: list[str] = []
                already_sent: list[str] = list(preexisting_sent)

                for platform, row in existing_targets.items():
                    if str(row["status"]) == "sent":
                        if platform in desired:
                            already_sent.append(platform)
                        continue
                    if platform not in desired:
                        db.execute("DELETE FROM publication_targets WHERE id=?", (int(row["id"]),))
                        removed.append(platform)

                for platform in sorted(desired):
                    row = existing_targets.get(platform)
                    if row is not None and str(row["status"]) == "sent":
                        continue
                    if row is None and platform in historical_sent:
                        already_sent.append(platform)
                        continue
                    if row is None:
                        db.execute(
                            """
                            INSERT INTO publication_targets(batch_id,platform,payload_text,status,updated_at)
                            VALUES(?,?,?,'pending',?)
                            """,
                            (batch_id, platform, cleaned[platform], now),
                        )
                        added.append(platform)
                    else:
                        db.execute(
                            """
                            UPDATE publication_targets
                            SET payload_text=?,status='pending',remote_id=NULL,last_error=NULL,
                                progress_json='{}',updated_at=?
                            WHERE id=?
                            """,
                            (cleaned[platform], now, int(row["id"])),
                        )
                        updated.append(platform)

                target_rows = db.execute(
                    "SELECT platform,status FROM publication_targets WHERE batch_id=? ORDER BY id",
                    (batch_id,),
                ).fetchall()
                if not target_rows:
                    db.execute(
                        """
                        UPDATE publication_batches SET status='cancelled',lease_owner=NULL,lease_until=NULL,
                            cleanup_error=NULL,updated_at=? WHERE id=?
                        """,
                        (now, batch_id),
                    )
                    db.execute("UPDATE news_groups SET status='draft',updated_at=? WHERE id=?", (now, group_id))
                    db.execute("UPDATE articles SET status='draft' WHERE group_id=?", (group_id,))
                    final_status = "cancelled"
                elif any(str(row["status"]) != "sent" for row in target_rows):
                    # Preserve a still-future slot while an existing pending package is
                    # merely edited. If that slot is already overdue, move the same package
                    # to the freshly calculated slot instead of leaving it marooned in the
                    # past. A completed package reopened with new platforms also gets the
                    # newly calculated slot.
                    current_due = _parse_aware_iso(current_schedule)
                    effective_schedule = (
                        scheduled_at
                        if prior_status == "completed" or current_due <= _now()
                        else _iso(current_due)
                    )
                    db.execute(
                        """
                        UPDATE publication_batches SET status='pending',scheduled_at=?,lease_owner=NULL,
                            lease_until=NULL,cleanup_error=NULL,updated_at=? WHERE id=?
                        """,
                        (effective_schedule, now, batch_id),
                    )
                    current_schedule = effective_schedule
                    db.execute("UPDATE news_groups SET status='approved',updated_at=? WHERE id=?", (now, group_id))
                    db.execute("UPDATE articles SET status='approved' WHERE group_id=?", (group_id,))
                    final_status = "pending"
                else:
                    media_row = db.execute(
                        "SELECT media_file_id FROM news_groups WHERE id=?",
                        (group_id,),
                    ).fetchone()
                    needs_cleanup = bool(media_row and str(media_row["media_file_id"] or "").strip())
                    if needs_cleanup:
                        # The worker owns permanent Drive deletion. Keep a cleanup-only
                        # package active instead of declaring completion in the editor.
                        db.execute(
                            """
                            UPDATE publication_batches SET status='pending',scheduled_at=?,lease_owner=NULL,
                                lease_until=NULL,updated_at=? WHERE id=?
                            """,
                            (current_schedule, now, batch_id),
                        )
                        final_status = "pending"
                    else:
                        db.execute(
                            """
                            UPDATE publication_batches SET status='completed',lease_owner=NULL,lease_until=NULL,
                                cleanup_error=NULL,updated_at=? WHERE id=?
                            """,
                            (now, batch_id),
                        )
                        final_status = "completed"
                    db.execute("UPDATE news_groups SET status='approved',updated_at=? WHERE id=?", (now, group_id))
                    db.execute("UPDATE articles SET status='approved' WHERE group_id=?", (group_id,))

                db.execute("COMMIT")
                return QueueUpdateResult(
                    batch_id=batch_id,
                    scheduled_at=current_schedule,
                    status=final_status,
                    created=created,
                    added=added,
                    updated=updated,
                    removed=removed,
                    already_sent=sorted(set(already_sent)),
                )
            except Exception:
                db.execute("ROLLBACK")
                raise

    def list_publication_history(self, limit: int = 500) -> list[dict[str, object]]:
        """Return one history row per batch that sent at least one target."""

        with self.connect() as db:
            rows = db.execute(
                """
                SELECT b.id AS batch_id,b.scheduled_at,b.status AS batch_status,
                       a.group_id,g.headline,g.canonical_title,g.rewrite_text,
                       t.id AS target_id,t.platform,t.status AS target_status,
                       t.remote_id,t.last_error,t.progress_json,t.updated_at
                FROM publication_batches b
                JOIN articles a ON a.id=b.article_id
                JOIN news_groups g ON g.id=a.group_id
                JOIN publication_targets t ON t.batch_id=b.id
                WHERE EXISTS (
                    SELECT 1 FROM publication_targets sent
                    WHERE sent.batch_id=b.id AND sent.status='sent'
                )
                ORDER BY b.id DESC,t.id
                """
            ).fetchall()
        grouped: dict[int, dict[str, object]] = {}
        for row in rows:
            batch_id = int(row["batch_id"])
            item = grouped.get(batch_id)
            if item is None:
                item = {
                    "batch_id": batch_id,
                    "group_id": int(row["group_id"]),
                    "headline": str(row["headline"] or row["canonical_title"] or ""),
                    "rewrite_text": str(row["rewrite_text"] or ""),
                    "scheduled_at": str(row["scheduled_at"] or ""),
                    "batch_status": str(row["batch_status"] or ""),
                    "published_at": "",
                    "targets": [],
                }
                grouped[batch_id] = item
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
            targets = item["targets"]
            assert isinstance(targets, list)
            targets.append(target)
            if target["status"] == "sent" and str(target["updated_at"]) > str(item["published_at"]):
                item["published_at"] = str(target["updated_at"])
        return list(grouped.values())[: max(1, int(limit))]

    def save_publication_metrics(
        self,
        target_id: int,
        *,
        metrics: dict[str, int] | None = None,
        checked_at: str | None = None,
        error: str = "",
        note: str = "",
        permalink_url: str = "",
    ) -> None:
        """Merge metrics into progress_json without changing publication time."""

        with self.connect() as db:
            row = db.execute(
                "SELECT progress_json FROM publication_targets WHERE id=?",
                (int(target_id),),
            ).fetchone()
            if not row:
                raise KeyError(target_id)
            try:
                progress = json.loads(str(row[0] or "{}"))
            except json.JSONDecodeError:
                progress = {}
            if not isinstance(progress, dict):
                progress = {}
            progress["metrics"] = {
                str(key): max(0, int(value))
                for key, value in (metrics or {}).items()
                if isinstance(value, (int, float))
            }
            progress["metrics_checked_at"] = str(checked_at or _iso())
            progress["metrics_error"] = redact_secrets(error)[:1000] if error else ""
            progress["metrics_note"] = str(note or "")[:1000]
            if permalink_url:
                progress["permalink_url"] = str(permalink_url)[:2000]
            db.execute(
                "UPDATE publication_targets SET progress_json=? WHERE id=?",
                (json.dumps(progress, ensure_ascii=False, sort_keys=True), int(target_id)),
            )

    def create_batch(self, article_id: int, scheduled_at: str, targets: dict[str, str]) -> int:
        """Backward-compatible wrapper used by tests and integrations."""
        return self.queue_targets(article_id, scheduled_at, targets).batch_id

    def target_statuses_for_group(self, group_id: int) -> dict[str, str]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT t.platform,t.status FROM publication_targets t
                JOIN publication_batches b ON b.id=t.batch_id
                JOIN articles a ON a.id=b.article_id
                WHERE a.group_id=? AND b.status!='cancelled'
                ORDER BY b.id,t.id
                """,
                (group_id,),
            ).fetchall()
        return {str(row["platform"]): str(row["status"]) for row in rows}

    def group_id_for_batch(self, batch_id: int) -> int:
        with self.connect() as db:
            row = db.execute(
                """
                SELECT a.group_id FROM publication_batches b
                JOIN articles a ON a.id=b.article_id WHERE b.id=?
                """,
                (batch_id,),
            ).fetchone()
        if not row or row[0] is None:
            raise KeyError(batch_id)
        return int(row[0])

    def cancel_batch(self, batch_id: int) -> None:
        self.cancel_batches([batch_id])

    def cancel_batches(self, batch_ids: Iterable[int]) -> list[int]:
        """Atomically cancel several queue packages.

        All selected packages are validated before any update. If even one package
        is currently publishing, completed, missing, or awaiting safe Drive cleanup,
        the whole operation is rolled back instead of leaving a half-cancelled range.
        """
        raw_ids = list(batch_ids)

        normalized: list[int] = []
        seen: set[int] = set()
        for raw in raw_ids:
            batch_id = int(raw)
            if batch_id <= 0:
                raise ValueError("Package ID must be positive.")
            if batch_id not in seen:
                seen.add(batch_id)
                normalized.append(batch_id)
        if not normalized:
            return []

        placeholders = ",".join("?" for _ in normalized)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                rows = db.execute(
                    f"""
                    SELECT b.id,b.status,b.cleanup_error,a.group_id,g.media_file_id,
                           (SELECT COUNT(*) FROM publication_targets t WHERE t.batch_id=b.id) AS target_count,
                           (SELECT COUNT(*) FROM publication_targets t WHERE t.batch_id=b.id AND t.status='sent') AS sent_count
                    FROM publication_batches b
                    JOIN articles a ON a.id=b.article_id
                    JOIN news_groups g ON g.id=a.group_id
                    WHERE b.id IN ({placeholders})
                    """,
                    normalized,
                ).fetchall()
                by_id = {int(row["id"]): row for row in rows}
                missing = [batch_id for batch_id in normalized if batch_id not in by_id]
                if missing:
                    raise KeyError(missing[0])

                affected_groups: set[int] = set()
                cancellable: list[int] = []
                for batch_id in normalized:
                    row = by_id[batch_id]
                    status = str(row["status"])
                    if status == "in_progress":
                        raise ValueError(
                            f"Пакет #{batch_id} зараз публікується і не може бути скасований до завершення операції."
                        )
                    if status == "completed":
                        raise ValueError(
                            f"Завершений пакет #{batch_id} не можна скасувати: публікації вже виконано."
                        )
                    if status == "cancelled":
                        continue
                    target_count = int(row["target_count"] or 0)
                    sent_count = int(row["sent_count"] or 0)
                    has_media = bool(str(row["media_file_id"] or "").strip())
                    if has_media and target_count > 0 and sent_count == target_count:
                        raise ValueError(
                            f"Пакет #{batch_id} завершує безпечне очищення Google Drive. "
                            "Дочекайтеся видалення файла й оновіть чергу."
                        )
                    cancellable.append(batch_id)
                    affected_groups.add(int(row["group_id"]))

                if cancellable:
                    now = _iso()
                    update_placeholders = ",".join("?" for _ in cancellable)
                    db.execute(
                        f"""
                        UPDATE publication_batches SET status='cancelled',lease_owner=NULL,lease_until=NULL,
                            cleanup_error=NULL,updated_at=? WHERE id IN ({update_placeholders})
                        """,
                        [now, *cancellable],
                    )
                    for group_id in affected_groups:
                        sent_history = int(
                            db.execute(
                                """
                                SELECT COUNT(*) FROM publication_targets t
                                JOIN publication_batches b ON b.id=t.batch_id
                                JOIN articles a ON a.id=b.article_id
                                WHERE a.group_id=? AND t.status='sent'
                                """,
                                (group_id,),
                            ).fetchone()[0]
                            or 0
                        )
                        next_status = "approved" if sent_history else "draft"
                        db.execute(
                            "UPDATE news_groups SET status=?,updated_at=? WHERE id=?",
                            (next_status, now, group_id),
                        )
                        db.execute(
                            "UPDATE articles SET status=? WHERE group_id=?",
                            (next_status, group_id),
                        )
                db.execute("COMMIT")
                return cancellable
            except Exception:
                db.execute("ROLLBACK")
                raise

    def claim_due_batch(self, owner: str | None = None, lease_seconds: int = 120) -> PublicationBatch | None:
        owner = owner or str(uuid.uuid4())
        now = _now()
        now_iso = _iso(now)
        lease_until = _iso(now + timedelta(seconds=lease_seconds))
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute(
                    """
                    SELECT id FROM publication_batches
                    WHERE julianday(scheduled_at)<=julianday(?)
                      AND ((status='pending' AND (lease_until IS NULL OR julianday(lease_until)<julianday(?)))
                           OR (status='in_progress' AND (lease_until IS NULL OR julianday(lease_until)<julianday(?))))
                    ORDER BY julianday(scheduled_at),id LIMIT 1
                    """,
                    (now_iso, now_iso, now_iso),
                ).fetchone()
                if not row:
                    db.execute("COMMIT")
                    return None
                batch_id = int(row["id"])
                cursor = db.execute(
                    """
                    UPDATE publication_batches
                    SET status='in_progress',lease_owner=?,lease_until=?,attempts=attempts+1,updated_at=?
                    WHERE id=? AND ((status='pending' AND (lease_until IS NULL OR julianday(lease_until)<julianday(?)))
                              OR (status='in_progress' AND (lease_until IS NULL OR julianday(lease_until)<julianday(?))))
                    """,
                    (owner, lease_until, now_iso, batch_id, now_iso, now_iso),
                )
                if cursor.rowcount != 1:
                    db.execute("ROLLBACK")
                    return None
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return self.get_batch(batch_id)

    def renew_lease(self, batch_id: int, owner: str, lease_seconds: int = 120) -> None:
        now = _now()
        with self.connect() as db:
            cursor = db.execute(
                """
                UPDATE publication_batches SET lease_until=?,updated_at=?
                WHERE id=? AND status='in_progress' AND lease_owner=? AND lease_until>=?
                """,
                (_iso(now + timedelta(seconds=lease_seconds)), _iso(now), batch_id, owner, _iso(now)),
            )
        if cursor.rowcount != 1:
            raise LeaseLost("Publication lease was lost.")

    def assert_lease(self, batch_id: int, owner: str) -> None:
        with self.connect() as db:
            row = db.execute("SELECT status,lease_owner,lease_until FROM publication_batches WHERE id=?", (batch_id,)).fetchone()
        if not row or row["status"] != "in_progress" or row["lease_owner"] != owner or not row["lease_until"] or row["lease_until"] < _iso():
            raise LeaseLost("Publication lease was lost.")

    def get_batch(self, batch_id: int) -> PublicationBatch:
        with self.connect() as db:
            row = db.execute("SELECT * FROM publication_batches WHERE id=?", (batch_id,)).fetchone()
            target_rows = db.execute("SELECT * FROM publication_targets WHERE batch_id=? ORDER BY id", (batch_id,)).fetchall()
        if not row:
            raise KeyError(batch_id)
        targets = [
            PublicationTarget(
                id=int(item["id"]), batch_id=int(item["batch_id"]), platform=str(item["platform"]),
                status=str(item["status"]), remote_id=item["remote_id"], last_error=item["last_error"],
                progress=json.loads(item["progress_json"] or "{}"),
            )
            for item in target_rows
        ]
        return PublicationBatch(
            id=int(row["id"]), article_id=int(row["article_id"]), scheduled_at=str(row["scheduled_at"]),
            status=str(row["status"]), lease_owner=row["lease_owner"], lease_until=row["lease_until"],
            attempts=int(row["attempts"]), targets=targets, cleanup_error=row["cleanup_error"],
        )

    def target_payload(self, target_id: int) -> str:
        with self.connect() as db:
            row = db.execute("SELECT payload_text FROM publication_targets WHERE id=?", (target_id,)).fetchone()
        if not row:
            raise KeyError(target_id)
        return str(row[0])

    def save_target_progress(self, target_id: int, progress: dict[str, object]) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE publication_targets SET progress_json=?,updated_at=? WHERE id=?",
                (json.dumps(progress, ensure_ascii=False, sort_keys=True), _iso(), target_id),
            )

    def mark_target_sent(self, target_id: int, remote_id: str | None) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE publication_targets SET status='sent',remote_id=?,last_error=NULL,updated_at=? WHERE id=?",
                (remote_id, _iso(), target_id),
            )

    def mark_target_failed(self, target_id: int, error: object) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE publication_targets SET status='failed',last_error=?,updated_at=? WHERE id=?",
                (redact_secrets(error)[:1000], _iso(), target_id),
            )

    def all_targets_sent(self, batch_id: int) -> bool:
        with self.connect() as db:
            rows = db.execute("SELECT status FROM publication_targets WHERE batch_id=?", (batch_id,)).fetchall()
        return bool(rows) and all(str(row[0]) == "sent" for row in rows)

    def finish_batch(
        self,
        batch_id: int,
        owner: str,
        *,
        retry_minutes: int | None = None,
        pause: bool = False,
        max_automatic_attempts: int = 3,
    ) -> bool:
        self.assert_lease(batch_id, owner)
        complete = self.all_targets_sent(batch_id)
        with self.connect() as db:
            row = db.execute(
                "SELECT attempts FROM publication_batches WHERE id=? AND lease_owner=?",
                (batch_id, owner),
            ).fetchone()
            attempts = int(row["attempts"] if row else 0)
            if complete:
                db.execute(
                    """
                    UPDATE publication_batches SET status='completed',lease_owner=NULL,lease_until=NULL,
                        cleanup_error=NULL,updated_at=? WHERE id=? AND lease_owner=?
                    """,
                    (_iso(), batch_id, owner),
                )
            elif pause or attempts >= max(1, int(max_automatic_attempts)):
                # Authentication, permissions and malformed requests do not improve
                # through blind repetition. Stop the retry storm and leave the exact
                # per-target error visible until the user updates settings and resumes.
                db.execute(
                    """
                    UPDATE publication_batches SET status='paused',lease_owner=NULL,lease_until=NULL,
                        updated_at=? WHERE id=? AND lease_owner=?
                    """,
                    (_iso(), batch_id, owner),
                )
            else:
                # Back off progressively: 15, 30 and 60 minutes for the first three
                # attempts. Tests and explicit integrations can still request an exact
                # retry delay by passing retry_minutes.
                delay = (
                    max(0, int(retry_minutes))
                    if retry_minutes is not None
                    else min(120, 15 * (2 ** max(0, attempts - 1)))
                )
                retry_at = _iso(_now() + timedelta(minutes=delay))
                # Keep failed targets visibly failed between attempts. The worker retries
                # every target that is not already sent, so changing them back to
                # "pending" only hid the actual platform error from the user.
                db.execute(
                    """
                    UPDATE publication_batches SET status='pending',scheduled_at=?,lease_owner=NULL,lease_until=NULL,
                        updated_at=? WHERE id=? AND lease_owner=?
                    """,
                    (retry_at, _iso(), batch_id, owner),
                )
        return complete

    def _reschedule_batches(
        self,
        schedules: dict[int, str],
        *,
        allowed_statuses: set[str],
    ) -> list[int]:
        normalized: dict[int, str] = {}
        for raw_id, raw_schedule in schedules.items():
            batch_id = int(raw_id)
            if batch_id <= 0:
                raise ValueError("Package ID must be positive.")
            normalized[batch_id] = _normalize_scheduled_at(str(raw_schedule))
        if not normalized:
            return []
        ids = list(normalized)
        placeholders = ",".join("?" for _ in ids)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                rows = db.execute(
                    f"SELECT id,status FROM publication_batches WHERE id IN ({placeholders})",
                    ids,
                ).fetchall()
                by_id = {int(row["id"]): str(row["status"]) for row in rows}
                missing = [batch_id for batch_id in ids if batch_id not in by_id]
                if missing:
                    raise KeyError(missing[0])
                invalid = [batch_id for batch_id in ids if by_id[batch_id] not in allowed_statuses]
                if invalid:
                    raise ValueError(
                        "Ці пакети вже не можна безпечно перепланувати: "
                        + ", ".join(f"#{item}" for item in invalid)
                    )
                now = _iso()
                for batch_id in ids:
                    db.execute(
                        """
                        UPDATE publication_batches
                        SET status='pending',scheduled_at=?,lease_owner=NULL,lease_until=NULL,
                            attempts=0,cleanup_error=NULL,updated_at=?
                        WHERE id=?
                        """,
                        (normalized[batch_id], now, batch_id),
                    )
                    db.execute(
                        """
                        UPDATE publication_targets
                        SET status=CASE WHEN status='sent' THEN 'sent' ELSE 'pending' END,
                            last_error=CASE WHEN status='sent' THEN last_error ELSE NULL END,
                            progress_json=CASE WHEN status='sent' THEN progress_json ELSE '{}' END,
                            updated_at=?
                        WHERE batch_id=?
                        """,
                        (now, batch_id),
                    )
                db.execute("COMMIT")
                return ids
            except Exception:
                db.execute("ROLLBACK")
                raise

    def reschedule_paused_batches(self, schedules: dict[int, str]) -> list[int]:
        """Atomically resume paused packages at explicit future slots."""
        return self._reschedule_batches(schedules, allowed_statuses={"paused"})

    def reschedule_recoverable_batches(self, schedules: dict[int, str]) -> list[int]:
        """Reschedule paused packages and overdue pending packages after an outage.

        Sent targets remain sent. Non-sent targets are reset for a clean,
        selective retry. In-progress, completed and cancelled packages fail
        closed so a recovery action cannot duplicate an active publication.
        """
        return self._reschedule_batches(schedules, allowed_statuses={"paused", "pending"})

    def resume_batch(self, batch_id: int, *, reset_attempts: bool = True) -> None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute(
                    "SELECT status FROM publication_batches WHERE id=?",
                    (batch_id,),
                ).fetchone()
                if not row:
                    raise KeyError(batch_id)
                status = str(row["status"])
                if status == "in_progress":
                    raise ValueError("Пакет зараз публікується.")
                if status in {"completed", "cancelled"}:
                    raise ValueError("Завершений або скасований пакет не можна відновити цією дією.")
                now = _iso()
                db.execute(
                    """
                    UPDATE publication_batches
                    SET status='pending',scheduled_at=?,lease_owner=NULL,lease_until=NULL,
                        attempts=CASE WHEN ? THEN 0 ELSE attempts END,updated_at=?
                    WHERE id=?
                    """,
                    (now, 1 if reset_attempts else 0, now, batch_id),
                )
                db.execute(
                    """
                    UPDATE publication_targets
                    SET status=CASE WHEN status='sent' THEN 'sent' ELSE 'pending' END,
                        last_error=CASE WHEN status='sent' THEN last_error ELSE NULL END,
                        updated_at=?
                    WHERE batch_id=?
                    """,
                    (now, batch_id),
                )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise

    def defer_cleanup(self, batch_id: int, owner: str, error: object, retry_minutes: int = 15) -> None:
        self.assert_lease(batch_id, owner)
        with self.connect() as db:
            db.execute(
                """
                UPDATE publication_batches SET status='pending',scheduled_at=?,lease_owner=NULL,lease_until=NULL,
                    cleanup_error=?,updated_at=? WHERE id=? AND lease_owner=?
                """,
                (_iso(_now() + timedelta(minutes=retry_minutes)), redact_secrets(error)[:1000], _iso(), batch_id, owner),
            )

    def release_lost_batch(self, batch_id: int, owner: str) -> None:
        with self.connect() as db:
            db.execute(
                """
                UPDATE publication_batches SET status='pending',lease_owner=NULL,lease_until=NULL,updated_at=?
                WHERE id=? AND lease_owner=? AND status='in_progress'
                """,
                (_iso(), batch_id, owner),
            )

    def list_batches(
        self,
        limit: int = 200,
        statuses: set[str] | None = None,
    ) -> list[PublicationBatch]:
        query = "SELECT id FROM publication_batches"
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
        params.append(limit)
        with self.connect() as db:
            ids = [row[0] for row in db.execute(query, params).fetchall()]
        return [self.get_batch(int(batch_id)) for batch_id in ids]
