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
from ...network import dns_resolver_stats
from ...source_health import source_health_map
from ..ai.service import backend_status
from ..ai.settings import load_backend_settings


_PROCESS_STARTED_AT = datetime.now().astimezone()

PROCESS_HANDLE_SOFT_LIMIT = 16000
PROCESS_HANDLE_HARD_LIMIT = 20000
PROCESS_HANDLE_GROWTH_LIMIT = 750


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
    cutoff = max(datetime.now().astimezone() - timedelta(hours=2), _PROCESS_STARTED_AT)
    local_tz = datetime.now().astimezone().tzinfo
    for line in raw.splitlines():
        # Do not turn yesterday's retry storm into a current incident simply
        # because the same log file is still on disk.  If a line starts with a
        # parseable timestamp, only the recent two-hour window is incident data.
        stamp = re.match(r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,6})?(?:[+-]\d{2}:?\d{2})?)", line)
        if stamp:
            try:
                moment = datetime.fromisoformat(stamp.group(1).replace(",", "."))
                if moment.tzinfo is None:
                    moment = moment.replace(tzinfo=local_tz)
                if moment.astimezone(cutoff.tzinfo) < cutoff:
                    continue
            except ValueError:
                pass
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


def _failed_target_metrics(database) -> dict[str, Any]:
    """Separate active publication failures from the 24h historical tail."""
    zero = {
        "failed_targets_15m": 0,
        "failed_targets_60m": 0,
        "failed_targets_24h": 0,
        "last_failed_target_at": "",
    }
    try:
        now = datetime.now(timezone.utc)
        windows = {
            "failed_targets_15m": now - timedelta(minutes=15),
            "failed_targets_60m": now - timedelta(hours=1),
            "failed_targets_24h": now - timedelta(hours=24),
        }
        result: dict[str, Any] = {}
        with database.connect() as db:
            for key, threshold in windows.items():
                row = db.execute(
                    "SELECT COUNT(*) AS n FROM publication_targets WHERE status='failed' AND updated_at>=?",
                    (threshold.isoformat(timespec="seconds"),),
                ).fetchone()
                result[key] = int(row["n"] if row else 0)
            row = db.execute(
                "SELECT MAX(updated_at) AS stamp FROM publication_targets WHERE status='failed'"
            ).fetchone()
            result["last_failed_target_at"] = str(row["stamp"] or "") if row else ""
        return result
    except Exception:
        return zero


def _windows_process_handle_count() -> int:
    if os.name != "nt":
        return -1
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_current_process = kernel32.GetCurrentProcess
        get_current_process.restype = wintypes.HANDLE
        get_handle_count = kernel32.GetProcessHandleCount
        get_handle_count.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        count = wintypes.DWORD()
        if not get_handle_count(get_current_process(), ctypes.byref(count)):
            return -1
        return int(count.value)
    except Exception:
        return -1


def _windows_stdio_limit() -> int:
    if os.name != "nt":
        return -1
    try:
        import ctypes
        msvcrt = ctypes.CDLL("msvcrt")
        getmax = msvcrt._getmaxstdio
        getmax.restype = ctypes.c_int
        return int(getmax())
    except Exception:
        return -1


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
    operation_running = bool(getattr(window, "operation_running", False))
    operation_started = getattr(window, "operation_started_at", None)
    operation_age = 0.0
    if operation_running and operation_started is not None:
        try:
            now_local = datetime.now().astimezone()
            if getattr(operation_started, "tzinfo", None) is None:
                operation_started = operation_started.replace(tzinfo=now_local.tzinfo)
            operation_age = max(0.0, (now_local - operation_started.astimezone(now_local.tzinfo)).total_seconds())
        except Exception:
            operation_age = 0.0
    worker = getattr(window, "worker_thread", None)
    worker_alive = bool(worker is not None and worker.is_alive()) if background_started else True
    publishing_metrics = _failed_target_metrics(database)
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
            "auto_collect_scheduled": bool(getattr(window, "auto_collect_after_id", None)),
            "auto_collect_enabled": bool(
                background_started
                and not getattr(window, "stop_event", threading.Event()).is_set()
                and (bool(getattr(window, "auto_collect_running", False)) or bool(getattr(window, "auto_collect_after_id", None)))
            ),
            "ui_lag_seconds": round(ui_lag, 3),
            "operation_running": operation_running,
            "operation_age_seconds": round(operation_age, 1),
            "operation": (
                str(getattr(getattr(window, "operation_var", None), "get", lambda: "")() or "")[:500]
                if operation_running
                else ""
            ),
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
            **publishing_metrics,
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
            "thread_count": len(threading.enumerate()),
            "process_handle_count": _windows_process_handle_count(),
            "stdio_limit": _windows_stdio_limit(),
            "dns_resolver": dns_resolver_stats(),
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
    handle_count = int(system.get("process_handle_count") or -1)
    supervisor = status.get("supervisor", {}) if isinstance(status.get("supervisor"), dict) else {}
    handles = supervisor.get("handles", {}) if isinstance(supervisor.get("handles"), dict) else {}
    handle_growth = int(handles.get("growth_since_supervisor_start") or 0)
    handle_rate = float(handles.get("estimated_rate_per_hour") or 0.0)
    if handle_count >= PROCESS_HANDLE_HARD_LIMIT:
        out.append({
            "severity": "CRITICAL",
            "code": "PROCESS_HANDLE_PRESSURE",
            "detail": (
                f"Content Tool process handle count is {handle_count} (hard limit {PROCESS_HANDLE_HARD_LIMIT}); "
                f"growth since Supervisor start {handle_growth}, estimated rate {handle_rate:.1f}/h."
            ),
        })
    elif handle_count >= PROCESS_HANDLE_SOFT_LIMIT and handle_growth >= PROCESS_HANDLE_GROWTH_LIMIT:
        out.append({
            "severity": "WARNING",
            "code": "PROCESS_HANDLE_PRESSURE",
            "detail": (
                f"Content Tool process handles are high and growing: current {handle_count}, "
                f"growth {handle_growth} (soft limit {PROCESS_HANDLE_SOFT_LIMIT}, growth trigger "
                f"{PROCESS_HANDLE_GROWTH_LIMIT}), estimated rate {handle_rate:.1f}/h."
            ),
        })
    drive_runtime = supervisor.get("drive_runtime", {}) if isinstance(supervisor.get("drive_runtime"), dict) else {}
    if bool(drive_runtime.get("auth_required")):
        out.append({
            "severity": "WARNING",
            "code": "DRIVE_REAUTH_REQUIRED",
            "detail": (
                "Google Drive authentication is no longer valid. Reconnect Google Drive in the application. "
                "This is a Drive credential incident, not an AI/provider failure."
            ),
        })
    dns = system.get("dns_resolver", {}) if isinstance(system.get("dns_resolver"), dict) else {}
    if int(dns.get("queued") or 0) >= 24:
        out.append({
            "severity": "WARNING",
            "code": "DNS_RESOLVER_PRESSURE",
            "detail": f"Bounded DNS resolver queue is {int(dns.get('queued') or 0)}/32.",
        })
    if 0 <= free < 512 * 1024 * 1024:
        out.append({"severity": "CRITICAL", "code": "DISK_LOW", "detail": f"Free disk space {free} bytes."})
    content = status.get("content", {}) if isinstance(status.get("content"), dict) else {}
    enabled = int(content.get("enabled_sources") or 0)
    errors = int(content.get("source_errors_active") or 0)
    if enabled >= 5 and errors >= max(5, int(enabled * 0.35)):
        out.append({"severity": "WARNING", "code": "SOURCE_FAILURE_WAVE", "detail": f"Active source errors {errors}/{enabled}."})
    publishing = status.get("publishing", {}) if isinstance(status.get("publishing"), dict) else {}
    failed_15m = int(publishing.get("failed_targets_15m") or 0)
    failed_60m = int(publishing.get("failed_targets_60m") or 0)
    failed_24h = int(publishing.get("failed_targets_24h") or 0)
    last_failed_at = str(publishing.get("last_failed_target_at") or "")
    if failed_15m >= 3 or failed_60m >= 5:
        out.append({
            "severity": "WARNING",
            "code": "PUBLISH_FAILURES_ACTIVE",
            "detail": (
                f"Recent failed publication targets: {failed_15m} in 15m, {failed_60m} in 60m "
                f"({failed_24h} in 24h; last={last_failed_at or 'unknown'}). "
                "The 24h count is historical context and is not by itself an active incident."
            ),
        })
    ai = status.get("ai", {}) if isinstance(status.get("ai"), dict) else {}
    active = str(ai.get("active_backend") or "")
    if active == "openrouter" and not bool(ai.get("openrouter_configured")):
        out.append({"severity": "CRITICAL", "code": "OPENROUTER_NOT_CONFIGURED", "detail": "OpenRouter is the active backend but its API key is missing."})
    if active == "openrouter":
        events = ai.get("openrouter_recent_events") if isinstance(ai.get("openrouter_recent_events"), list) else []
        cutoff = datetime.now().astimezone() - timedelta(hours=2)
        process_stamp = str(ai.get("process_started_at") or "").strip()
        if process_stamp:
            try:
                process_start = datetime.fromisoformat(process_stamp.replace("Z", "+00:00"))
                if process_start.tzinfo is None:
                    process_start = process_start.replace(tzinfo=cutoff.tzinfo)
                cutoff = max(cutoff, process_start.astimezone(cutoff.tzinfo))
            except ValueError:
                pass

        def fresh_failure(item: object) -> bool:
            if not isinstance(item, dict) or str(item.get("outcome") or "") not in {"failed", "qa_fail"}:
                return False
            stamp = str(item.get("timestamp") or "").strip()
            if not stamp:
                return False
            try:
                moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                if moment.tzinfo is None:
                    moment = moment.replace(tzinfo=cutoff.tzinfo)
                return moment.astimezone(cutoff.tzinfo) >= cutoff
            except ValueError:
                return False

        recent_failures = [item for item in events[-16:] if fresh_failure(item)]
        if len(recent_failures) >= 3:
            chain = " | ".join(
                f"{item.get('model','?')}:{item.get('kind') or item.get('outcome','failed')}"
                + (f"/finish={item.get('finish_reason')}" if item.get("finish_reason") else "")
                for item in recent_failures[-5:]
            )
            out.append({
                "severity": "WARNING",
                "code": "OPENROUTER_MODEL_FAILURES",
                "detail": f"OpenRouter model-level failures in current process window: {len(recent_failures)}. {chain}"[:1200],
            })
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
        for extra in (
            data_dir() / "ui_freeze_trace.log",
            data_dir() / "ui_startup_freeze_trace.log",
            data_dir() / "v2" / "openrouter_events.jsonl",
        ):
            if extra.exists():
                try:
                    archive.writestr(extra.name, extra.read_bytes()[-256 * 1024:])
                except OSError:
                    pass
    return path
