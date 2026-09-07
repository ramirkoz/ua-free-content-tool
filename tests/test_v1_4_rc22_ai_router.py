from __future__ import annotations

import sys
import types

from content_agent import ai_router_v1_4_rc22 as router


def test_rc22_cooldown_caps_are_bounded() -> None:
    assert router._cooldown_seconds_rc22(router.AIModelError("quota", kind="quota")) == 600
    assert router._cooldown_seconds_rc22(router.AIModelError("auth", kind="auth")) == 1800
    assert router._cooldown_seconds_rc22(router.AIModelError("model", kind="model")) == 300
    assert router._cooldown_seconds_rc22(router.AIModelError("bad", kind="bad_response")) == 60
    assert router._cooldown_seconds_rc22(router.AIModelError("temp", kind="temporary")) == 90
    assert router._cooldown_seconds_rc22(router.AIModelError("quota", kind="quota", retry_after=45)) == 45


def test_rc22_classifies_persisted_reasons() -> None:
    assert router._classify_cooldown_reason("HTTP 401 ключ або доступ відхилено") == "auth"
    assert router._classify_cooldown_reason("HTTP 429 досягнуто ліміт") == "quota"
    assert router._classify_cooldown_reason("HTTP 404 model not found") == "model"
    assert router._classify_cooldown_reason("validation: bad json") == "validation"
    assert router._classify_cooldown_reason("timeout") == "temporary"


def test_rc22_retries_one_cooled_provider_instead_of_false_no_provider(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    candidate = router.AIModelSlot(2, "gemini", "gemini-test", "Gemini test", "gemini")
    result = router.AIResult("OK", "gemini", "gemini-test", "Gemini test", 2, ("Gemini test",))

    def fake_base(prompt: str, **kwargs: object):
        calls.append(dict(kwargs))
        if len(calls) == 1:
            raise router.AIRouterError("Немає доступного AI-провайдера.")
        return result

    candidates = iter([candidate])
    monkeypatch.setattr(router, "_BASE_RUN_AI", fake_base)
    monkeypatch.setattr(router, "_normalize_persisted_cooldowns", lambda: None)
    monkeypatch.setattr(router, "_next_recovery_candidate", lambda **_kwargs: next(candidates, None))
    monkeypatch.setattr(router, "_clear_candidate_cooldown", lambda _slot: None)

    actual = router.run_ai("test", max_output_tokens=4096)

    assert actual is result
    assert len(calls) == 2
    assert calls[0]["max_output_tokens"] == 4095


def test_rc22_runtime_patches_consumers_but_not_core_routers() -> None:
    dummy = types.ModuleType("content_agent._rc22_dummy_consumer")
    dummy.run_ai = router._BASE_RUN_AI
    dummy.test_ai_router = router._LEGACY_TEST_AI_ROUTER
    sys.modules[dummy.__name__] = dummy
    try:
        router.install_runtime()
        assert dummy.run_ai is router.run_ai
        assert dummy.test_ai_router is router.test_ai_router
        assert router.legacy.run_ai is router._LEGACY_RUN_AI
        assert router.base.run_ai is router._BASE_RUN_AI
    finally:
        sys.modules.pop(dummy.__name__, None)
