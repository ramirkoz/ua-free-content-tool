from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import dataclass, asdict
from pathlib import Path

from .config import load_config, save_config
from .paths import config_path, data_dir, database_path, migration_dir, portable_key_path

# Durable editorial/user state only. Runtime cooldowns, source-health state,
# migration scratch tables, old archives, logs, cache and Tools are excluded.
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


@dataclass(slots=True)
class CleanImportReport:
    source: str
    database: str
    tables: dict[str, int]
    config_imported: bool

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
    save_config(cfg, config_path(), key_path=portable_key_path())
    return True


def clean_import_from_old_data(path: str | Path) -> CleanImportReport:
    old_root, source_db = _locate_old_data(path)
    target_db = database_path()
    target_db.parent.mkdir(parents=True, exist_ok=True)

    # Target schema must already exist.  The main startup creates Database first.
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
    report = CleanImportReport(
        source=str(old_root),
        database=str(source_db),
        tables=summary,
        config_imported=config_imported,
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
