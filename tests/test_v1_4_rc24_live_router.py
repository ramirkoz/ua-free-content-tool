from __future__ import annotations

from types import SimpleNamespace

import pytest

from content_agent import ai_router_v1_4_rc24 as router
from content_agent import codex_engine_v1_4_rc24 as codex_engine


class _FakeThread:
    def __init__(self, model: str, calls: list[str], *, fail_model: str = "") -> None:
        self.model = model
        self.calls = calls
        self.fail_model = fail_model

    def run(self, _prompt: str, **kwargs: object):
        assert kwargs.get("model") == self.model
        self.calls.append(self.model)
        if self.model == self.fail_model:
            raise RuntimeError("unexpected status 404 Not Found: The model does not exist")
        return SimpleNamespace(final_response='{"status":"ok"}', error=None)


class _FakeCodex:
    def __init__(self, calls: list[str], *, fail_model: str = "") -> None:
        self.calls = calls
        self.fail_model = fail_model

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def account(self):
        return SimpleNamespace(account=SimpleNamespace(email="user@example.com"))

    def models(self, *, include_hidden: bool = False):
        assert include_hidden is False
        return SimpleNamespace(
            data=[
                SimpleNamespace(model="gpt-retired", is_default=True, display_name="Retired"),
                SimpleNamespace(model="gpt-live", is_default=False, display_name="Live"),
            ]
        )

    def thread_start(self, **kwargs: object):
        model = str(kwargs.get("model") or "")
        assert model, "RC24 must never rely on Codex implicit model defaults"
        return _FakeThread(model, self.calls, fail_model=self.fail_model)


class _FakeSDK:
    Sandbox = SimpleNamespace(read_only="read_only")
    ApprovalMode = SimpleNamespace(deny_all="deny_all")

    def __init__(self, calls: list[str], *, fail_model: str = "") -> None:
        self.calls = calls
        self.fail_model = fail_model

    def Codex(self):
        return _FakeCodex(self.calls, fail_model=self.fail_model)


def test_rc24_codex_uses_live_model_catalog_and_falls_back_from_retired_default(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(codex_engine.legacy, "_load_sdk", lambda: _FakeSDK(calls, fail_model="gpt-retired"))
    monkeypatch.setattr(codex_engine.legacy, "data_dir", lambda: __import__("pathlib").Path("."))

    raw = codex_engine.run_codex("return json")

    assert raw == '{"status":"ok"}'
    assert calls == ["gpt-retired", "gpt-live"]
    assert codex_engine.CODEX_PACKAGE == "openai-codex==0.147.0"


def test_rc24_recovers_different_transient_route_after_fresh_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    candidate = router.AIModelSlot(2, "gemini", "gemini-test", "Gemini test", "gemini")
    result = router.AIResult("OK", "gemini", "gemini-test", "Gemini test", 2, ("Gemini test",))

    def fake_base(*_args: object, **_kwargs: object):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise router.AIRouterError("Усі доступні AI-моделі цього разу відмовили. fresh provider failed")
        return result

    candidates = iter([candidate, None])
    monkeypatch.setattr(router, "_BASE_RUN_AI", fake_base)
    monkeypatch.setattr(router.rc22, "_normalize_persisted_cooldowns", lambda: None)
    monkeypatch.setattr(router, "_clear_obsolete_codex_model_cooldown", lambda: None)
    monkeypatch.setattr(router, "load_provider_secrets", lambda: router.AIProviderSecrets())
    monkeypatch.setattr(router, "_fresh_attempted_models", lambda **_kwargs: set())
    monkeypatch.setattr(router, "_next_safe_recovery_candidate", lambda **_kwargs: next(candidates, None))
    monkeypatch.setattr(router.rc22, "_clear_candidate_cooldown", lambda _slot: None)

    actual = router.run_ai("x", task_timeout_seconds=30)

    assert actual is result
    assert calls == 2


def test_rc24_supplies_default_deadline_when_consumer_omits_it(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    result = router.AIResult("OK", "gemini", "m", "Gemini", 2, ("Gemini",))

    def fake_base(*_args: object, **kwargs: object):
        captured.update(kwargs)
        return result

    monkeypatch.setattr(router, "_BASE_RUN_AI", fake_base)
    monkeypatch.setattr(router.rc22, "_normalize_persisted_cooldowns", lambda: None)
    monkeypatch.setattr(router, "_clear_obsolete_codex_model_cooldown", lambda: None)
    monkeypatch.setattr(router.codex_rc24, "install_runtime", lambda: None)
    monkeypatch.setattr(router, "load_provider_secrets", lambda: router.AIProviderSecrets())
    monkeypatch.setattr(router, "_fresh_attempted_models", lambda **_kwargs: set())

    actual = router.run_ai("x")

    assert actual is result
    assert 1 <= int(captured["task_timeout_seconds"]) <= 80
