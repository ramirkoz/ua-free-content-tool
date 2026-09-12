from __future__ import annotations

import json
import logging
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

from ...paths import data_dir
from .analyzer import analyze_with_openrouter
from .diagnostics import collect_status, detect_incidents, diagnostic_bundle, instance_identity, write_json
from .drive_export import SupervisorDriveExporter
from ..ai.settings import load_backend_settings

logger = logging.getLogger("content_agent.v2.supervisor")


class SupervisorRuntime:
    def __init__(self, window, database, config, *, version: str) -> None:
        self.window = window
        self.database = database
        self.config = config
        self.version = version
        self.stop_event = getattr(window, "stop_event", threading.Event())
        self.thread: threading.Thread | None = None
        self._last_signature: tuple[tuple[str, str], ...] = ()
        # A clean startup writes status immediately, but should not spend an
        # OpenRouter call on a HEALTHY report every time the operator restarts.
        # Incidents still generate a report on the first cycle.
        self._last_summary_at = time.monotonic()
        self._last_drive_status_at = 0.0
        self._last_report = ""
        self._last_error = ""
        self._hooks_installed = False
        self._resource_exhaustion_until = 0.0

    def start(self) -> None:
        if self.thread is not None and self.thread.is_alive():
            return
        settings = load_backend_settings()
        if not settings.supervisor_enabled:
            return
        self._install_exception_hooks()
        self.thread = threading.Thread(target=self._loop, name="content-v2-supervisor", daemon=True)
        self.thread.start()


    def _install_exception_hooks(self) -> None:
        if self._hooks_installed:
            return
        self._hooks_installed = True
        uncaught = data_dir() / "supervisor" / "uncaught.jsonl"
        uncaught.parent.mkdir(parents=True, exist_ok=True)
        old_sys = sys.excepthook
        old_thread = getattr(threading, "excepthook", None)

        def append(kind: str, exc_type, exc_value, exc_tb, thread_name: str = "") -> None:
            try:
                payload = {
                    "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "kind": kind,
                    "thread": thread_name,
                    "type": getattr(exc_type, "__name__", str(exc_type)),
                    "message": str(exc_value)[:1200],
                    "traceback": "".join(traceback.format_exception(exc_type, exc_value, exc_tb))[-12000:],
                }
                with uncaught.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
            except Exception:
                pass

        def sys_hook(exc_type, exc_value, exc_tb):
            append("main_thread", exc_type, exc_value, exc_tb, "MainThread")
            try:
                old_sys(exc_type, exc_value, exc_tb)
            except Exception:
                pass

        def thread_hook(args):
            append("thread", args.exc_type, args.exc_value, args.exc_traceback, getattr(args.thread, "name", ""))
            if callable(old_thread):
                try:
                    old_thread(args)
                except Exception:
                    pass

        sys.excepthook = sys_hook
        if old_thread is not None:
            threading.excepthook = thread_hook

    def status_text(self) -> str:
        if self._last_error:
            return "Supervisor: помилка · " + self._last_error[:180]
        if self.thread is None or not self.thread.is_alive():
            return "Supervisor: не запущено"
        suffix = f" · звіт: {self._last_report}" if self._last_report else ""
        return "Supervisor: працює" + suffix

    def _post_status(self) -> None:
        var = getattr(self.window, "v2_supervisor_status_var", None)
        if var is None:
            return
        text = self.status_text()
        poster = getattr(self.window, "_post_ui", None)
        if callable(poster):
            poster(lambda: var.set(text))

    @staticmethod
    def _signature(incidents: list[dict[str, str]]) -> tuple[tuple[str, str], ...]:
        return tuple(sorted((str(item.get("severity") or ""), str(item.get("code") or "")) for item in incidents))

    def _write_report(self, status: dict, incidents: list[dict[str, str]], event: str, bundle: Path | None) -> Path:
        report = analyze_with_openrouter(status, incidents, event=event)
        instance = instance_identity()
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        code = incidents[0]["code"] if incidents else "HEALTHY"
        path = data_dir() / "supervisor" / f"{stamp}_{event}_{code}_{instance.instance_name}.md"
        path.write_text(report, encoding="utf-8")
        self._last_report = path.name
        self._upload_event(status, incidents, path, bundle)
        return path

    def _drive_hierarchy(self, exporter: SupervisorDriveExporter):
        settings = load_backend_settings()
        instance = instance_identity()
        root = exporter.ensure_folder(settings.supervisor_drive_root, "root")
        instances = exporter.ensure_folder("INSTANCES", root)
        instance_folder = exporter.ensure_folder(instance.instance_name, instances)
        diagnostics = exporter.ensure_folder("DIAGNOSTICS", instance_folder)
        resume = exporter.ensure_folder("RESUME", root)
        return instance_folder, diagnostics, resume

    def _upload_event(self, status: dict, incidents: list[dict[str, str]], report: Path, bundle: Path | None) -> None:
        try:
            exporter = SupervisorDriveExporter(self.config)
            instance_folder, diagnostics_folder, resume_folder = self._drive_hierarchy(exporter)
            status_path = write_json("status.json", status)
            incident_path = write_json("incident.json", {"generated_at": status.get("generated_at"), "incidents": incidents})
            exporter.upload_path(status_path, instance_folder, replace=True)
            exporter.upload_path(incident_path, instance_folder, replace=True)
            exporter.upload_path(report, resume_folder, replace=False)
            if bundle is not None and bundle.exists():
                exporter.upload_path(bundle, diagnostics_folder, replace=False)
            self._last_drive_status_at = time.monotonic()
            self._last_error = ""
        except Exception as exc:
            self._last_error = f"Drive export: {exc}"
            logger.warning("Supervisor Drive export failed: %s", exc)

    def _upload_status_only(self, status: dict, incidents: list[dict[str, str]]) -> None:
        try:
            exporter = SupervisorDriveExporter(self.config)
            instance_folder, _diagnostics, _resume = self._drive_hierarchy(exporter)
            status_path = write_json("status.json", status)
            incident_path = write_json("incident.json", {"generated_at": status.get("generated_at"), "incidents": incidents})
            exporter.upload_path(status_path, instance_folder, replace=True)
            exporter.upload_path(incident_path, instance_folder, replace=True)
            self._last_drive_status_at = time.monotonic()
            self._last_error = ""
        except Exception as exc:
            self._last_error = f"Drive status: {exc}"
            logger.warning("Supervisor Drive status upload failed: %s", exc)

    def run_once(self, *, force_report: bool = False) -> dict:
        status = collect_status(self.window, self.database, version=self.version)
        incidents = detect_incidents(status)
        signature = self._signature(incidents)
        write_json("status.json", status)
        write_json("incident.json", {"generated_at": status.get("generated_at"), "incidents": incidents})

        now = time.monotonic()
        settings = load_backend_settings()
        changed = signature != self._last_signature
        periodic = now - self._last_summary_at >= settings.supervisor_summary_interval_minutes * 60
        event = "STATUS"
        should_report = force_report or changed or periodic
        if changed:
            if signature and not self._last_signature:
                event = "INCIDENT"
            elif not signature and self._last_signature:
                event = "RECOVERY"
            else:
                event = "INCIDENT_UPDATE"
        elif force_report:
            event = "MANUAL"
        elif periodic:
            event = "HEALTH_SNAPSHOT"

        if should_report:
            bundle = diagnostic_bundle(status, incidents) if incidents or changed else None
            self._write_report(status, incidents, event, bundle)
            self._last_summary_at = now
        elif now - self._last_drive_status_at >= 5 * 60:
            self._upload_status_only(status, incidents)

        self._last_signature = signature
        self._post_status()
        return status

    def _loop(self) -> None:
        try:
            self.run_once(force_report=False)
        except Exception as exc:
            self._last_error = str(exc)
            detail = str(exc).casefold()
            if (isinstance(exc, OSError) and getattr(exc, "errno", None) == 24) or "too many open files" in detail:
                self._resource_exhaustion_until = time.monotonic() + 10 * 60
            logger.exception("Supervisor initial cycle failed: %s", exc)
            self._post_status()
        while not self.stop_event.is_set():
            interval = load_backend_settings().supervisor_interval_seconds
            if self.stop_event.wait(interval):
                break
            if time.monotonic() < self._resource_exhaustion_until:
                continue
            try:
                self.run_once()
            except Exception as exc:
                self._last_error = str(exc)
                detail = str(exc).casefold()
                if (isinstance(exc, OSError) and getattr(exc, "errno", None) == 24) or "too many open files" in detail:
                    # Do not add one failed status/tmp open every minute while
                    # the process is already out of handles. A ten-minute quiet
                    # period reduces further pressure and log spam.
                    self._resource_exhaustion_until = time.monotonic() + 10 * 60
                logger.exception("Supervisor cycle failed: %s", exc)
                self._post_status()
