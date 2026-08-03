from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import ConfigError, load_config, save_config
from .database import DATABASE_SCHEMA_VERSION
from .maintenance import DATA_MAINTENANCE_LOCK
from .paths import backups_dir, config_path, data_dir, database_path, portable_key_path, portable_mode
from .security import sha256_file, validate_zip_member

_BACKUP_SCHEMA = 2
_APPLICATION_ID = "UA_FREE_Content_Tool"
_REQUIRED_TABLES = {
    "sources": {"id", "kind", "name", "url", "enabled", "last_checked_at", "created_at"},
    "news_groups": {
        "id", "canonical_title", "status", "headline", "fact_card", "rewrite_text",
        "ai_draft_text", "platform_texts_json", "include_source_link", "media_drive_url", "media_file_id",
        "media_name", "media_kind", "media_mime", "media_size", "explosiveness_score",
        "explosiveness_confidence", "explosiveness_details_json", "recommended_platforms_json",
        "created_at", "updated_at",
    },
    "articles": {
        "id", "source_id", "group_id", "external_id", "content_hash", "title", "url",
        "raw_text", "published_at", "discovered_at", "status", "headline", "fact_card",
        "rewrite_text", "platform_texts_json",
    },
    "publication_batches": {
        "id", "article_id", "scheduled_at", "status", "lease_owner", "lease_until",
        "attempts", "cleanup_error", "created_at", "updated_at",
    },
    "publication_targets": {
        "id", "batch_id", "platform", "payload_text", "status", "remote_id",
        "last_error", "progress_json", "updated_at",
    },
    "editorial_examples": {
        "id", "group_id", "source_fingerprint", "source_text", "ai_draft_text",
        "final_text", "headline", "created_at",
    },
    "topic_merge_feedback": {
        "id", "anchor_signature", "candidate_signature", "decision", "anchor_text",
        "candidate_text", "created_at",
    },
    "content_exclusions": {
        "id", "group_id", "signature", "title", "source_text", "active",
        "created_at", "updated_at",
    },
    "queue_text_migrations": {
        "id", "migration_key", "backup_path", "summary_json", "completed_at",
    },
    "queue_text_migration_items": {
        "id", "migration_id", "batch_id", "group_id", "old_text", "new_text",
        "old_length", "new_length", "limit_value", "created_at",
    },
}
_ALLOWED = {"content_agent.sqlite3", "config.dpapi", "config.portable", "portable.key", "manifest.json"}
_MAX_BACKUP_ARCHIVE_BYTES = 512 * 1024 * 1024
_MAX_BACKUP_FILE_BYTES = 1024 * 1024 * 1024
_MAX_BACKUP_TOTAL_BYTES = 1024 * 1024 * 1024 + 10 * 1024 * 1024
_MAX_BACKUP_ENTRIES = len(_ALLOWED)


class BackupError(RuntimeError):
    pass


@dataclass(slots=True)
class ImportResult:
    safety_backup: Path
    imported_database: bool
    imported_config: bool


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


def _validate_database(path: Path) -> None:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        result = connection.execute("PRAGMA quick_check").fetchone()[0]
        if result != "ok":
            raise BackupError(f"Backup database failed quick_check: {result}")
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version != DATABASE_SCHEMA_VERSION:
            raise BackupError(
                f"Backup database schema {version} is unsupported; expected {DATABASE_SCHEMA_VERSION}."
            )
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        if tables != set(_REQUIRED_TABLES):
            raise BackupError("Backup database has an unexpected table set.")
        for table, expected_columns in _REQUIRED_TABLES.items():
            columns = {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
            if columns != expected_columns:
                raise BackupError(f"Backup database table {table} has an unexpected schema.")
    finally:
        connection.close()


def _sqlite_snapshot(source: Path, destination: Path) -> None:
    source_db = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    destination_db = sqlite3.connect(destination)
    try:
        source_db.backup(destination_db)
        result = destination_db.execute("PRAGMA quick_check").fetchone()[0]
        if result != "ok":
            raise BackupError(f"SQLite backup quick_check failed: {result}")
        destination_db.commit()
    finally:
        destination_db.close()
        source_db.close()
    _fsync_file(destination)


def _create_backup_unlocked(destination_dir: Path | None = None) -> Path:
    db_path = database_path()
    if not db_path.exists():
        raise BackupError("Database does not exist yet.")
    destination = destination_dir or backups_dir()
    destination.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    final_zip = destination / f"UA_FREE_Content_Tool_backup_{stamp}.zip"
    temp_zip = final_zip.with_suffix(".zip.tmp")
    with tempfile.TemporaryDirectory(prefix="uafree-backup-") as temp_name:
        temp = Path(temp_name)
        snapshot = temp / "content_agent.sqlite3"
        _sqlite_snapshot(db_path, snapshot)
        files = [snapshot]
        cfg = config_path()
        if cfg.exists():
            cfg_copy = temp / cfg.name
            shutil.copyfile(cfg, cfg_copy)
            _fsync_file(cfg_copy)
            files.append(cfg_copy)
            if cfg.name == "config.portable":
                key = portable_key_path()
                if not key.exists():
                    raise BackupError("Portable configuration key is missing.")
                key_copy = temp / "portable.key"
                shutil.copyfile(key, key_copy)
                _fsync_file(key_copy)
                files.append(key_copy)
        manifest = {
            "application": _APPLICATION_ID,
            "schema": _BACKUP_SCHEMA,
            "database_schema": DATABASE_SCHEMA_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "files": {
                item.name: {"size": item.stat().st_size, "sha256": sha256_file(item)} for item in files
            },
        }
        manifest_path = temp / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        files.append(manifest_path)
        with zipfile.ZipFile(temp_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for item in files:
                archive.write(item, item.name)
    _fsync_file(temp_zip)
    os.replace(temp_zip, final_zip)
    _fsync_directory(destination)
    return final_zip



def create_backup(destination_dir: Path | None = None) -> Path:
    with DATA_MAINTENANCE_LOCK:
        return _create_backup_unlocked(destination_dir)

def _validate_archive(archive_path: Path, destination: Path) -> dict[str, object]:
    try:
        archive_size = archive_path.stat().st_size
    except OSError as exc:
        raise BackupError("Backup file cannot be read.") from exc
    if archive_size > _MAX_BACKUP_ARCHIVE_BYTES:
        raise BackupError("Backup archive exceeds the configured size limit.")

    with zipfile.ZipFile(archive_path, "r") as archive:
        infos = archive.infolist()
        if len(infos) > _MAX_BACKUP_ENTRIES:
            raise BackupError("Backup contains too many entries.")
        raw_names = [info.filename for info in infos]
        if len(raw_names) != len(set(raw_names)):
            raise BackupError("Backup contains duplicate file names.")

        names: set[str] = set()
        total_uncompressed = 0
        for info in infos:
            path = validate_zip_member(info.filename)
            if len(path.parts) != 1 or info.is_dir():
                raise BackupError("Backup must contain files only at the archive root.")
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise BackupError("Symlinks are forbidden in backups.")
            if info.flag_bits & 0x1:
                raise BackupError("Encrypted backup entries are not supported.")
            if info.file_size > _MAX_BACKUP_FILE_BYTES:
                raise BackupError(f"Backup entry is too large: {info.filename}.")
            total_uncompressed += info.file_size
            if total_uncompressed > _MAX_BACKUP_TOTAL_BYTES:
                raise BackupError("Backup uncompressed size exceeds the configured limit.")
            names.add(info.filename)

        if not names.issubset(_ALLOWED) or "manifest.json" not in names or "content_agent.sqlite3" not in names:
            raise BackupError("Backup contains an unexpected file set.")

        destination.mkdir(parents=True, exist_ok=True)
        for info in infos:
            target = destination / info.filename
            written = 0
            try:
                with archive.open(info, "r") as source, target.open("xb") as output:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > _MAX_BACKUP_FILE_BYTES:
                            raise BackupError(f"Backup entry expanded beyond the size limit: {info.filename}.")
                        output.write(chunk)
            except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
                raise BackupError(f"Backup entry could not be extracted safely: {info.filename}.") from exc
            if written != info.file_size:
                raise BackupError(f"Backup entry size mismatch: {info.filename}.")
    try:
        manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupError("Backup manifest is invalid.") from exc
    if not isinstance(manifest, dict) or set(manifest) != {
        "application", "schema", "database_schema", "created_at", "files"
    }:
        raise BackupError("Backup manifest has an invalid schema.")
    if (
        manifest["application"] != _APPLICATION_ID
        or manifest["schema"] != _BACKUP_SCHEMA
        or manifest["database_schema"] != DATABASE_SCHEMA_VERSION
        or not isinstance(manifest["created_at"], str)
        or not isinstance(manifest["files"], dict)
    ):
        raise BackupError("Backup schema is unsupported.")
    expected_files = names - {"manifest.json"}
    if set(manifest["files"]) != expected_files:
        raise BackupError("Backup manifest file list does not match the archive.")
    for name in expected_files:
        record = manifest["files"][name]
        path = destination / name
        if not isinstance(record, dict) or set(record) != {"size", "sha256"}:
            raise BackupError(f"Invalid manifest record for {name}.")
        if path.stat().st_size != record["size"] or sha256_file(path) != record["sha256"]:
            raise BackupError(f"Backup hash or size mismatch for {name}.")
    _validate_database(destination / "content_agent.sqlite3")
    return manifest


def _remove_sqlite_sidecars(path: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(str(path) + suffix)
        try:
            sidecar.unlink()
        except FileNotFoundError:
            pass


def _import_backup_unlocked(archive_path: Path) -> ImportResult:
    if not archive_path.is_file():
        raise BackupError("Backup file does not exist.")
    safety = _create_backup_unlocked()
    root = data_dir()
    with tempfile.TemporaryDirectory(prefix="uafree-import-", dir=root) as temp_name:
        temp = Path(temp_name)
        _validate_archive(archive_path, temp)
        incoming_db = temp / "content_agent.sqlite3"
        incoming_dpapi = temp / "config.dpapi"
        incoming_portable = temp / "config.portable"
        incoming_key = temp / "portable.key"
        if incoming_portable.exists() != incoming_key.exists():
            raise BackupError("Portable backup must contain both config.portable and portable.key.")
        if incoming_dpapi.exists() and incoming_portable.exists():
            raise BackupError("Backup contains two different configuration formats.")

        staged_db = root / ".content_agent.sqlite3.import"
        shutil.copyfile(incoming_db, staged_db)
        _fsync_file(staged_db)
        _validate_database(staged_db)
        target_db = database_path()
        target_cfg = config_path()
        target_key = portable_key_path()
        incoming_cfg = incoming_portable if incoming_portable.exists() else incoming_dpapi
        imported_config = incoming_cfg.exists()

        staged_cfg_dir = temp / "converted"
        staged_cfg_dir.mkdir()
        staged_cfg = staged_cfg_dir / target_cfg.name
        staged_key = staged_cfg_dir / "portable.key"
        if imported_config:
            try:
                loaded = load_config(
                    incoming_cfg,
                    key_path=incoming_key if incoming_portable.exists() else None,
                )
                save_config(
                    loaded,
                    staged_cfg,
                    key_path=staged_key if portable_mode() else None,
                )
            except ConfigError as exc:
                raise BackupError("Backup configuration cannot be decrypted on this computer.") from exc
            _fsync_file(staged_cfg)
            if portable_mode():
                _fsync_file(staged_key)

        _remove_sqlite_sidecars(target_db)
        os.replace(staged_db, target_db)
        _fsync_file(target_db)
        _remove_sqlite_sidecars(target_db)

        if imported_config:
            if portable_mode():
                os.replace(staged_key, target_key)
                _fsync_file(target_key)
            else:
                try:
                    target_key.unlink()
                except FileNotFoundError:
                    pass
            os.replace(staged_cfg, target_cfg)
            _fsync_file(target_cfg)
        else:
            for path in (target_cfg, target_key):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
        _fsync_directory(root)
    return ImportResult(safety_backup=safety, imported_database=True, imported_config=imported_config)


def import_backup(archive_path: Path) -> ImportResult:
    with DATA_MAINTENANCE_LOCK:
        return _import_backup_unlocked(archive_path)
