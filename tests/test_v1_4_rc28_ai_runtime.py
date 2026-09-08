from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from content_agent import ai_router_v1_4_rc28 as router
from content_agent import codex_engine_v1_4_rc28 as codex


def test_rc28_codex_gets_realistic_slice(monkeypatch: pytest.MonkeyPatch) -> None:
    slot = router.AIModelSlot(1, "codex", "codex", "Codex / ChatGPT", "codex")
    state = router.legacy.AIRouterState()
    captured: dict[str, object] = {}
    monkeypatch.setattr(router.codex_rc28, "install_runtime", lambda: None)
    monkeypatch.setattr(router.rc25, "_normalize_state", lambda: None)
    monkeypatch.setattr(router, "load_provider_secrets", lambda: router.AIProviderSecrets())
    monkeypatch.setattr(router, "load_router_state", lambda: state)
    monkeypatch.setattr(router, "save_router_state", lambda _state: None)
    monkeypatch.setattr(router, "_available_routes", lambda **_kwargs: [slot])

    def fake_invoke(_slot, *_args, **kwargs):
        captured.update(kwargs)
        return "ok", slot

    monkeypatch.setattr(router.rc25, "_invoke_route", fake_invoke)
    result = router.run_ai("x", task_timeout_seconds=90, cloud_timeout_seconds=120)
    assert result.text == "ok"
    assert int(captured["timeout_seconds"]) == 45


def test_rc28_local_budget_matches_runtime_minimum(monkeypatch: pytest.MonkeyPatch) -> None:
    slot = router.AIModelSlot(9, "local", "local-model", "Local", "local")
    state = router.legacy.AIRouterState()
    captured: dict[str, object] = {}
    monkeypatch.setattr(router.codex_rc28, "install_runtime", lambda: None)
    monkeypatch.setattr(router.rc25, "_normalize_state", lambda: None)
    monkeypatch.setattr(router, "load_provider_secrets", lambda: router.AIProviderSecrets(local_enabled=True))
    monkeypatch.setattr(router, "load_router_state", lambda: state)
    monkeypatch.setattr(router, "save_router_state", lambda _state: None)
    monkeypatch.setattr(router, "_available_routes", lambda **_kwargs: [slot])

    def fake_invoke(_slot, *_args, **kwargs):
        captured.update(kwargs)
        return "local ok", slot

    monkeypatch.setattr(router.rc25, "_invoke_route", fake_invoke)
    result = router.run_ai("x", local_timeout_seconds=12, task_timeout_seconds=90)
    assert result.text == "local ok"
    assert int(captured["timeout_seconds"]) == 30


def test_rc28_local_runs_before_secondary_cloud_models(monkeypatch: pytest.MonkeyPatch) -> None:
    c1 = router.AIModelSlot(1, "codex", "c1", "Codex", "codex")
    n1 = router.AIModelSlot(2, "nvidia", "n1", "NVIDIA 1")
    n2 = router.AIModelSlot(3, "nvidia", "n2", "NVIDIA 2")
    g1 = router.AIModelSlot(4, "groq", "g1", "Groq 1")
    g2 = router.AIModelSlot(5, "groq", "g2", "Groq 2")
    local = router.AIModelSlot(9, "local", "local", "Local", "local")
    monkeypatch.setattr(router.rc25, "_available_routes", lambda **_kwargs: [c1, n1, g1, n2, g2, local])
    ordered = router._available_routes()
    assert [s.model for s in ordered] == ["c1", "n1", "g1", "local", "n2", "g2"]


def test_rc28_codex_install_is_side_by_side(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(codex.legacy, "data_dir", lambda: tmp_path)
    old = tmp_path / "ai_runtime" / "codex"
    old.mkdir(parents=True)
    locked = old / "pydantic_core" / "_pydantic_core.cp312-win_amd64.pyd"
    locked.parent.mkdir()
    locked.write_bytes(b"loaded-binary-placeholder")

    def fake_run(command, **_kwargs):
        target = Path(command[command.index("--target") + 1])
        (target / "openai_codex").mkdir(parents=True)
        (target / "openai_codex-0.147.0.dist-info").mkdir()
        return SimpleNamespace(returncode=0, stdout="installed")

    monkeypatch.setattr(codex.subprocess, "run", fake_run)
    # Simulate a process that already imported Codex: new runtime must wait for restart.
    monkeypatch.setitem(sys.modules, "openai_codex", SimpleNamespace())
    message = codex.install_codex()

    assert locked.read_bytes() == b"loaded-binary-placeholder"
    pointer = json.loads((tmp_path / "ai_runtime" / "codex_active.json").read_text(encoding="utf-8"))
    active = tmp_path / "ai_runtime" / pointer["directory"]
    assert active != old
    assert (active / "openai_codex").is_dir()
    assert "Перезапустіть" in message


def test_rc28_startup_clears_only_transient_rc27_cooldowns(monkeypatch: pytest.MonkeyPatch) -> None:
    state = router.legacy.AIRouterState()
    state.cooldowns = {
        "model:codex:codex": {"until": 9999999999.0, "reason": "temporary: timeout"},
        "provider:groq": {"until": 9999999999.0, "reason": "quota: rate limit"},
        "provider:gemini": {"until": 9999999999.0, "reason": "auth: ключ або доступ відхилено"},
    }
    saved: list[object] = []
    monkeypatch.setattr(router, "_STARTUP_TRANSIENT_RESET_DONE", False)
    monkeypatch.setattr(router, "load_router_state", lambda: state)
    monkeypatch.setattr(router, "save_router_state", lambda value: saved.append(value))

    router._reset_stale_transient_cooldowns_once()

    assert "model:codex:codex" not in state.cooldowns
    assert "provider:groq" in state.cooldowns
    assert "provider:gemini" in state.cooldowns
    assert saved == [state]
