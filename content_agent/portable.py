from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import AppConfig, ConfigError, load_config, save_config
from .paths import (
    CLEAN_START_MARKER,
    config_path,
    data_dir,
    database_path,
    legacy_local_data_dir,
    portable_key_path,
    portable_mode,
    runtime_dir,
)


class PortableMigrationError(RuntimeError):
    pass


@dataclass(slots=True)
class PortableMigrationResult:
    migrated: bool
    database_migrated: bool = False
    config_migrated: bool = False
    source: Path | None = None


_USER_DATA_TABLES = (
    "sources",
    "news_groups",
    "articles",
    "publication_batches",
    "publication_targets",
)


def _fsync_file(path: Path) -> None:
    with path.open("rb+") as handle:
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _remove_sqlite_sidecars(path: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        try:
            Path(str(path) + suffix).unlink()
        except FileNotFoundError:
            pass


def _sqlite_snapshot(source: Path, destination: Path) -> None:
    source_db = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    destination_db = sqlite3.connect(destination)
    try:
        source_db.backup(destination_db)
        destination_db.commit()
        result = destination_db.execute("PRAGMA quick_check").fetchone()[0]
        if result != "ok":
            raise PortableMigrationError(f"Portable database copy failed quick_check: {result}")
    finally:
        destination_db.close()
        source_db.close()
    _fsync_file(destination)


def _database_has_user_data(path: Path) -> bool:
    """Return False for a newly initialized schema-only database.

    Windows gate startup probes legitimately create an empty database beside the
    portable EXE. That empty file must not block a later import of the user's
    real LocalAppData database.
    """
    if not path.exists() or path.stat().st_size == 0:
        return False
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise PortableMigrationError("Existing portable database failed quick_check.")
        existing = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for table in _USER_DATA_TABLES:
            if table not in existing:
                continue
            if connection.execute(f'SELECT 1 FROM "{table}" LIMIT 1').fetchone() is not None:
                return True
        return False
    finally:
        connection.close()


def _portable_config_is_default(config_file: Path, key_file: Path) -> bool:
    try:
        return load_config(config_file, key_path=key_file) == AppConfig()
    except ConfigError as exc:
        raise PortableMigrationError("Existing portable settings cannot be opened.") from exc


def _backup_existing(path: Path, backup: Path) -> Path | None:
    if not path.exists():
        return None
    shutil.copy2(path, backup)
    _fsync_file(backup)
    return backup


def ensure_portable_data_migrated() -> PortableMigrationResult:
    """Import missing or test-empty portable data from the old stable folder.

    R8 FIX6 treated the existence of *any* portable database as authoritative.
    The Windows gate starts the EXE once and therefore creates a schema-only DB;
    copying that tested folder then suppressed the real LocalAppData migration.

    FIX7 evaluates the database and configuration independently:
    - a database with user rows is preserved;
    - a schema-only/zero-byte database may be replaced by the real legacy DB;
    - a valid non-default portable config is preserved;
    - a missing or default portable config may be replaced by legacy settings;
    - a half-present config/key pair still fails closed.
    """
    if not portable_mode():
        return PortableMigrationResult(False)

    # FIX25 portable releases start empty by design. The clean-start marker
    # prevents old LocalAppData settings, channels and queue state from being
    # silently imported into a freshly unpacked copy. Users can still restore
    # an explicit backup from the Settings tab.
    if (runtime_dir() / CLEAN_START_MARKER).is_file():
        return PortableMigrationResult(False)

    target_root = data_dir()
    target_db = database_path()
    target_cfg = config_path()
    target_key = portable_key_path()
    target_db_existed = target_db.exists()

    cfg_exists = target_cfg.exists()
    key_exists = target_key.exists()
    if cfg_exists != key_exists:
        raise PortableMigrationError(
            "Portable settings are incomplete. Keep config.portable and portable.key together."
        )

    source_root = legacy_local_data_dir()
    source_db = source_root / "content_agent.sqlite3"
    source_cfg = source_root / "config.dpapi"
    if not source_db.exists() and not source_cfg.exists():
        return PortableMigrationResult(False)

    target_db_has_data = _database_has_user_data(target_db)
    target_cfg_is_authoritative = cfg_exists and not _portable_config_is_default(target_cfg, target_key)

    migrate_database = source_db.exists() and not target_db_has_data
    migrate_config = source_cfg.exists() and not target_cfg_is_authoritative
    if not migrate_database and not migrate_config:
        return PortableMigrationResult(False)

    lock = target_root / ".portable-migration.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise PortableMigrationError("Portable data migration is already running or was interrupted.") from exc
    os.close(descriptor)

    database_migrated = False
    config_migrated = False
    originals: dict[Path, Path | None] = {}
    stage = Path(tempfile.mkdtemp(prefix="uafree-portable-", dir=target_root))
    try:
        staged_db = stage / "content_agent.sqlite3"
        staged_cfg = stage / "config.portable"
        staged_key = stage / "portable.key"

        if migrate_database:
            _sqlite_snapshot(source_db, staged_db)
            database_migrated = True

        if migrate_config:
            try:
                old_config = load_config(source_cfg)
            except ConfigError as exc:
                raise PortableMigrationError(
                    "Old settings cannot be decrypted on this Windows account. "
                    "Start FIX16 once on the original computer."
                ) from exc
            save_config(old_config, staged_cfg, key_path=staged_key)
            config_migrated = True

        # Preserve any pre-existing target bytes so a failed multi-file commit
        # can restore the exact prior state.
        if database_migrated:
            originals[target_db] = _backup_existing(target_db, stage / "original.sqlite3")
        if config_migrated:
            originals[target_cfg] = _backup_existing(target_cfg, stage / "original.config.portable")
            originals[target_key] = _backup_existing(target_key, stage / "original.portable.key")

        if database_migrated:
            _remove_sqlite_sidecars(target_db)
            os.replace(staged_db, target_db)
            _fsync_file(target_db)
        if config_migrated:
            os.replace(staged_key, target_key)
            os.replace(staged_cfg, target_cfg)
            _fsync_file(target_key)
            _fsync_file(target_cfg)

        record = {
            "migrated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": str(source_root),
            "database": database_migrated,
            "config": config_migrated,
            "replaced_empty_portable_database": bool(
                database_migrated and target_db_existed and not target_db_has_data
            ),
            "old_data_preserved": True,
        }
        marker = target_root / "portable-migration.json"
        marker.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        _fsync_file(marker)
        _fsync_directory(target_root)
        return PortableMigrationResult(True, database_migrated, config_migrated, source_root)
    except Exception:
        # Restore the exact target state that existed before this attempt while
        # the staged backups still exist.
        for target, backup in originals.items():
            try:
                if backup is None:
                    target.unlink()
                elif backup.exists():
                    os.replace(backup, target)
            except FileNotFoundError:
                pass
        _remove_sqlite_sidecars(target_db)
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        try:
            lock.unlink()
        except FileNotFoundError:
            pass
