from __future__ import annotations

import json
import os
import platform
import re
import shutil
import socket
import threading
import time
import zipfile
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ...paths import data_dir, database_path, logs_dir
from ...source_health import source_health_map
from ..ai.service import backend_status
from ..ai.settings import load_backend_settings


@dataclass(frozen=True, slots=True)
class InstanceIdentity:
    instance_id: str
    instance_name: str
    hostname: str


def _supervisor_dir() -> Path:
    path = data_dir() / "supervisor"
    path.mkdir(parents=True, exist_ok=True)
    return path


def instance_identity() -> InstanceIdentity:
    import uuid
    path = _supervisor_dir() / "instance.json"
    host = socket.gethostname() or "PC"
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            stored_host = str(raw.get("hostname") or "") if isinstance(raw, dict) else ""
            if (
                isinstance(raw, dict)
                and raw.get("instance_id")
                and raw.get("instance_name")
                and (not stored_host or stored_host.casefold() == host.casefold())
            ):
                return InstanceIdentity(
                    str(raw["instance_id"]),
                    str(raw["instance_name"]),
                    stored_host or host,
                )
            # If a complete Data folder was cloned to another PC, the machine
            # must get a new identity so two installations never overwrite the
            # same Drive status files.
        except Exception:
            pass
    uid = uuid.uuid4().hex
    identity = InstanceIdentity(uid, f"CONTENT-{host}-{uid[:6]}", host)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(asdict(identity), ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)
    return identity


def _status_counts(database) -> tuple[dict[str, int], dict[str, int]]:
    groups: dict[str, int] = {}
    batches: dict[str, int] = {}
    try:
        with database.connect() as db:
            for row in db.execute("SELECT status,COUNT(*) AS n FROM news_groups GROUP BY status").fetchall():
                groups[str(row["status"])] = int(row["n"])
            for row in db.execute("SELECT status,COUNT(*) AS n FROM publication_batches GROUP BY status").fetchall():
                batches[str(row["status"])] = int(row["n"])
    except Exception:
        pass
    return groups, batches


def _log_tail_summary() -> dict[str, Any]:
    path = logs_dir() / "content_agent.log"
    if not path.exists():
        return {"warnings": 0, "errors": 0, "top_repeated": []}
    try:
        raw = path.read_bytes()[-384 * 1024:].decode("utf-8", "replace")
    except OSError:
        return {"warnings": 0, "errors": 0, "top_repeated": []}
    warnings = 0
    errors = 0
    signatures: Counter[str] = Counter()
    for line in raw.splitlines():
        if " WARNING " in line:
            warnings += 1
        if " ERROR " in line or " CRITICAL " in line:
            errors += 1
        if " WARNING " not in line and " ERROR " not in line and " CRITICAL " not in line:
            continue
        # Strip timestamp and volatile ids/numbers so a retry storm collapses to
        # one useful signature instead of hundreds of almost-identical lines.
        message = re.sub(r"^\d{4}-\d{2}-\d{2}[^ ]*\s+", "", line)
        message = re.sub(r"\b\d+(?:\.\d+)?\b", "#", message)
        message = re.sub(r"\s+", " ", message).strip()[:280]
        if message:
            signatures[message] += 1
    top = [{"count": count, "signature": signature} for signature, count in signatures.most_common(8)]
    return {"warnings": warnings, "errors": errors, "top_repeated": top}


def _failed_targets_recent(database, hours: int = 24) -> int:
    try:
        threshold = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
        with database.connect() as db:
            row = db.execute(
                "SELECT COUNT(*) AS n FROM publication_targets WHERE status='failed' AND updated_at>=?",
                (threshold,),
            ).fetchone()
        return int(row["n"] if row else 0)
    except Exception:
        return 0


def collect_status(window, database, *, version: str) -> dict[str, Any]:
    identity = instance_identity()
    generated = datetime.now().astimezone().isoformat(timespec="seconds")
    groups, batches = _status_counts(database)
    db_ok = True
    db_error = ""
    try:
        database.quick_check()
    except Exception as exc:
        db_ok = False
        db_error = str(exc)[:800]
    sources = []
    source_errors = []
    try:
        sources = list(database.list_sources(enabled_only=False))
        health = source_health_map(database)
        for source in sources:
            row = health.get(int(source.id))
            if row is None:
                continue
            last_error_at = str(getattr(row, "last_error_at", "") or "")
            last_success_at = str(getattr(row, "last_success_at", "") or "")
            if last_error_at and (not last_success_at or last_error_at >= last_success_at):
                source_errors.append({
                    "source_id": int(source.id),
                    "name": str(source.name),
                    "error": str(getattr(row, "last_error", "") or "")[:500],
                    "last_error_at": last_error_at,
                })
    except Exception:
        pass
    try:
        today_articles = int(database.count_today_articles())
    except Exception:
        today_articles = -1
    try:
        disk = shutil.disk_usage(data_dir())
        disk_free = int(disk.free)
    except Exception:
        disk_free = -1
    ui_lag = max(0.0, time.monotonic() - float(getattr(window, "_ui_last_pulse", time.monotonic())))
    background_started = bool(getattr(window, "background_services_started", False))
    operation_started = getattr(window, "operation_started_at", None)
    operation_age = 0.0
    if operation_started is not None:
        try:
            now_local = datetime.now().astimezone()
            if getattr(operation_started, "tzinfo", None) is None:
                operation_started = operation_started.replace(tzinfo=now_local.tzinfo)
            operation_age = max(0.0, (now_local - operation_started.astimezone(now_local.tzinfo)).total_seconds())
        except Exception:
            operation_age = 0.0
    worker = getattr(window, "worker_thread", None)
    worker_alive = bool(worker is not None and worker.is_alive()) if background_started else True
    settings = load_backend_settings()
    return {
        "schema": "ua-free-content-tool-supervisor-v2",
        "generated_at": generated,
        "version": version,
        "instance": asdict(identity),
        "runtime": {
            "background_started": background_started,
            "worker_alive": worker_alive,
            "auto_collect_running": bool(getattr(window, "auto_collect_running", False)),
            "ui_lag_seconds": round(ui_lag, 3),
            "operation_running": bool(getattr(window, "operation_running", False)),
            "operation_age_seconds": round(operation_age, 1),
            "operation": str(getattr(getattr(window, "operation_var", None), "get", lambda: "")() or "")[:500],
            "threads": [item.name for item in threading.enumerate()],
        },
        "database": {
            "ok": db_ok,
            "error": db_error,
            "path": str(database_path()),
            "size_bytes": database_path().stat().st_size if database_path().exists() else 0,
        },
        "content": {
            "today_articles": today_articles,
            "groups": groups,
            "enabled_sources": sum(1 for row in sources if bool(getattr(row, "enabled", False))),
            "sources_total": len(sources),
            "source_errors_active": len(source_errors),
            "source_errors": source_errors[:20],
        },
        "publishing": {
            "batches": batches,
            "failed_targets_24h": _failed_targets_recent(database),
        },
        "ai": backend_status(),
        "logs": _log_tail_summary(),
        "supervisor": {
            "enabled": settings.supervisor_enabled,
            "drive_root": settings.supervisor_drive_root,
        },
        "system": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "hostname": socket.gethostname(),
            "disk_free_bytes": disk_free,
        },
    }


def detect_incidents(status: dict[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if not bool(status.get("database", {}).get("ok", True)):
        out.append({"severity": "CRITICAL", "code": "DATABASE_ERROR", "detail": str(status.get("database", {}).get("error", ""))})
    runtime = status.get("runtime", {}) if isinstance(status.get("runtime"), dict) else {}
    if bool(runtime.get("background_started")) and not bool(runtime.get("worker_alive")):
        out.append({"severity": "CRITICAL", "code": "PUBLISH_WORKER_DEAD", "detail": "Publication worker thread is not alive."})
    if bool(runtime.get("operation_running")) and float(runtime.get("operation_age_seconds") or 0.0) >= 900:
        out.append({"severity": "WARNING", "code": "LONG_OPERATION", "detail": f"Foreground/background operation age {float(runtime.get('operation_age_seconds') or 0.0):.0f}s: {runtime.get('operation','')}"})
    lag = float(runtime.get("ui_lag_seconds") or 0.0)
    if lag >= 12:
        out.append({"severity": "CRITICAL" if lag >= 30 else "WARNING", "code": "UI_STALLED", "detail": f"UI heartbeat lag {lag:.1f}s."})
    system = status.get("system", {}) if isinstance(status.get("system"), dict) else {}
    free = int(system.get("disk_free_bytes") or -1)
    if 0 <= free < 512 * 1024 * 1024:
        out.append({"severity": "CRITICAL", "code": "DISK_LOW", "detail": f"Free disk space {free} bytes."})
    content = status.get("content", {}) if isinstance(status.get("content"), dict) else {}
    enabled = int(content.get("enabled_sources") or 0)
    errors = int(content.get("source_errors_active") or 0)
    if enabled >= 5 and errors >= max(5, int(enabled * 0.35)):
        out.append({"severity": "WARNING", "code": "SOURCE_FAILURE_WAVE", "detail": f"Active source errors {errors}/{enabled}."})
    publishing = status.get("publishing", {}) if isinstance(status.get("publishing"), dict) else {}
    failed_targets = int(publishing.get("failed_targets_24h") or 0)
    if failed_targets >= 5:
        out.append({"severity": "WARNING", "code": "PUBLISH_FAILURES", "detail": f"Failed publication targets in 24h: {failed_targets}."})
    ai = status.get("ai", {}) if isinstance(status.get("ai"), dict) else {}
    active = str(ai.get("active_backend") or "")
    if active == "openrouter" and not bool(ai.get("openrouter_configured")):
        out.append({"severity": "CRITICAL", "code": "OPENROUTER_NOT_CONFIGURED", "detail": "OpenRouter is the active backend but its API key is missing."})
    if active == "router":
        router = ai.get("router") if isinstance(ai.get("router"), dict) else {}
        configured = int(router.get("configured_providers") or 0)
        available = int(router.get("available_providers") or 0)
        if configured > 0 and available == 0:
            out.append({"severity": "CRITICAL", "code": "AI_ROUTER_DOWN", "detail": f"Configured providers {configured}, available providers 0."})
    logs = status.get("logs", {}) if isinstance(status.get("logs"), dict) else {}
    repeated = logs.get("top_repeated") if isinstance(logs.get("top_repeated"), list) else []
    if repeated and isinstance(repeated[0], dict) and int(repeated[0].get("count") or 0) >= 20:
        out.append({"severity": "WARNING", "code": "RETRY_STORM", "detail": f"Repeated warning/error x{repeated[0].get('count')}: {repeated[0].get('signature','')}"})
    return out


def write_json(name: str, payload: object) -> Path:
    path = _supervisor_dir() / name
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)
    return path


def diagnostic_bundle(status: dict[str, Any], incidents: list[dict[str, str]]) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    code = incidents[0]["code"] if incidents else "SNAPSHOT"
    path = _supervisor_dir() / f"ContentTool_Diagnostic_{stamp}_{code}.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("status.json", json.dumps(status, ensure_ascii=False, indent=2))
        archive.writestr("incidents.json", json.dumps(incidents, ensure_ascii=False, indent=2))
        archive.writestr("environment.txt", f"pid={os.getpid()}\nthreads={threading.active_count()}\n")
        for log_path in sorted(logs_dir().glob("*.log*"))[:20]:
            try:
                data = log_path.read_bytes()
            except OSError:
                continue
            archive.writestr(f"logs/{log_path.name}", data[-256 * 1024:])
        for extra in (data_dir() / "ui_freeze_trace.log", data_dir() / "ui_startup_freeze_trace.log"):
            if extra.exists():
                try:
                    archive.writestr(extra.name, extra.read_bytes()[-256 * 1024:])
                except OSError:
                    pass
    return path
