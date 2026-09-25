from __future__ import annotations

import json
import os
import shutil
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import load_config, save_config
from .paths import config_path, data_dir, database_path, migration_dir, portable_key_path

# Only durable editorial/user state is imported. Runtime cooldowns, source-health,
# supervisor/recovery state, caches, logs, backups, Tools and legacy AI runtimes stay behind.
_STABLE_TABLES = (
    "sources",
    "news_groups",
    "articles",
    "publication_batches",
    "publication_targets",
    "editorial_examples",
    "topic_merge_feedback",
    "content_exclusions",
    "learning_events",
)

_DURABLE_JSON_FILES = (
    "instagram_destinations_v1_4.json",
    "telegram_destinations_v2.json",
    "destination_schedules_v1_4.json",
    "publication_target_sets.json",
    "topic_assignments_v1_4_rc4.json",
    "managed_media.json",
    "multi_images_v1_2.json",
    "source_media_hints_v1_2.json",
    # Safe same-day collection checkpoint. The file carries its working_date, so
    # the collector discards it automatically on another day. Preserving it avoids
    # a needless full-day crawl of every Telegram/RSS source immediately after upgrade.
    "rc21_daily_source_coverage.json",
)

_AI_ROUTER_HEADER = b"UA_FREE_AI_ROUTER_AESGCM_V1\n"
_AI_ROUTER_AAD = b"UA_FREE_AI_ROUTER_PROVIDER_SECRETS_V1"
_OPENROUTER_HEADER = b"UA_FREE_OPENROUTER_AESGCM_V1\n"
_OPENROUTER_AAD = b"UA_FREE_Content_Tool_OpenRouter_v2"


@dataclass(slots=True)
class CleanImportReport:
    source: str
    database: str
    tables: dict[str, int]
    config_imported: bool
    imported_files: list[str]
    warnings: list[str]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _locate_old_data(path: str | Path) -> tuple[Path, Path]:
    src = Path(path).expanduser().resolve()
    roots: list[Path] = []
    if src.is_dir():
        roots.extend([src, src / "Data"])
    for root in roots:
        db = root / "content_agent.sqlite3"
        if db.is_file():
            return root, db
    if src.is_file() and src.suffix.casefold() in {".sqlite", ".sqlite3", ".db"}:
        return src.parent, src
    raise FileNotFoundError(f"Не знайдено content_agent.sqlite3 у {src}")


def _columns(con: sqlite3.Connection, table: str) -> list[str]:
    try:
        return [str(row[1]) for row in con.execute(f'PRAGMA table_info("{table}")')]
    except sqlite3.Error:
        return []


def _copy_table(src: sqlite3.Connection, dst: sqlite3.Connection, table: str) -> int:
    source_cols = _columns(src, table)
    target_cols = set(_columns(dst, table))
    cols = [col for col in source_cols if col in target_cols]
    if not cols:
        return 0
    quoted = ",".join('"' + col.replace('"', '""') + '"' for col in cols)
    marks = ",".join("?" for _ in cols)
    rows = src.execute(f'SELECT {quoted} FROM "{table}"').fetchall()
    if rows:
        dst.executemany(
            f'INSERT OR REPLACE INTO "{table}" ({quoted}) VALUES ({marks})',
            [tuple(row) for row in rows],
        )
    return len(rows)


def _import_config(old_root: Path) -> bool:
    portable_cfg = old_root / "config.portable"
    portable_key = old_root / "portable.key"
    dpapi_cfg = old_root / "config.dpapi"
    if portable_cfg.is_file() and portable_key.is_file():
        cfg = load_config(portable_cfg, key_path=portable_key)
    elif dpapi_cfg.is_file():
        cfg = load_config(dpapi_cfg)
    else:
        return False
    # Re-encrypt into the fresh portable key instead of copying legacy key material.
    save_config(cfg, config_path(), key_path=portable_key_path())
    return True


def _validate_secret_bundle(key: Path, secure: Path, *, header: bytes, aad: bytes, label: str) -> None:
    key_bytes = key.read_bytes()
    if len(key_bytes) != 32:
        raise RuntimeError(f"{label}: файл ключа пошкоджено")
    raw = secure.read_bytes()
    if not raw.startswith(header):
        raise RuntimeError(f"{label}: неправильний формат secure-файлу")
    payload = raw[len(header):]
    if len(payload) < 13:
        raise RuntimeError(f"{label}: secure-файл неповний")
    nonce, encrypted = payload[:12], payload[12:]
    try:
        decoded = AESGCM(key_bytes).decrypt(nonce, encrypted, aad)
        values = json.loads(decoded.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"{label}: не вдалося розшифрувати старі налаштування") from exc
    if not isinstance(values, dict):
        raise RuntimeError(f"{label}: розшифровані налаштування мають неправильний формат")


def _copy_secret_bundle(
    old_dir: Path,
    new_dir: Path,
    *,
    key_name: str,
    secure_name: str,
    header: bytes,
    aad: bytes,
    label: str,
    imported: list[str],
    warnings: list[str],
) -> None:
    old_key = old_dir / key_name
    old_secure = old_dir / secure_name
    if not old_key.exists() and not old_secure.exists():
        return
    if not old_key.is_file() or not old_secure.is_file():
        warnings.append(f"{label}: знайдено лише частину пари {key_name}/{secure_name}; пропущено")
        return
    try:
        _validate_secret_bundle(old_key, old_secure, header=header, aad=aad, label=label)
    except Exception as exc:
        warnings.append(str(exc))
        return

    new_dir.mkdir(parents=True, exist_ok=True)
    key_tmp = new_dir / (key_name + ".import.tmp")
    secure_tmp = new_dir / (secure_name + ".import.tmp")
    try:
        shutil.copy2(old_key, key_tmp)
        shutil.copy2(old_secure, secure_tmp)
        # Key first is the safe interruption order: a lone key is harmless, while
        # a secure file without its matching key would appear corrupted on startup.
        os.replace(key_tmp, new_dir / key_name)
        os.replace(secure_tmp, new_dir / secure_name)
    finally:
        key_tmp.unlink(missing_ok=True)
        secure_tmp.unlink(missing_ok=True)
    imported.extend([str((new_dir / key_name).relative_to(data_dir())), str((new_dir / secure_name).relative_to(data_dir()))])


def _copy_json_file(source: Path, target: Path, *, imported: list[str], warnings: list[str]) -> None:
    if not source.is_file():
        return
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except Exception as exc:
        warnings.append(f"{source.name}: пошкоджений JSON, пропущено ({exc})")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".import.tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    imported.append(str(target.relative_to(data_dir())))


def _import_sidecars(old_root: Path) -> tuple[list[str], list[str]]:
    imported: list[str] = []
    warnings: list[str] = []
    target = data_dir()

    _copy_secret_bundle(
        old_root,
        target,
        key_name="ai_router.key",
        secure_name="ai_providers.secure",
        header=_AI_ROUTER_HEADER,
        aad=_AI_ROUTER_AAD,
        label="AI Router",
        imported=imported,
        warnings=warnings,
    )

    old_v2 = old_root / "v2"
    new_v2 = target / "v2"
    _copy_secret_bundle(
        old_v2,
        new_v2,
        key_name="openrouter.key",
        secure_name="openrouter.secure",
        header=_OPENROUTER_HEADER,
        aad=_OPENROUTER_AAD,
        label="OpenRouter",
        imported=imported,
        warnings=warnings,
    )
    _copy_json_file(old_v2 / "ai_backend.json", new_v2 / "ai_backend.json", imported=imported, warnings=warnings)

    for name in _DURABLE_JSON_FILES:
        _copy_json_file(old_root / name, target / name, imported=imported, warnings=warnings)

    # Keep exactly one Supervisor identity file across upgrades. This is durable
    # installation identity, not runtime/incident state. Without it every clean
    # upgrade creates a new Drive instance folder and remote monitoring loses the
    # current process among a pile of historical instance names.
    _copy_json_file(
        old_root / "supervisor" / "instance.json",
        target / "supervisor" / "instance.json",
        imported=imported,
        warnings=warnings,
    )

    return imported, warnings


def clean_import_from_old_data(path: str | Path) -> CleanImportReport:
    old_root, source_db = _locate_old_data(path)
    target_db = database_path()
    target_db.parent.mkdir(parents=True, exist_ok=True)

    # Target schema must already exist. The main startup creates Database first.
    src = sqlite3.connect(f"file:{source_db.as_posix()}?mode=ro", uri=True, timeout=30)
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(target_db, timeout=30)
    summary: dict[str, int] = {}
    try:
        if src.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("Стара база не пройшла SQLite quick_check")
        if dst.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("Нова база не пройшла SQLite quick_check перед імпортом")
        dst.execute("PRAGMA foreign_keys=OFF")
        dst.execute("BEGIN IMMEDIATE")
        for table in reversed(_STABLE_TABLES):
            if _columns(dst, table):
                dst.execute(f'DELETE FROM "{table}"')
        for table in _STABLE_TABLES:
            if _columns(src, table) and _columns(dst, table):
                summary[table] = _copy_table(src, dst, table)
        dst.commit()
        if dst.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("Нова база не пройшла SQLite quick_check після імпорту")
    except Exception:
        dst.rollback()
        raise
    finally:
        dst.close()
        src.close()

    config_imported = _import_config(old_root)
    imported_files, warnings = _import_sidecars(old_root)
    report = CleanImportReport(
        source=str(old_root),
        database=str(source_db),
        tables=summary,
        config_imported=config_imported,
        imported_files=imported_files,
        warnings=warnings,
    )
    marker = migration_dir() / "clean_import.json"
    marker.write_text(json.dumps(report.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def target_has_user_data() -> bool:
    db = database_path()
    if not db.exists() or db.stat().st_size == 0:
        return False
    try:
        con = sqlite3.connect(f"file:{db.resolve().as_posix()}?mode=ro", uri=True, timeout=10)
        try:
            for table in ("sources", "news_groups", "articles", "publication_batches"):
                if _columns(con, table) and con.execute(f'SELECT 1 FROM "{table}" LIMIT 1').fetchone() is not None:
                    return True
        finally:
            con.close()
    except Exception:
        return True
    return False


def first_run_marker() -> Path:
    return migration_dir() / "first_run_choice.json"


def mark_first_run_choice(choice: str, source: str = "") -> None:
    first_run_marker().write_text(
        json.dumps({"choice": choice, "source": source}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
