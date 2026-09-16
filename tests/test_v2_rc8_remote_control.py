from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from content_agent.v2.supervisor.control import RemoteControlManager
from content_agent.v2.supervisor.updater import _rc_number, _runner_script


class DummyWindow:
    root = None


def command_payload(manager: RemoteControlManager, command: str, **extra):
    payload = {
        "schema": "ua-free-content-tool-control-v1",
        "request_id": "request-12345678",
        "instance_id": manager.identity.instance_id,
        "command": command,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
    }
    payload.update(extra)
    return payload


def test_control_protocol_allows_only_fixed_commands(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("UA_FREE_CONTENT_DATA", str(tmp_path))
    from content_agent.paths import reset_path_cache_for_tests
    reset_path_cache_for_tests()
    manager = RemoteControlManager(DummyWindow(), SimpleNamespace(), version="2.0.0-rc8")
    for command in ("report", "restart"):
        parsed = manager._validate(command_payload(manager, command))
        assert parsed.command == command
    parsed = manager._validate(command_payload(manager, "update", target_version="2.0.0-rc9"))
    assert parsed.target_version == "2.0.0-rc9"
    with pytest.raises(ValueError, match="CONTROL_COMMAND_NOT_ALLOWED"):
        manager._validate(command_payload(manager, "shell", command_line="calc.exe"))
    reset_path_cache_for_tests()


def test_control_rejects_stale_and_wrong_instance(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("UA_FREE_CONTENT_DATA", str(tmp_path))
    from content_agent.paths import reset_path_cache_for_tests
    reset_path_cache_for_tests()
    manager = RemoteControlManager(DummyWindow(), SimpleNamespace(), version="2.0.0-rc8")
    stale = command_payload(manager, "report")
    stale["created_at"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    with pytest.raises(ValueError, match="CONTROL_REQUEST_STALE"):
        manager._validate(stale)
    wrong = command_payload(manager, "restart")
    wrong["instance_id"] = "another-instance"
    with pytest.raises(ValueError, match="CONTROL_INSTANCE_MISMATCH"):
        manager._validate(wrong)
    reset_path_cache_for_tests()


def test_update_runner_preserves_data_and_has_rollback() -> None:
    script = _runner_script()
    assert 'Where-Object { $_.Name -ne "Data" }' in script
    assert 'Write-Pending "ROLLBACK_OK"' in script
    assert 'UPDATE_SHA256_MISMATCH' in script
    assert 'startup_healthy.json' in script
    assert "Invoke-Expression" not in script


def test_rc_version_ordering() -> None:
    assert _rc_number("2.0.0-rc8") == 8
    assert _rc_number("2.0.0-rc10") > _rc_number("2.0.0-rc9")
    assert _rc_number("2.1.0") == -1
