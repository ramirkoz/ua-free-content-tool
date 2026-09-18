from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from content_agent.v2.supervisor import diagnostics
from content_agent.v2.supervisor.diagnostics import detect_incidents


def _base_status() -> dict:
    return {
        "database": {"ok": True},
        "runtime": {
            "background_started": True,
            "worker_alive": True,
            "operation_running": False,
            "operation_age_seconds": 0,
            "ui_lag_seconds": 0,
        },
        "system": {
            "process_handle_count": 6546,
            "disk_free_bytes": 10_000_000_000,
            "dns_resolver": {"queued": 0},
        },
        "supervisor": {
            "handles": {
                "baseline": 6006,
                "current": 6546,
                "growth_since_supervisor_start": 540,
                "estimated_rate_per_hour": 1200.0,
            },
            "drive_runtime": {
                "auth_required": False,
                "failures": 0,
            },
        },
        "content": {"enabled_sources": 149, "source_errors_active": 0},
        "publishing": {
            "failed_targets_15m": 0,
            "failed_targets_60m": 0,
            "failed_targets_24h": 19,
            "last_failed_target_at": "2026-09-18T12:00:00+00:00",
        },
        "ai": {"active_backend": "openrouter", "openrouter_configured": True, "openrouter_recent_events": []},
        "logs": {"top_repeated": []},
    }


def _codes(status: dict) -> set[str]:
    return {str(item.get("code")) for item in detect_incidents(status)}


def test_rc10_does_not_treat_6500_process_handles_as_pressure() -> None:
    status = _base_status()
    assert "PROCESS_HANDLE_PRESSURE" not in _codes(status)


def test_rc10_warns_only_when_handles_are_high_and_growing() -> None:
    status = _base_status()
    status["system"]["process_handle_count"] = diagnostics.PROCESS_HANDLE_SOFT_LIMIT + 500
    status["supervisor"]["handles"].update({
        "current": diagnostics.PROCESS_HANDLE_SOFT_LIMIT + 500,
        "growth_since_supervisor_start": diagnostics.PROCESS_HANDLE_GROWTH_LIMIT + 50,
    })
    incidents = detect_incidents(status)
    row = next(item for item in incidents if item["code"] == "PROCESS_HANDLE_PRESSURE")
    assert row["severity"] == "WARNING"
    assert "Content Tool process" in row["detail"]


def test_rc10_historical_24h_publish_failures_are_not_active_incident() -> None:
    status = _base_status()
    assert status["publishing"]["failed_targets_24h"] == 19
    assert "PUBLISH_FAILURES_ACTIVE" not in _codes(status)


def test_rc10_recent_publish_failure_wave_is_active_incident() -> None:
    status = _base_status()
    status["publishing"].update({"failed_targets_15m": 3, "failed_targets_60m": 5})
    incidents = detect_incidents(status)
    row = next(item for item in incidents if item["code"] == "PUBLISH_FAILURES_ACTIVE")
    assert "3 in 15m" in row["detail"]
    assert "5 in 60m" in row["detail"]


def test_rc10_drive_auth_failure_has_explicit_reauth_incident() -> None:
    status = _base_status()
    status["supervisor"]["drive_runtime"].update({
        "auth_required": True,
        "failures": 2,
        "last_failure": "remote control poll: Google Drive API HTTP 401",
    })
    incidents = detect_incidents(status)
    row = next(item for item in incidents if item["code"] == "DRIVE_REAUTH_REQUIRED")
    assert "Reconnect Google Drive" in row["detail"]
    assert "AI/provider" in row["detail"]


def test_rc10_finished_operation_age_is_zero(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    class Database:
        def quick_check(self):
            return None

        def list_sources(self, enabled_only=False):
            return []

        def count_today_articles(self):
            return 0

        def connect(self):
            raise RuntimeError("test database has no SQL tables")

    class Value:
        def get(self):
            return "Поточна операція: завершено"

    class Window:
        _ui_last_pulse = 0.0
        background_services_started = False
        auto_collect_running = False
        operation_running = False
        operation_started_at = datetime.now().astimezone() - timedelta(hours=2)
        operation_var = Value()
        worker_thread = None

    db_file = tmp_path / "content_agent.sqlite3"
    db_file.write_bytes(b"x")
    monkeypatch.setattr(diagnostics, "database_path", lambda: db_file)
    monkeypatch.setattr(diagnostics, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(diagnostics, "source_health_map", lambda database: {})
    monkeypatch.setattr(diagnostics, "backend_status", lambda: {})
    monkeypatch.setattr(diagnostics, "dns_resolver_stats", lambda: {"queued": 0, "workers": 4})
    monkeypatch.setattr(
        diagnostics,
        "load_backend_settings",
        lambda: type("Settings", (), {"supervisor_enabled": True, "supervisor_drive_root": "CONTENT_TOOL_SUPERVISOR"})(),
    )
    monkeypatch.setattr(diagnostics, "_windows_process_handle_count", lambda: 100)
    monkeypatch.setattr(diagnostics, "_windows_stdio_limit", lambda: 512)
    monkeypatch.setattr(diagnostics.time, "monotonic", lambda: 100.0)
    Window._ui_last_pulse = 100.0

    status = diagnostics.collect_status(Window(), Database(), version="2.0.0-rc10")
    assert status["runtime"]["operation_running"] is False
    assert status["runtime"]["operation_age_seconds"] == 0.0
    assert status["runtime"]["operation"] == ""
