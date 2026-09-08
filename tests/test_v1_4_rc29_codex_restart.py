from __future__ import annotations

from pathlib import Path

import pytest

from content_agent import restart_helper_v1_4_rc29 as restart


def test_rc29_schedules_restart_of_current_portable_executable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    exe = tmp_path / "UA_FREE_Content_Tool.exe"
    captured: dict[str, object] = {}
    monkeypatch.setattr(restart.sys, "executable", str(exe))

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(restart.subprocess, "Popen", fake_popen)
    restart.schedule_delayed_restart()
    args = captured["args"]
    assert args[:4] == ["cmd.exe", "/d", "/s", "/c"]
    assert str(exe.resolve()) in args[4]
    assert str(tmp_path.resolve()) in args[4]
    assert captured["cwd"] == str(tmp_path.resolve())


def test_rc29_rc28_installer_failure_uses_real_codex_error_type() -> None:
    source = Path(restart.__file__).resolve().parent / "codex_engine_v1_4_rc28.py"
    text = source.read_text(encoding="utf-8")
    assert "CodexEngineEr(" not in text
    assert "CodexEngineError(" in text
