from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path

from ...paths import data_dir
from ..ai.settings import load_backend_settings
from .diagnostics import collect_status, detect_incidents, diagnostic_bundle, instance_identity, write_json
from .drive_export import SupervisorDriveExporter
from .runtime import SupervisorRuntime

logger = logging.getLogger("content_agent.v2.supervisor.resilient")


class ResilientSupervisorRuntime(SupervisorRuntime):
    """RC9 supervisor containment for Drive retry storms and Windows handle growth."""

    AUTH_BACKOFF_SECONDS = 15 * 60
    MAX_TRANSIENT_BACKOFF_SECONDS = 5 * 60
    HANDLE_SOFT_LIMIT = 16000
    HANDLE_HARD_LIMIT = 20000

    def __init__(self, window, database, config, *, version: str) -> None:
        super().__init__(window, database, config, version=version)
        self._drive_backoff_until = 0.0
        self._drive_failures = 0
        self._drive_last_failure = ""
        self._handle_baseline = -1
        self._handle_last = -1
        self._handle_last_at = time.monotonic()
        self._handle_growth = 0
        self._drive_suppressed_for_handles = False

    @staticmethod
    def _is_drive_auth_error(exc: BaseException) -> bool:
        text = str(exc).casefold()
        return any(marker in text for marker in (
            "http 401", "http 403", "unauthorized", "invalid_grant",
            "invalid credentials", "access denied", "refresh token",
        ))

    def _drive_allowed(self) -> bool:
        now = time.monotonic()
        if now < self._drive_backoff_until:
            return False
        if now < self._resource_exhaustion_until:
            return False
        return not self._drive_suppressed_for_handles

    def _register_drive_success(self) -> None:
        self._drive_failures = 0
        self._drive_last_failure = ""
        self._drive_backoff_until = 0.0
        self._last_error = ""

    def _register_drive_failure(self, exc: BaseException, *, operation: str) -> None:
        self._drive_failures += 1
        self._drive_last_failure = f"{operation}: {exc}"[:500]
        now = time.monotonic()
        if self._is_drive_auth_error(exc):
            delay = float(self.AUTH_BACKOFF_SECONDS)
        else:
            delay = min(
                float(self.MAX_TRANSIENT_BACKOFF_SECONDS),
                float(15 * (2 ** min(self._drive_failures - 1, 5))),
            )
        self._drive_backoff_until = max(self._drive_backoff_until, now + delay)
        self._last_error = f"Drive backoff {int(delay)}s · {str(exc)[:180]}"
        logger.warning(
            "Supervisor Drive operation failed; backoff %.0fs operation=%s failures=%s: %s",
            delay, operation, self._drive_failures, exc,
        )

    def _track_handles(self, status: dict) -> None:
        try:
            count = int(status.get("system", {}).get("process_handle_count", -1))
        except Exception:
            return
        if count < 0:
            return
        now = time.monotonic()
        if self._handle_baseline < 0:
            self._handle_baseline = count
        previous = self._handle_last
        elapsed = max(1.0, now - self._handle_last_at)
        cycle_delta = 0 if previous < 0 else count - previous
        rate_per_hour = 0.0 if previous < 0 else cycle_delta * 3600.0 / elapsed
        self._handle_last = count
        self._handle_last_at = now
        self._handle_growth = count - self._handle_baseline

        # Expose trend in status/reporting rather than a single opaque absolute count.
        status.setdefault("supervisor", {})["handles"] = {
            "baseline": self._handle_baseline,
            "current": count,
            "growth_since_supervisor_start": self._handle_growth,
            "cycle_delta": cycle_delta,
            "estimated_rate_per_hour": round(rate_per_hour, 1),
            "drive_suppressed": self._drive_suppressed_for_handles,
        }

        # At the observed live counts, secondary Drive polling is less important than
        # keeping the editor/publisher alive. Suppress it until the process restarts.
        if count >= self.HANDLE_HARD_LIMIT or (
            count >= self.HANDLE_SOFT_LIMIT and self._handle_growth >= 750
        ):
            if not self._drive_suppressed_for_handles:
                logger.error(
                    "Supervisor Drive polling suppressed due to Windows handle pressure: count=%s growth=%s rate=%.1f/h",
                    count, self._handle_growth, rate_per_hour,
                )
            self._drive_suppressed_for_handles = True
            self._resource_exhaustion_until = max(self._resource_exhaustion_until, now + 15 * 60)

    def _annotate_supervisor_status(self, status: dict) -> None:
        now = time.monotonic()
        status.setdefault("supervisor", {})["drive_runtime"] = {
            "allowed": self._drive_allowed(),
            "failures": self._drive_failures,
            "last_failure": self._drive_last_failure,
            "backoff_seconds_remaining": max(0, int(self._drive_backoff_until - now)),
            "suppressed_for_handles": self._drive_suppressed_for_handles,
        }

    def _upload_event(self, status: dict, incidents: list[dict[str, str]], report: Path, bundle: Path | None) -> None:
        if not self._drive_allowed():
            return
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
            self._register_drive_success()
        except Exception as exc:
            self._register_drive_failure(exc, operation="event upload")

    def _upload_status_only(self, status: dict, incidents: list[dict[str, str]]) -> None:
        if not self._drive_allowed():
            return
        try:
            exporter = SupervisorDriveExporter(self.config)
            instance_folder, _diagnostics, _resume = self._drive_hierarchy(exporter)
            status_path = write_json("status.json", status)
            incident_path = write_json("incident.json", {"generated_at": status.get("generated_at"), "incidents": incidents})
            exporter.upload_path(status_path, instance_folder, replace=True)
            exporter.upload_path(incident_path, instance_folder, replace=True)
            self._last_drive_status_at = time.monotonic()
            self._register_drive_success()
        except Exception as exc:
            self._register_drive_failure(exc, operation="status upload")

    def run_once(self, *, force_report: bool = False) -> dict:
        status = collect_status(self.window, self.database, version=self.version)
        self._track_handles(status)
        self._annotate_supervisor_status(status)
        status["remote_control"] = self.control.status()
        incidents = detect_incidents(status)
        signature = self._signature(incidents)

        command = None
        if self._drive_allowed():
            try:
                command = self.control.poll()
                self._register_drive_success()
            except Exception as exc:
                self._register_drive_failure(exc, operation="remote control poll")
                self._annotate_supervisor_status(status)
        remote_report = bool(command is not None and command.command == "report")
        if remote_report:
            force_report = True

        write_json("status.json", status)
        write_json("incident.json", {"generated_at": status.get("generated_at"), "incidents": incidents})

        now = time.monotonic()
        settings = load_backend_settings()
        changed = signature != self._last_signature
        periodic = now - self._last_summary_at >= settings.supervisor_summary_interval_minutes * 60
        event = "STATUS"
        should_report = force_report or changed or periodic
        if remote_report:
            event = "REMOTE_REPORT"
        elif changed:
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

        report_path: Path | None = None
        if should_report:
            bundle = diagnostic_bundle(status, incidents) if incidents or changed else None
            report_path = self._write_report(status, incidents, event, bundle)
            self._last_summary_at = now
        elif now - self._last_drive_status_at >= 5 * 60:
            self._upload_status_only(status, incidents)

        if remote_report and command is not None:
            self.control.complete_report(command, report_name=report_path.name if report_path else self._last_report)
        elif command is not None and command.command == "restart":
            self._upload_status_only(status, incidents)
            self.control.execute_restart(command)
        elif command is not None and command.command == "update":
            self._upload_status_only(status, incidents)
            self.control.execute_update(command)

        self._last_signature = signature
        self._post_status()
        return status


__all__ = ["ResilientSupervisorRuntime"]
