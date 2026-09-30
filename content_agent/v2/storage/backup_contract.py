from __future__ import annotations

import json
import os
import secrets
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from ...ai_router import AIProviderSecrets, load_provider_secrets, save_provider_secrets
from ...config import AppConfig, load_config, save_config
from ...database import DATABASE_SCHEMA_VERSION
from ...maintenance import DATA_MAINTENANCE_LOCK
from ...paths import backups_dir, data_dir, database_path
from ...security import sha256_file, validate_zip_member
from ..ai.settings import load_openrouter_api_key, save_openrouter_api_key

SCHEMA = 3
MODE_NORMAL = "normal"
MODE_MIGRATION = "migration"
APPLICATION_ID = "UA_FREE_Content_Tool"
CREDENTIAL_HEADER = b"UA_FREE_BACKUP_CREDENTIALS_SCRYPT_AESGCM_V1\n"
CREDENTIAL_AAD = b"UA_FREE_Content_Tool_backup_credentials_v1"
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_FILE_BYTES = 1024 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024 + 16 * 1024 * 1024
ALLOWED_FILES = {
    "content_agent.sqlite3",
    "durable_state.json",
    "publication_receipts.json",
    "credentials.enc",
    "manifest.json",
}
DURABLE_JSON_FILES = (
    "instagram_destinations_v1_4.json",
    "telegram_destinations_v2.json",
    "destination_schedules_v1_4.json",
    "publication_target_sets.json",
    "topic_assignments_v1_4_rc4.json",
    "managed_media.json",
    "multi_images_v1_2.json",
    "source_media_hints_v1_2.json",
    "v2/ai_backend.json",
    "supervisor/instance.json",
)


class BackupContractError(RuntimeError):
    pass


def _legacy():
    # Import lazily so content_agent.backup can expose this contract without an
    # import cycle. The legacy module still owns the thoroughly tested SQLite and
    # schema validation helpers used by schema-2 compatibility.
    from ... import backup as legacy

    return legacy


def _fsync(path: Path) -> None:
    with path.open("rb+") as handle:
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_json(path: Path) -> object | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _collect_durable_state() -> dict[str, object]:
    root = data_dir()
    result: dict[str, object] = {}
    for relative in DURABLE_JSON_FILES:
        value = _read_json(root / Path(relative))
        if value is not None:
            result[relative] = value
    return result


def _collect_receipts() -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    receipt_dir = data_dir() / "publication_recovery"
    if not receipt_dir.is_dir():
        return result
    for path in sorted(receipt_dir.glob("target_*.json")):
        value = _read_json(path)
        if not isinstance(value, dict):
            continue
        if value.get("schema") != "ua-free-content-tool-publication-receipt-v1":
            continue
        try:
            target_id = int(value.get("target_id") or 0)
        except (TypeError, ValueError):
            continue
        if target_id > 0:
            result.append(dict(value))
    return result


def _derive_key(password: str, salt: bytes) -> bytes:
    value = str(password or "")
    if len(value) < 10:
        raise BackupContractError("Пароль migration backup має містити щонайменше 10 символів.")
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(value.encode("utf-8"))


def _credential_payload() -> bytes:
    try:
        config = load_config()
        router = load_provider_secrets()
        openrouter_key = load_openrouter_api_key()
    except Exception as exc:
        raise BackupContractError("Не вдалося прочитати credentials для migration backup.") from exc
    payload = {
        "schema": "ua-free-content-tool-credential-migration-v1",
        "app_config": json.loads(config.to_json_bytes().decode("utf-8")),
        "ai_provider_secrets": asdict(router),
        "openrouter_api_key": openrouter_key,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")


def _encrypt_credentials(password: str) -> bytes:
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(12)
    key = _derive_key(password, salt)
    encrypted = AESGCM(key).encrypt(nonce, _credential_payload(), CREDENTIAL_AAD)
    return CREDENTIAL_HEADER + salt + nonce + encrypted


def _decrypt_credentials(raw: bytes, password: str) -> dict[str, object]:
    if not raw.startswith(CREDENTIAL_HEADER):
        raise BackupContractError("Migration credentials мають невідомий формат.")
    payload = raw[len(CREDENTIAL_HEADER):]
    if len(payload) < 44:
        raise BackupContractError("Migration credentials пошкоджено.")
    salt, nonce, encrypted = payload[:16], payload[16:28], payload[28:]
    try:
        plain = AESGCM(_derive_key(password, salt)).decrypt(nonce, encrypted, CREDENTIAL_AAD)
        value = json.loads(plain.decode("utf-8"))
    except BackupContractError:
        raise
    except Exception as exc:
        raise BackupContractError("Неправильний пароль або migration credentials пошкоджено.") from exc
    if not isinstance(value, dict) or value.get("schema") != "ua-free-content-tool-credential-migration-v1":
        raise BackupContractError("Migration credentials мають неправильну схему.")
    return value


def create_backup(
    destination_dir: Path | None = None,
    *,
    mode: str = MODE_NORMAL,
    credential_password: str | None = None,
) -> Path:
    legacy = _legacy()
    db_path = database_path()
    if not db_path.exists():
        raise BackupContractError("Database does not exist yet.")
    if mode not in {MODE_NORMAL, MODE_MIGRATION}:
        raise BackupContractError("Невідомий режим backup.")
    if mode == MODE_MIGRATION and not credential_password:
        raise BackupContractError("Для migration backup потрібен пароль.")

    destination = destination_dir or backups_dir()
    destination.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    kind = "migration" if mode == MODE_MIGRATION else "backup"
    final_zip = destination / f"UA_FREE_Content_Tool_{kind}_{stamp}.zip"
    temp_zip = final_zip.with_suffix(".zip.tmp")

    with tempfile.TemporaryDirectory(prefix="uafree-backup-v3-") as temp_name:
        temp = Path(temp_name)
        snapshot = temp / "content_agent.sqlite3"
        with DATA_MAINTENANCE_LOCK:
            legacy._sqlite_snapshot(db_path, snapshot)

        durable_path = temp / "durable_state.json"
        durable_path.write_text(
            json.dumps(_collect_durable_state(), ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        receipts_path = temp / "publication_receipts.json"
        receipts_path.write_text(
            json.dumps(_collect_receipts(), ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        files = [snapshot, durable_path, receipts_path]
        if mode == MODE_MIGRATION:
            credential_path = temp / "credentials.enc"
            credential_path.write_bytes(_encrypt_credentials(str(credential_password)))
            files.append(credential_path)

        manifest = {
            "application": APPLICATION_ID,
            "schema": SCHEMA,
            "database_schema": DATABASE_SCHEMA_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "mode": mode,
            "credential_protection": "scrypt-aesgcm-v1" if mode == MODE_MIGRATION else "none",
            "files": {
                item.name: {"size": item.stat().st_size, "sha256": sha256_file(item)} for item in files
            },
        }
        manifest_path = temp / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        files.append(manifest_path)
        with zipfile.ZipFile(temp_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for item in files:
                archive.write(item, item.name)

    _fsync(temp_zip)
    os.replace(temp_zip, final_zip)
    _fsync_directory(destination)
    return final_zip


def create_migration_backup(password: str, destination_dir: Path | None = None) -> Path:
    return create_backup(destination_dir, mode=MODE_MIGRATION, credential_password=password)


def peek_manifest(archive_path: Path) -> dict[str, object]:
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            info = archive.getinfo("manifest.json")
            if info.file_size > 1024 * 1024:
                raise BackupContractError("Backup manifest завеликий.")
            value = json.loads(archive.read(info).decode("utf-8"))
    except (KeyError, zipfile.BadZipFile, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackupContractError("Backup manifest is invalid.") from exc
    if not isinstance(value, dict):
        raise BackupContractError("Backup manifest is invalid.")
    return value


def backup_requires_password(archive_path: Path) -> bool:
    manifest = peek_manifest(Path(archive_path))
    return int(manifest.get("schema") or 0) == SCHEMA and manifest.get("mode") == MODE_MIGRATION


def _validate_archive(archive_path: Path, destination: Path) -> dict[str, object]:
    legacy = _legacy()
    try:
        archive_size = archive_path.stat().st_size
    except OSError as exc:
        raise BackupContractError("Backup file cannot be read.") from exc
    if archive_size > MAX_ARCHIVE_BYTES:
        raise BackupContractError("Backup archive exceeds the configured size limit.")

    with zipfile.ZipFile(archive_path, "r") as archive:
        infos = archive.infolist()
        if len(infos) > len(ALLOWED_FILES):
            raise BackupContractError("Backup contains too many entries.")
        names: set[str] = set()
        total = 0
        for info in infos:
            path = validate_zip_member(info.filename)
            if len(path.parts) != 1 or info.is_dir():
                raise BackupContractError("Backup must contain files only at the archive root.")
            if info.filename in names:
                raise BackupContractError("Backup contains duplicate file names.")
            names.add(info.filename)
            mode_bits = (info.external_attr >> 16) & 0o170000
            if mode_bits == 0o120000:
                raise BackupContractError("Symlinks are forbidden in backups.")
            if info.flag_bits & 0x1:
                raise BackupContractError("ZIP-level encryption is not supported.")
            if info.file_size > MAX_FILE_BYTES:
                raise BackupContractError(f"Backup entry is too large: {info.filename}.")
            total += info.file_size
            if total > MAX_TOTAL_BYTES:
                raise BackupContractError("Backup uncompressed size exceeds the configured limit.")
        required = {"content_agent.sqlite3", "durable_state.json", "publication_receipts.json", "manifest.json"}
        if not names.issubset(ALLOWED_FILES) or not required.issubset(names):
            raise BackupContractError("Backup contains an unexpected or incomplete file set.")
        destination.mkdir(parents=True, exist_ok=True)
        for info in infos:
            target = destination / info.filename
            with archive.open(info, "r") as source, target.open("xb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)

    manifest = peek_manifest(archive_path)
    expected_keys = {
        "application", "schema", "database_schema", "created_at", "mode",
        "credential_protection", "files",
    }
    if set(manifest) != expected_keys:
        raise BackupContractError("Backup manifest has an invalid schema.")
    if manifest.get("application") != APPLICATION_ID or int(manifest.get("schema") or 0) != SCHEMA:
        raise BackupContractError("Backup schema is unsupported.")
    if int(manifest.get("database_schema") or 0) != DATABASE_SCHEMA_VERSION:
        raise BackupContractError("Backup database schema is unsupported.")
    mode = str(manifest.get("mode") or "")
    if mode not in {MODE_NORMAL, MODE_MIGRATION}:
        raise BackupContractError("Backup mode is unsupported.")
    if (mode == MODE_MIGRATION) != ("credentials.enc" in names):
        raise BackupContractError("Migration credential payload does not match manifest mode.")
    protection = manifest.get("credential_protection")
    if mode == MODE_MIGRATION and protection != "scrypt-aesgcm-v1":
        raise BackupContractError("Migration backup credential protection is unsupported.")
    if mode == MODE_NORMAL and protection != "none":
        raise BackupContractError("Normal backup unexpectedly declares credential protection.")
    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != names - {"manifest.json"}:
        raise BackupContractError("Backup manifest file list does not match the archive.")
    for name, record in files.items():
        if not isinstance(record, dict) or set(record) != {"size", "sha256"}:
            raise BackupContractError(f"Invalid manifest record for {name}.")
        path = destination / str(name)
        if path.stat().st_size != int(record["size"]) or sha256_file(path) != str(record["sha256"]):
            raise BackupContractError(f"Backup hash or size mismatch for {name}.")
    legacy._validate_database(destination / "content_agent.sqlite3")
    return manifest


def _load_durable_bundle(temp: Path) -> dict[str, object]:
    try:
        value = json.loads((temp / "durable_state.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackupContractError("Durable state bundle is invalid.") from exc
    if not isinstance(value, dict) or set(value) - set(DURABLE_JSON_FILES):
        raise BackupContractError("Durable state bundle contains unsupported files.")
    return value


def _restore_durable_state(bundle: dict[str, object]) -> None:
    root = data_dir()
    for relative in DURABLE_JSON_FILES:
        target = root / Path(relative)
        if relative not in bundle:
            target.unlink(missing_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".restore.tmp")
        temporary.write_text(
            json.dumps(bundle[relative], ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, target)


def _restore_receipts(temp: Path, restored_db: Path) -> None:
    try:
        values = json.loads((temp / "publication_receipts.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackupContractError("Publication receipt bundle is invalid.") from exc
    if not isinstance(values, list):
        raise BackupContractError("Publication receipt bundle must be a list.")
    destination = data_dir() / "publication_recovery"
    destination.mkdir(parents=True, exist_ok=True)
    for old in destination.glob("target_*.json"):
        old.unlink(missing_ok=True)
    connection = sqlite3.connect(f"file:{restored_db}?mode=ro", uri=True)
    try:
        for value in values:
            if not isinstance(value, dict) or value.get("schema") != "ua-free-content-tool-publication-receipt-v1":
                raise BackupContractError("Publication receipt bundle contains an invalid receipt.")
            target_id = int(value.get("target_id") or 0)
            if target_id <= 0:
                raise BackupContractError("Publication receipt has an invalid target id.")
            exists = connection.execute("SELECT 1 FROM publication_targets WHERE id=?", (target_id,)).fetchone()
            if exists is None:
                continue
            (destination / f"target_{target_id}.json").write_text(
                json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2),
                encoding="utf-8",
            )
    finally:
        connection.close()


def _apply_credentials(payload: dict[str, object]) -> None:
    app_config = payload.get("app_config")
    provider = payload.get("ai_provider_secrets")
    openrouter = payload.get("openrouter_api_key")
    if not isinstance(app_config, dict) or not isinstance(provider, dict) or not isinstance(openrouter, str):
        raise BackupContractError("Migration credential payload is incomplete.")
    try:
        config = AppConfig.from_json_bytes(json.dumps(app_config, ensure_ascii=False).encode("utf-8"))
        allowed = set(AIProviderSecrets.__dataclass_fields__)
        provider_value = AIProviderSecrets(**{key: provider[key] for key in provider if key in allowed}).normalized()
        save_config(config)
        save_provider_secrets(provider_value)
        save_openrouter_api_key(openrouter)
    except Exception as exc:
        raise BackupContractError("Не вдалося застосувати migration credentials.") from exc


def import_backup(archive_path: Path, *, credential_password: str | None = None):
    legacy = _legacy()
    with DATA_MAINTENANCE_LOCK:
        safety = create_backup()
        root = data_dir()
        with tempfile.TemporaryDirectory(prefix="uafree-import-v3-", dir=root) as temp_name:
            temp = Path(temp_name)
            manifest = _validate_archive(Path(archive_path), temp)
            mode = str(manifest["mode"])
            credentials: dict[str, object] | None = None
            if mode == MODE_MIGRATION:
                if not credential_password:
                    raise BackupContractError("Цей migration backup захищено паролем.")
                credentials = _decrypt_credentials((temp / "credentials.enc").read_bytes(), credential_password)

            durable = _load_durable_bundle(temp)
            incoming_db = temp / "content_agent.sqlite3"
            staged_db = root / ".content_agent.sqlite3.import-v3"
            shutil.copyfile(incoming_db, staged_db)
            _fsync(staged_db)
            legacy._validate_database(staged_db)
            target_db = database_path()
            legacy._remove_sqlite_sidecars(target_db)
            os.replace(staged_db, target_db)
            _fsync(target_db)
            legacy._remove_sqlite_sidecars(target_db)
            _restore_durable_state(durable)
            _restore_receipts(temp, target_db)
            if credentials is not None:
                _apply_credentials(credentials)
            _fsync_directory(root)
    return legacy.ImportResult(
        safety_backup=safety,
        imported_database=True,
        imported_config=credentials is not None,
    )


__all__ = [
    "SCHEMA",
    "MODE_NORMAL",
    "MODE_MIGRATION",
    "BackupContractError",
    "create_backup",
    "create_migration_backup",
    "peek_manifest",
    "backup_requires_password",
    "import_backup",
]
