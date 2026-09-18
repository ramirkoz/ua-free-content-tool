from __future__ import annotations

import logging
import time
from pathlib import Path

from .diagnostics import collect_status, detect_incidents, diagnostic_bundle, write_json
from .auto_update import AutonomousUpdateManager
from .drive_export import SupervisorDriveExporter
from .runtime import SupervisorRuntime
from ..ai.settings import load_backend_settings

logger = logging.getLogger("content_agent.v2.supervisor.resilient")


class ResilientSupervisorRuntime(SupervisorRuntime):
    """RC11 supervisor: one circuit breaker for all Drive work.

    The control plane used to swallow HTTP 401/403 and therefore the outer runtime
    registered failed polls as successes. RC11 treats transport/auth failure as a
    first-class failure, backs off, drops cached auth state, and keeps all local
    diagnostics/publication services alive while Drive is suppressed.
    """

    AUTH_BACKOFF_SECONDS = 15 * 60
    TRANSIENT_BACKOFF_MAX = 5 * 60
    CONTROL_POLL_INTERVAL = 5 * 60
    STATUS_UPLOAD_INTERVAL = 5 * 60
    HANDLE_GROWTH_SUPPRESS = 160
    HANDLE_RATE_SUPPRESS = 800.0
    HANDLE_ABSOLUTE_SUPPRESS = 6000

    def __init__(self, window, database, config, *, version: str):
        super().__init__(window, database, config, version=version)
        self._drive_backoff_until = 0.0
        self._drive_failures = 0
        self._drive_last_failure = ""
        self._drive_auth_required = False
        self._last_control_poll = 0.0
        self._last_status_upload_attempt = 0.0
        self._handle_baseline = -1
        self._handle_last = -1
        self._handle_last_at = time.monotonic()
        self._drive_suppressed_for_handles = False
        self._exporter: SupervisorDriveExporter | None = None
        self.auto_update = AutonomousUpdateManager(current_version=version)

    @staticmethod
    def _is_auth_error(exc: BaseException) -> bool:
        text = str(exc).casefold()
        return any(x in text for x in (
            "http 401", "http 403", "unauthorized", "invalid_grant",
            "invalid credentials", "access denied", "refresh token",
        ))

    @staticmethod
    def _is_drive_auth_error(exc: BaseException) -> bool:
        """Backward-compatible RC9 classifier name."""
        return ResilientSupervisorRuntime._is_auth_error(exc)

    def _drive_base_allowed(self) -> bool:
        now = time.monotonic()
        return (
            not self._drive_suppressed_for_handles
            and now >= self._drive_backoff_until
            and now >= self._resource_exhaustion_until
        )

    def _control_due(self) -> bool:
        return self._drive_base_allowed() and (
            self._last_control_poll <= 0.0
            or time.monotonic() - self._last_control_poll >= self.CONTROL_POLL_INTERVAL
        )

    def _status_due(self) -> bool:
        return self._drive_base_allowed() and (
            self._last_drive_status_at <= 0.0
            or time.monotonic() - self._last_drive_status_at >= self.STATUS_UPLOAD_INTERVAL
        )

    def _drive(self) -> SupervisorDriveExporter:
        if self._exporter is None:
            self._exporter = SupervisorDriveExporter(self.config)
        return self._exporter

    def _drop_drive_state(self) -> None:
        self._exporter = None
        reset = getattr(self.control, "reset_drive", None)
        if callable(reset):
            try:
                reset()
            except Exception:
                pass

    def _drive_failure(self, exc: BaseException, *, operation: str) -> None:
        self._drive_failures += 1
        self._drive_last_failure = f"{operation}: {exc}"[:600]
        auth_error = self._is_auth_error(exc)
        if auth_error:
            self._drive_auth_required = True
            delay = float(self.AUTH_BACKOFF_SECONDS)
        else:
            delay = min(
                float(self.TRANSIENT_BACKOFF_MAX),
                float(15 * (2 ** min(self._drive_failures - 1, 5))),
            )
        self._drive_backoff_until = max(self._drive_backoff_until, time.monotonic() + delay)
        self._last_error = (
            f"Google Drive: потрібне повторне підключення · {str(exc)[:160]}"
            if auth_error
            else f"Drive backoff {int(delay)}s · {str(exc)[:180]}"
        )
        self._drop_drive_state()
        logger.warning(
            "Supervisor Drive failed; backoff %.0fs operation=%s failures=%s: %s",
            delay, operation, self._drive_failures, exc,
        )

    def _drive_success(self) -> None:
        self._drive_failures = 0
        self._drive_last_failure = ""
        self._drive_auth_required = False
        self._drive_backoff_until = 0.0
        if self._last_error.startswith("Drive backoff"):
            self._last_error = ""

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
        delta = 0 if self._handle_last < 0 else count - self._handle_last
        elapsed = max(1.0, now - self._handle_last_at)
        rate = 0.0 if self._handle_last < 0 else delta * 3600.0 / elapsed
        growth = count - self._handle_baseline
        self._handle_last, self._handle_last_at = count, now

        if (
            count >= self.HANDLE_ABSOLUTE_SUPPRESS
            or growth >= self.HANDLE_GROWTH_SUPPRESS
            or (rate >= self.HANDLE_RATE_SUPPRESS and delta > 0)
        ):
            if not self._drive_suppressed_for_handles:
                logger.error(
                    "Supervisor Drive suppressed for process-handle pressure: count=%s growth=%s rate=%.1f/h",
                    count, growth, rate,
                )
            self._drive_suppressed_for_handles = True
            self._resource_exhaustion_until = max(self._resource_exhaustion_until, now + 30 * 60)
            self._drop_drive_state()

        status.setdefault("supervisor", {})["handles"] = {
            "baseline": self._handle_baseline,
            "current": count,
            "growth_since_supervisor_start": growth,
            "cycle_delta": delta,
            "estimated_rate_per_hour": round(rate, 1),
            "drive_suppressed": self._drive_suppressed_for_handles,
        }

    def _auto_update_idle(self) -> bool:
        if bool(self.control.status().get("busy")):
            return False
        if bool(getattr(self.window, "operation_running", False)):
            return False
        if bool(getattr(self.window, "auto_collect_running", False)):
            return False
        return True

    def _poll_auto_update(self, status: dict) -> None:
        if not self.auto_update.due():
            status["auto_update"] = self.auto_update.status()
            return
        candidate = self.auto_update.check()
        status["auto_update"] = self.auto_update.status()
        if candidate is None or not self._auto_update_idle():
            return
        command = self.auto_update.command_for(candidate)
        if command is None:
            return
        logger.info("Autonomous update accepted target=%s", candidate.version)
        self._upload_status_only(status, detect_incidents(status), force=True)
        self.control.execute_update(command)

    def status_text(self) -> str:
        base = super().status_text()
        state = self.auto_update.status()
        mode = str(state.get("state") or "")
        latest = str(state.get("latest_checked_version") or self.version)
        if mode == "update_available":
            return base + f" · автооновлення: доступне {latest}"
        if mode == "preparing_update":
            return base + f" · автооновлення: готую {latest}"
        if mode == "check_failed":
            return base + " · автооновлення: перевірка не вдалася"
        if mode == "up_to_date":
            return base + " · автооновлення: актуальна"
        return base + " · автооновлення: увімкнено"

    def _annotate_drive(self, status: dict) -> None:
        now = time.monotonic()
        status.setdefault("supervisor", {})["drive_runtime"] = {
            "allowed": self._drive_base_allowed(),
            "failures": self._drive_failures,
            "last_failure": self._drive_last_failure,
            "auth_required": self._drive_auth_required,
            "backoff_seconds_remaining": max(0, int(self._drive_backoff_until - now)),
            "suppressed_for_handles": self._drive_suppressed_for_handles,
            "control_poll_interval_seconds": self.CONTROL_POLL_INTERVAL,
            "status_upload_interval_seconds": self.STATUS_UPLOAD_INTERVAL,
        }

    def _upload_status_only(self, status: dict, incidents: list[dict[str, str]], *, force: bool = False) -> None:
        if not self._drive_base_allowed():
            return
        if not force and not self._status_due():
            return
        self._last_status_upload_attempt = time.monotonic()
        try:
            exporter = self._drive()
            instance_folder, _diag, _resume = self._drive_hierarchy(exporter)
            exporter.upload_path(write_json("status.json", status), instance_folder, replace=True)
            exporter.upload_path(
                write_json("incident.json", {"generated_at": status.get("generated_at"), "incidents": incidents}),
                instance_folder,
                replace=True,
            )
            self._last_drive_status_at = time.monotonic()
            self._drive_success()
        except Exception as exc:
            self._drive_failure(exc, operation="status upload")

    def _upload_event(self, status: dict, incidents: list[dict[str, str]], report: Path, bundle: Path | None) -> None:
        if not self._drive_base_allowed():
            return
        try:
            exporter = self._drive()
            instance_folder, diagnostics_folder, resume_folder = self._drive_hierarchy(exporter)
            exporter.upload_path(write_json("status.json", status), instance_folder, replace=True)
            exporter.upload_path(
                write_json("incident.json", {"generated_at": status.get("generated_at"), "incidents": incidents}),
                instance_folder,
                replace=True,
            )
            exporter.upload_path(report, resume_folder, replace=False)
            if bundle is not None and bundle.exists():
                exporter.upload_path(bundle, diagnostics_folder, replace=False)
            self._last_drive_status_at = time.monotonic()
            self._drive_success()
        except Exception as exc:
            self._drive_failure(exc, operation="event upload")

    def run_once(self, *, force_report: bool = False) -> dict:
        status = collect_status(self.window, self.database, version=self.version)
        self._track_handles(status)
        self._annotate_drive(status)
        status["remote_control"] = self.control.status()
        self._poll_auto_update(status)
        incidents = detect_incidents(status)
        signature = self._signature(incidents)

        command = None
        if self._control_due():
            self._last_control_poll = time.monotonic()
            try:
                command = self.control.poll()
                self._drive_success()
            except Exception as exc:
                self._drive_failure(exc, operation="remote control poll")
                self._annotate_drive(status)

        # Local truth is always written, regardless of Drive/auth health.
        write_json("status.json", status)
        write_json("incident.json", {"generated_at": status.get("generated_at"), "incidents": incidents})

        now = time.monotonic()
        settings = load_backend_settings()
        changed = signature != self._last_signature
        periodic = now - self._last_summary_at >= settings.supervisor_summary_interval_minutes * 60
        remote_report = bool(command is not None and command.command == "report")
        if remote_report:
            force_report = True
        should_report = force_report or remote_report or changed or periodic
        report_path = None
        if should_report:
            event = (
                "REMOTE_REPORT" if remote_report
                else "INCIDENT" if changed and signature and not self._last_signature
                else "RECOVERY" if changed and not signature
                else "INCIDENT_UPDATE" if changed
                else "MANUAL" if force_report
                else "HEALTH_SNAPSHOT"
            )
            bundle = diagnostic_bundle(status, incidents) if incidents or changed else None
            report_path = self._write_report(status, incidents, event, bundle)
            self._last_summary_at = now
        elif self._status_due():
            self._upload_status_only(status, incidents)

        if remote_report and command is not None:
            self.control.complete_report(command, report_name=report_path.name if report_path else self._last_report)
        elif command is not None and command.command == "restart":
            self._upload_status_only(status, incidents, force=True)
            self.control.execute_restart(command)
        elif command is not None and command.command == "update":
            self._upload_status_only(status, incidents, force=True)
            self.control.execute_update(command)

        self._last_signature = signature
        self._post_status()
        return status


__all__ = ["ResilientSupervisorRuntime"]
