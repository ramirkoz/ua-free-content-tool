from __future__ import annotations

import threading
import sys
import types

import pytest

from content_agent import ai_router_v1_4_rc23 as router


def test_rc23_does_not_recover_after_fresh_provider_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def fake_base(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise router.AIRouterError("Усі доступні AI-моделі цього разу відмовили. provider failed")

    monkeypatch.setattr(router, "_BASE_RUN_AI", fake_base)
    monkeypatch.setattr(router.rc22, "_normalize_persisted_cooldowns", lambda: None)
    monkeypatch.setattr(router.rc22, "_diagnostic_error", lambda exc: router.AIRouterError("diag: " + str(exc)))

    with pytest.raises(router.AIRouterError, match="diag"):
        router.run_ai("x", task_timeout_seconds=30)
    assert calls == 1


def test_rc23_recovery_uses_remaining_budget_not_original_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int | None] = []
    slot = router.AIModelSlot(1, "gemini", "m", "Gemini", "gemini")
    result = router.AIResult("OK", "gemini", "m", "Gemini", 1, ("Gemini",))

    def fake_base(*_args, **kwargs):
        calls.append(kwargs.get("task_timeout_seconds"))
        if len(calls) == 1:
            raise router.AIRouterError("Немає доступного AI-провайдера.")
        return result

    monkeypatch.setattr(router, "_BASE_RUN_AI", fake_base)
    monkeypatch.setattr(router.rc22, "_normalize_persisted_cooldowns", lambda: None)
    monkeypatch.setattr(router.rc22, "_next_recovery_candidate", lambda **_kwargs: slot)
    monkeypatch.setattr(router.rc22, "_clear_candidate_cooldown", lambda _slot: None)

    actual = router.run_ai("x", task_timeout_seconds=30)
    assert actual is result
    assert len(calls) == 2
    assert calls[0] is not None and calls[0] <= 30
    assert calls[1] is not None and calls[1] <= calls[0]


def test_rc23_cancellation_blocks_recovery(monkeypatch: pytest.MonkeyPatch) -> None:
    cancel = threading.Event()
    cancel.set()
    calls = 0

    def fake_base(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("base router must not run after cancellation")

    monkeypatch.setattr(router, "_BASE_RUN_AI", fake_base)
    monkeypatch.setattr(router.rc22, "_normalize_persisted_cooldowns", lambda: None)

    with pytest.raises(router.AIRouterError, match="скасовано"):
        router.run_ai("x", task_timeout_seconds=30, cancel_event=cancel)
    assert calls == 0


def test_rc23_runtime_patches_consumers_without_mutating_core_routers() -> None:
    dummy = types.ModuleType("content_agent._rc23_dummy_consumer")
    dummy.run_ai = router._BASE_RUN_AI
    dummy.test_ai_router = router._LEGACY_TEST_AI_ROUTER
    sys.modules[dummy.__name__] = dummy
    try:
        router.install_runtime()
        assert dummy.run_ai is router.run_ai
        assert dummy.test_ai_router is router.test_ai_router
        assert router.base.run_ai is router._BASE_RUN_AI
        assert router.legacy.run_ai is router._LEGACY_RUN_AI
        assert router.rc22.run_ai is router._RC22_RUN_AI
    finally:
        sys.modules.pop(dummy.__name__, None)
