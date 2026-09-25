from __future__ import annotations

import copy
import logging
import threading
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
    STATUS_UPLOAD_INTERVAL = 60
    HEARTBEAT_START_DELAY = 5
    HEARTBEAT_INTERVAL = 60
    HANDLE_GROWTH_SUPPRESS = 160
    HANDLE_RATE_SUPPRESS = 800.0
    HANDLE_ABSOLUTE_SUPPRESS = 6000
    HANDLE_SUPPRESS_SECONDS = 5 * 60
    HANDLE_RECOVERY_STABLE_CYCLES = 3

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
        self._handle_type_baseline: dict[str, int] = {}
        self._drive_suppressed_for_handles = False
        self._drive_suppressed_until = 0.0
        self._handle_recovery_streak = 0
        self._drive_last_success_at = ""
        self._drive_last_attempt_at = ""
        self._exporter: SupervisorDriveExporter | None = None
        self._drive_io_lock = threading.RLock()
        self._state_lock = threading.RLock()
        self._heartbeat_thread: threading.Thread | None = None
        self._heartbeat_last_attempt_at = ""
        self._heartbeat_last_success_at = ""
        self._heartbeat_last_error = ""
        self._heartbeat_sequence = 0
        self._heartbeat_exporter: SupervisorDriveExporter | None = None
        self._heartbeat_instance_folder = ""
        self._heartbeat_backoff_until = 0.0
        self._heartbeat_failures = 0
        self._heartbeat_auth_required = False
        self._heartbeat_transport_lock = threading.RLock()
        self._heartbeat_wakeup = threading.Event()
        self._snapshot_lock = threading.RLock()
        self._latest_status_snapshot: dict = {}
        self._latest_incidents_snapshot: list[dict[str, str]] = []
        self._main_snapshot_monotonic = 0.0
        self._main_snapshot_at = ""
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
            and now >= self._drive_suppressed_until
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
        from datetime import datetime
        self._drive_failures = 0
        self._drive_last_failure = ""
        self._drive_auth_required = False
        self._drive_backoff_until = 0.0
        self._drive_last_success_at = datetime.now().astimezone().isoformat(timespec="seconds")
        if self._last_error.startswith(("Drive backoff", "Google Drive:", "Drive status:", "Drive export:")):
            self._last_error = ""

    def _track_handles(self, status: dict) -> None:
        with self._state_lock:
            self._track_handles_unlocked(status)

    def _track_handles_unlocked(self, status: dict) -> None:
        try:
            count = int(status.get("system", {}).get("process_handle_count", -1))
        except Exception:
            return
        if count < 0:
            return
        now = time.monotonic()
        if self._handle_baseline < 0:
            self._handle_baseline = count
        system = status.get("system", {}) if isinstance(status.get("system"), dict) else {}
        current_types_raw = system.get("process_handle_types", {}) if isinstance(system.get("process_handle_types"), dict) else {}
        current_types = {str(k): int(v) for k, v in current_types_raw.items() if isinstance(v, (int, float))}
        if not self._handle_type_baseline and current_types:
            self._handle_type_baseline = dict(current_types)
        type_growth = {
            name: int(value) - int(self._handle_type_baseline.get(name, 0))
            for name, value in current_types.items()
        }
        type_growth = dict(sorted(type_growth.items(), key=lambda item: (-item[1], item[0]))[:16])
        delta = 0 if self._handle_last < 0 else count - self._handle_last
        elapsed = max(1.0, now - self._handle_last_at)
        rate = 0.0 if self._handle_last < 0 else delta * 3600.0 / elapsed
        growth = count - self._handle_baseline
        self._handle_last, self._handle_last_at = count, now

        pressure = bool(
            count >= self.HANDLE_ABSOLUTE_SUPPRESS
            or growth >= self.HANDLE_GROWTH_SUPPRESS
            or (rate >= self.HANDLE_RATE_SUPPRESS and delta > 0)
        )
        if not self._drive_suppressed_for_handles and pressure:
            logger.error(
                "Supervisor Drive temporarily suppressed for process-handle pressure: count=%s growth=%s rate=%.1f/h",
                count, growth, rate,
            )
            self._drive_suppressed_for_handles = True
            self._drive_suppressed_until = now + float(self.HANDLE_SUPPRESS_SECONDS)
            self._resource_exhaustion_until = max(self._resource_exhaustion_until, now + 60.0)
            self._handle_recovery_streak = 0
            self._drop_drive_state()
        elif self._drive_suppressed_for_handles:
            # A lifetime-growth threshold must not make Drive suppression permanent.
            # Once the process is stable and the cooldown elapsed, accept the new
            # handle count as the baseline and probe Drive again.
            stable = bool(
                count < self.HANDLE_ABSOLUTE_SUPPRESS
                and abs(delta) <= 4
                and abs(rate) < 240.0
            )
            if now >= self._drive_suppressed_until and stable:
                self._handle_recovery_streak += 1
                if self._handle_recovery_streak >= int(self.HANDLE_RECOVERY_STABLE_CYCLES):
                    self._drive_suppressed_for_handles = False
                    self._drive_suppressed_until = 0.0
                    self._handle_recovery_streak = 0
                    self._handle_baseline = count
                    self._drop_drive_state()
                    logger.info("Supervisor Drive suppression recovered; new handle baseline=%s", count)
            elif now >= self._drive_suppressed_until:
                self._handle_recovery_streak = 0
                self._drive_suppressed_until = now + 60.0

        status.setdefault("supervisor", {})["handles"] = {
            "baseline": self._handle_baseline,
            "current": count,
            "growth_since_supervisor_start": count - self._handle_baseline,
            "cycle_delta": delta,
            "estimated_rate_per_hour": round(rate, 1),
            "drive_suppressed": self._drive_suppressed_for_handles,
            "suppression_seconds_remaining": max(0, int(self._drive_suppressed_until - now)),
            "recovery_streak": self._handle_recovery_streak,
            "types_current": current_types,
            "types_growth": type_growth,
        }

    def _ensure_heartbeat_thread(self) -> None:
        if self.stop_event.is_set():
            return
        if self._heartbeat_thread is not None and self._heartbeat_thread.is_alive():
            return
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="content-v2-drive-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def start(self) -> None:
        super().start()
        if self.thread is None or not self.thread.is_alive():
            return
        self._ensure_heartbeat_thread()

    def _remember_snapshot(self, status: dict, incidents: list[dict[str, str]]) -> None:
        from datetime import datetime
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._snapshot_lock:
            self._latest_status_snapshot = copy.deepcopy(status)
            self._latest_incidents_snapshot = copy.deepcopy(incidents)
            self._main_snapshot_monotonic = time.monotonic()
            self._main_snapshot_at = stamp

    def _snapshot_for_heartbeat(self) -> tuple[dict, list[dict[str, str]], float, str]:
        with self._snapshot_lock:
            status = copy.deepcopy(self._latest_status_snapshot)
            incidents = copy.deepcopy(self._latest_incidents_snapshot)
            snap_mono = float(self._main_snapshot_monotonic or 0.0)
            snap_at = str(self._main_snapshot_at or "")
        age = max(0.0, time.monotonic() - snap_mono) if snap_mono > 0.0 else -1.0
        if not status:
            status = {
                "schema": "ua-free-content-tool-supervisor-v2",
                "version": self.version,
                "runtime": {
                    "threads": [item.name for item in threading.enumerate()],
                },
                "supervisor": {"enabled": True},
            }
            incidents = [{
                "severity": "WARNING",
                "code": "SUPERVISOR_SNAPSHOT_UNAVAILABLE",
                "detail": "Main supervisor has not completed a status snapshot yet; heartbeat transport is still alive.",
            }]
        return status, incidents, age, snap_at

    def _heartbeat_allowed(self) -> bool:
        return (not self._heartbeat_auth_required) and time.monotonic() >= self._heartbeat_backoff_until

    def _drop_heartbeat_drive_state(self) -> None:
        self._heartbeat_exporter = None
        self._heartbeat_instance_folder = ""

    def _heartbeat_drive(self) -> SupervisorDriveExporter:
        if self._heartbeat_exporter is None:
            self._heartbeat_exporter = SupervisorDriveExporter(self.config)
        return self._heartbeat_exporter

    def _heartbeat_folder(self) -> str:
        if self._heartbeat_instance_folder:
            return self._heartbeat_instance_folder
        exporter = self._heartbeat_drive()
        instance_folder, _diag, _resume = self._drive_hierarchy(exporter)
        self._heartbeat_instance_folder = instance_folder
        return instance_folder

    def _heartbeat_failure(self, exc: BaseException) -> None:
        self._heartbeat_failures += 1
        self._heartbeat_auth_required = self._is_auth_error(exc)
        delay = float(self.AUTH_BACKOFF_SECONDS) if self._heartbeat_auth_required else min(120.0, float(10 * (2 ** min(self._heartbeat_failures - 1, 4))))
        self._heartbeat_backoff_until = time.monotonic() + delay
        self._heartbeat_last_error = f"{type(exc).__name__}: {exc}"[:600]
        self._drop_heartbeat_drive_state()
        logger.warning("Independent heartbeat transport failed; retry in %.0fs: %s", delay, exc)

    def _heartbeat_success(self) -> None:
        self._heartbeat_failures = 0
        self._heartbeat_auth_required = False
        self._heartbeat_backoff_until = 0.0
        self._heartbeat_last_error = ""
        self._drive_last_success_at = self._heartbeat_last_success_at

    def _heartbeat_upload(self, status: dict, incidents: list[dict[str, str]]) -> bool:
        if not self._heartbeat_allowed():
            return False
        from datetime import datetime
        self._heartbeat_last_attempt_at = datetime.now().astimezone().isoformat(timespec="seconds")
        try:
            # RC21: status/incident have one owner: this dedicated heartbeat transport.
            # It never waits for the main supervisor's Drive/report lock, so a slow
            # report upload cannot freeze remote liveness telemetry.
            with self._heartbeat_transport_lock:
                exporter = self._heartbeat_drive()
                instance_folder = self._heartbeat_folder()
                exporter.upload_json("status.json", status, instance_folder, replace=True)
                exporter.upload_json(
                    "incident.json",
                    {"generated_at": status.get("generated_at"), "incidents": incidents},
                    instance_folder,
                    replace=True,
                )
                # One stable pointer makes the currently running instance easy to
                # locate without scanning RESUME or guessing which historical
                # instance folder belongs to this launch.
                settings = load_backend_settings()
                root_folder = exporter.ensure_folder(settings.supervisor_drive_root, "root")
                from .diagnostics import instance_identity
                ident = instance_identity()
                exporter.upload_json(
                    "CURRENT.json",
                    {
                        "schema": "ua-free-content-tool-supervisor-current-v1",
                        "version": self.version,
                        "generated_at": status.get("generated_at"),
                        "instance_id": ident.instance_id,
                        "instance_name": ident.instance_name,
                        "instance_folder_id": instance_folder,
                        "status_file": "status.json",
                        "incident_file": "incident.json",
                    },
                    root_folder,
                    replace=True,
                )
            self._last_drive_status_at = time.monotonic()
            self._heartbeat_last_success_at = datetime.now().astimezone().isoformat(timespec="seconds")
            self._heartbeat_success()
            return True
        except Exception as exc:
            self._heartbeat_failure(exc)
            return False

    def _heartbeat_loop(self) -> None:
        if self.stop_event.wait(float(self.HEARTBEAT_START_DELAY)):
            return
        while not self.stop_event.is_set():
            started = time.monotonic()
            try:
                # RC20: the heartbeat must never call the full collect_status().
                # That path touches DB/AI/UI state and can legitimately stall.
                # Instead, use the latest completed main-supervisor snapshot and
                # keep the cloud heartbeat alive even when the main collector is stale.
                self._heartbeat_sequence += 1
                status, incidents, snapshot_age, snapshot_at = self._snapshot_for_heartbeat()
                from datetime import datetime
                status["generated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
                settings = load_backend_settings()
                stale_after = max(180.0, float(settings.supervisor_interval_seconds) * 2.5)
                main_thread_alive = bool(self.thread is not None and self.thread.is_alive())
                main_stale = snapshot_age < 0.0 or snapshot_age >= stale_after
                status.setdefault("supervisor", {})["independent_heartbeat"] = {
                    "sequence": self._heartbeat_sequence,
                    "thread_alive": True,
                    "main_supervisor_thread_alive": main_thread_alive,
                    "main_supervisor_stale": main_stale,
                    "main_snapshot_at": snapshot_at,
                    "main_snapshot_age_seconds": round(snapshot_age, 1) if snapshot_age >= 0.0 else -1.0,
                    "stale_after_seconds": int(stale_after),
                    "last_attempt_at": self._heartbeat_last_attempt_at,
                    "last_success_at": self._heartbeat_last_success_at,
                    "last_error": self._heartbeat_last_error,
                    "interval_seconds": self.HEARTBEAT_INTERVAL,
                }
                if main_stale and not any(str(x.get("code") or "") == "SUPERVISOR_MAIN_STALE" for x in incidents):
                    incidents.append({
                        "severity": "WARNING",
                        "code": "SUPERVISOR_MAIN_STALE",
                        "detail": (
                            "Main supervisor status snapshot is stale "
                            f"({snapshot_age:.0f}s old); independent Drive heartbeat is still alive."
                            if snapshot_age >= 0.0
                            else "Main supervisor has not completed a status snapshot; independent Drive heartbeat is still alive."
                        ),
                    })
                self._annotate_drive(status)
                # Local telemetry is unconditional. Drive may be offline/auth-expired,
                # but the program must still leave a current heartbeat for diagnostics.
                try:
                    write_json("heartbeat.json", status)
                    write_json("heartbeat_incident.json", {"generated_at": status.get("generated_at"), "incidents": incidents})
                except Exception as exc:
                    logger.warning("Local supervisor heartbeat write failed: %s", exc)
                self._heartbeat_upload(status, incidents)
            except Exception as exc:
                self._heartbeat_last_error = f"{type(exc).__name__}: {exc}"[:600]
                logger.exception("Independent Drive heartbeat failed: %s", exc)
            try:
                self._post_status()
            except Exception:
                pass
            elapsed = time.monotonic() - started
            wait_for = max(1.0, float(self.HEARTBEAT_INTERVAL) - elapsed)
            self._heartbeat_wakeup.wait(wait_for)
            self._heartbeat_wakeup.clear()
            if self.stop_event.is_set():
                break

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
        main_alive = bool(self.thread is not None and self.thread.is_alive())
        heartbeat_alive = bool(self._heartbeat_thread is not None and self._heartbeat_thread.is_alive())
        if not main_alive and not heartbeat_alive:
            return "Supervisor: не запущено"
        now = time.monotonic()
        if self._drive_auth_required:
            drive = "Drive: потрібне повторне підключення"
        elif self._drive_suppressed_for_handles:
            drive = f"Drive: пауза через handles · {max(0, int(self._drive_suppressed_until-now))} с"
        elif self._heartbeat_failures:
            drive = f"Drive heartbeat: ERROR · {self._heartbeat_last_error[:120]}"
        elif self._drive_failures:
            drive = f"Drive reports/control: ERROR · {self._drive_last_failure[:120]}"
        elif self._heartbeat_last_success_at:
            drive = f"Drive: OK · {self._heartbeat_last_success_at}"
        elif self._drive_last_success_at:
            drive = f"Drive: OK · {self._drive_last_success_at}"
        else:
            drive = "Drive: очікує першого heartbeat"

        state = self.auto_update.status()
        mode = str(state.get("state") or "")
        latest = str(state.get("latest_checked_version") or self.version)
        if mode == "disabled_manual_test":
            update = "автооновлення: вимкнено (manual test)"
        elif mode == "update_available":
            update = f"автооновлення: доступне {latest}"
        elif mode == "preparing_update":
            update = f"автооновлення: готую {latest}"
        elif mode == "check_failed":
            update = "автооновлення: перевірка не вдалася"
        elif mode == "up_to_date":
            update = "автооновлення: актуальна"
        else:
            update = "автооновлення: увімкнено"
        report = f" · звіт: {self._last_report}" if self._last_report else ""
        threads = (
            "main+heartbeat" if main_alive and heartbeat_alive
            else "heartbeat-only" if heartbeat_alive
            else "main-only"
        )
        return f"Supervisor: працює ({threads}) · {drive} · {update}{report}"

    def _annotate_drive(self, status: dict) -> None:
        now = time.monotonic()
        status.setdefault("supervisor", {})["drive_runtime"] = {
            "allowed": self._drive_base_allowed(),
            "failures": self._drive_failures,
            "last_failure": self._drive_last_failure,
            "auth_required": self._drive_auth_required,
            "backoff_seconds_remaining": max(0, int(self._drive_backoff_until - now)),
            "suppressed_for_handles": self._drive_suppressed_for_handles,
            "suppression_seconds_remaining": max(0, int(self._drive_suppressed_until - now)),
            "last_attempt_at": self._drive_last_attempt_at,
            "last_success_at": self._drive_last_success_at,
            "control_poll_interval_seconds": self.CONTROL_POLL_INTERVAL,
            "status_upload_interval_seconds": self.STATUS_UPLOAD_INTERVAL,
            "independent_heartbeat_interval_seconds": self.HEARTBEAT_INTERVAL,
            "heartbeat_thread_alive": bool(self._heartbeat_thread is not None and self._heartbeat_thread.is_alive()),
            "heartbeat_last_attempt_at": self._heartbeat_last_attempt_at,
            "heartbeat_last_success_at": self._heartbeat_last_success_at,
            "heartbeat_last_error": self._heartbeat_last_error,
            "heartbeat_sequence": self._heartbeat_sequence,
            "heartbeat_transport_allowed": self._heartbeat_allowed(),
            "heartbeat_transport_failures": self._heartbeat_failures,
            "heartbeat_transport_auth_required": self._heartbeat_auth_required,
            "heartbeat_transport_backoff_seconds_remaining": max(0, int(self._heartbeat_backoff_until - now)),
        }

    def _upload_status_only(self, status: dict, incidents: list[dict[str, str]], *, force: bool = False) -> None:
        # RC21: the main supervisor never writes status/incident to Drive. It only
        # refreshes the in-memory truth and wakes the dedicated heartbeat owner.
        self._remember_snapshot(status, incidents)
        self._heartbeat_wakeup.set()


    def _upload_event(self, status: dict, incidents: list[dict[str, str]], report: Path, bundle: Path | None) -> None:
        if not self._drive_base_allowed():
            return
        from datetime import datetime
        self._drive_last_attempt_at = datetime.now().astimezone().isoformat(timespec="seconds")
        try:
            # Reports/diagnostic bundles may be slow, but they no longer own or lock
            # the liveness heartbeat files.
            with self._drive_io_lock:
                exporter = self._drive()
                _instance_folder, diagnostics_folder, resume_folder = self._drive_hierarchy(exporter)
                exporter.upload_path(report, resume_folder, replace=False)
                if bundle is not None and bundle.exists():
                    exporter.upload_path(bundle, diagnostics_folder, replace=False)
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
        # Publish a safe in-memory snapshot before any remote Drive/control work.
        # The independent heartbeat consumes this copy and therefore cannot be
        # blocked by DB/AI/UI collection on its own thread.
        self._remember_snapshot(status, incidents)
        self._ensure_heartbeat_thread()
        self._heartbeat_wakeup.set()

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
