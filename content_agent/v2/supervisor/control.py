from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from ...paths import data_dir
from ...restart_helper_v1_4_rc29 import schedule_delayed_restart
from ..ai.settings import load_backend_settings
from .diagnostics import instance_identity
from .drive_export import SupervisorDriveExporter
from .updater import prepare_update, wait_for_preflight

logger = logging.getLogger("content_agent.v2.supervisor.control")
_REQUEST_RE = re.compile(r"^[A-Za-z0-9._-]{8,96}$")
_VERSION_RE = re.compile(r"^2\.0\.0-rc[1-9]\d*$")
_ALLOWED_COMMANDS = {"report", "restart", "update"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _state_path() -> Path:
    path = data_dir() / "supervisor" / "control_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _pending_result_path() -> Path:
    return data_dir() / "supervisor" / "control_result_pending.json"


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _parse_time(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class RemoteCommand:
    request_id: str
    command: str
    created_at: str
    target_version: str = ""


class RemoteControlManager:
    """Narrow Google Drive control plane.

    The Drive account is already authenticated by the application. A remote file
    may request only three fixed operations: report, restart, update-to-version.
    There is intentionally no shell/command/path/URL field in the protocol.
    """

    def __init__(self, window, config, *, version: str) -> None:
        self.window = window
        self.config = config
        self.version = str(version)
        self.identity = instance_identity()
        self._lock = threading.RLock()
        self._exporter: SupervisorDriveExporter | None = None
        self._control_folder_id = ""
        self._busy = False
        self._last_error = ""
        self._last_command = ""
        self._last_result = ""

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": True,
                "protocol": "ua-free-content-tool-control-v1",
                "instance_id": self.identity.instance_id,
                "control_folder": "CONTROL",
                "busy": self._busy,
                "last_command": self._last_command,
                "last_result": self._last_result,
                "last_error": self._last_error,
            }

    def _load_state(self) -> dict[str, Any]:
        try:
            raw = json.loads(_state_path().read_text(encoding="utf-8"))
        except Exception:
            raw = {}
        return raw if isinstance(raw, dict) else {}

    def _processed(self, request_id: str) -> bool:
        state = self._load_state()
        rows = state.get("processed") if isinstance(state.get("processed"), list) else []
        return request_id in {str(x) for x in rows}

    def _mark_processed(self, request_id: str) -> None:
        state = self._load_state()
        rows = [str(x) for x in (state.get("processed") or []) if str(x)]
        rows = [x for x in rows if x != request_id]
        rows.append(request_id)
        _atomic_json(_state_path(), {"processed": rows[-64:], "updated_at": _now_iso()})

    def _drive(self) -> SupervisorDriveExporter:
        if self._exporter is None:
            self._exporter = SupervisorDriveExporter(self.config)
        return self._exporter

    def reset_drive(self) -> None:
        """Drop cached Drive/auth state after a transport/auth failure."""
        self._exporter = None
        self._control_folder_id = ""

    def _control_folder(self) -> str:
        if self._control_folder_id:
            return self._control_folder_id
        exporter = self._drive()
        settings = load_backend_settings()
        root = exporter.ensure_folder(settings.supervisor_drive_root, "root")
        instances = exporter.ensure_folder("INSTANCES", root)
        instance_folder = exporter.ensure_folder(self.identity.instance_name, instances)
        self._control_folder_id = exporter.ensure_folder("CONTROL", instance_folder)
        return self._control_folder_id

    def _result(self, request_id: str, command: str, state: str, detail: str = "", **extra: Any) -> None:
        payload: dict[str, Any] = {
            "schema": "ua-free-content-tool-control-result-v1",
            "request_id": request_id,
            "command": command,
            "state": state,
            "detail": str(detail)[:2400],
            "version": self.version,
            "instance_id": self.identity.instance_id,
            "generated_at": _now_iso(),
        }
        payload.update(extra)
        try:
            self._drive().upload_json("result.json", payload, self._control_folder(), replace=True)
            with self._lock:
                self._last_result = f"{command}:{state}"
                self._last_error = ""
        except Exception as exc:
            _atomic_json(_pending_result_path(), payload)
            with self._lock:
                self._last_error = f"result upload: {exc}"
            logger.warning("Remote control result upload failed: %s", exc)

    def flush_pending_result(self, *, raise_transport_errors: bool = False) -> None:
        path = _pending_result_path()
        if not path.is_file():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(payload, dict):
                return
            self._drive().upload_json("result.json", payload, self._control_folder(), replace=True)
            path.unlink(missing_ok=True)
            with self._lock:
                self._last_result = f"{payload.get('command','?')}:{payload.get('state','?')}"
                self._last_error = ""
        except Exception as exc:
            self.reset_drive()
            with self._lock:
                self._last_error = f"pending result upload: {exc}"
            if raise_transport_errors:
                raise

    def _validate(self, raw: dict[str, Any]) -> RemoteCommand:
        if str(raw.get("schema") or "") != "ua-free-content-tool-control-v1":
            raise ValueError("CONTROL_SCHEMA_INVALID")
        request_id = str(raw.get("request_id") or "").strip()
        if not _REQUEST_RE.fullmatch(request_id):
            raise ValueError("CONTROL_REQUEST_ID_INVALID")
        command = str(raw.get("command") or "").strip().casefold()
        if command not in _ALLOWED_COMMANDS:
            raise ValueError("CONTROL_COMMAND_NOT_ALLOWED")
        instance_id = str(raw.get("instance_id") or "").strip()
        if instance_id and instance_id != self.identity.instance_id:
            raise ValueError("CONTROL_INSTANCE_MISMATCH")
        created = _parse_time(str(raw.get("created_at") or ""))
        if created is None:
            raise ValueError("CONTROL_CREATED_AT_REQUIRED")
        now = datetime.now(timezone.utc)
        if created < now - timedelta(hours=24) or created > now + timedelta(minutes=5):
            raise ValueError("CONTROL_REQUEST_STALE")
        expires = _parse_time(str(raw.get("expires_at") or ""))
        if expires is not None and expires < now:
            raise ValueError("CONTROL_REQUEST_EXPIRED")
        target = str(raw.get("target_version") or "").strip()
        if command == "update" and not _VERSION_RE.fullmatch(target):
            raise ValueError("CONTROL_UPDATE_VERSION_INVALID")
        return RemoteCommand(request_id, command, created.isoformat(), target)

    def poll(self) -> RemoteCommand | None:
        """Poll the narrow control file.

        Protocol/validation errors are local data problems and remain ignored.
        Transport/auth errors MUST propagate to the supervisor circuit breaker.
        RC9 swallowed them here, so the outer runtime falsely registered every
        failed 401 poll as a success and hammered Drive indefinitely.
        """
        if self._busy:
            return None
        try:
            self.flush_pending_result(raise_transport_errors=True)
            folder = self._control_folder()
            file_id = self._drive().find_child(folder, "command.json", folder=False)
            if not file_id:
                return None
            raw = self._drive().download_json(file_id)
            command = self._validate(raw)
            if self._processed(command.request_id):
                return None
            with self._lock:
                self._last_command = f"{command.command}:{command.request_id}"
                self._last_error = ""
            return command
        except ValueError as exc:
            with self._lock:
                self._last_error = str(exc)
            logger.warning("Ignored invalid remote control request: %s", exc)
            return None
        except Exception as exc:
            self.reset_drive()
            with self._lock:
                self._last_error = str(exc)
            # Deliberately propagate. ResilientSupervisorRuntime owns retry cadence
            # and auth/transient backoff; hiding the exception here recreates a
            # retry storm and Windows handle growth.
            raise

    def complete_report(self, command: RemoteCommand, *, report_name: str) -> None:
        self._mark_processed(command.request_id)
        self._result(command.request_id, command.command, "DONE", f"report={report_name}")

    def _post_ui(self, callback: Callable[[], None]) -> None:
        poster = getattr(self.window, "_post_ui", None)
        if callable(poster):
            poster(callback)
            return
        root = getattr(self.window, "root", None)
        if root is not None:
            try:
                root.after(0, callback)
            except Exception:
                pass

    def execute_restart(self, command: RemoteCommand) -> None:
        self._mark_processed(command.request_id)
        self._result(command.request_id, command.command, "RESTARTING", "graceful delayed relaunch scheduled")
        try:
            schedule_delayed_restart()
        except Exception as exc:
            self._result(command.request_id, command.command, "FAILED", str(exc))
            return
        self._post_ui(lambda: getattr(self.window, "root").destroy())

    def execute_update(self, command: RemoteCommand) -> None:
        if self._busy:
            return
        self._mark_processed(command.request_id)
        with self._lock:
            self._busy = True
        self._result(command.request_id, command.command, "PREPARING", f"target={command.target_version}")

        def worker() -> None:
            try:
                prepared = prepare_update(
                    command.target_version,
                    current_version=self.version,
                    control_request_id=command.request_id,
                )
                ready, detail = wait_for_preflight(prepared, timeout_seconds=150)
                if not ready:
                    self._result(command.request_id, command.command, "PRECHECK_FAILED", detail)
                    return
                self._result(
                    command.request_id,
                    command.command,
                    "READY_TO_APPLY",
                    detail,
                    transaction_id=prepared.request_id,
                    target_version=prepared.target_version,
                )
                # Detached runner has already downloaded, SHA/signature checked and
                # staged the release. It waits for this exact process to exit,
                # replaces everything except Data, validates startup health and
                # rolls back the old runtime if the new version cannot prove health.
                self._post_ui(lambda: getattr(self.window, "root").destroy())
            except Exception as exc:
                self._result(command.request_id, command.command, "FAILED", str(exc))
                logger.exception("Remote update preparation failed: %s", exc)
            finally:
                with self._lock:
                    self._busy = False

        threading.Thread(target=worker, name="content-v2-remote-update", daemon=True).start()
