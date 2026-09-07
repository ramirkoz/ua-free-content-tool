from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from content_agent import ai_router_v1_4_rc25 as router


class _Response:
    def __init__(self, payload: object, *, status: int = 200, headers: dict[str, str] | None = None) -> None:
        self.status = status
        self.headers = headers or {}
        self.body = json.dumps(payload).encode("utf-8")

    def json(self) -> object:
        return json.loads(self.body.decode("utf-8"))


def test_rc25_accepts_valid_json_without_content_type(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"choices": [{"message": {"content": "готовий текст"}}]}
    captured: dict[str, object] = {}

    def fake_fetch(_url: str, **kwargs: object) -> _Response:
        captured.update(kwargs)
        return _Response(payload, headers={})

    monkeypatch.setattr(router, "fetch_url", fake_fetch)
    slot = router.AIModelSlot(4, "nvidia", "nvidia/test", "NVIDIA test")
    cfg = router.AIProviderSecrets(nvidia_api_key="secret")

    text = router._openai_call_resilient(slot, cfg, "rewrite", max_output_tokens=300, timeout_seconds=8)

    assert text == "готовий текст"
    assert captured["allowed_content_types"] is None


def test_rc25_health_plan_prefers_recent_success_and_preserves_provider_diversity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = router.legacy.AIRouterState()
    cfg = router.AIProviderSecrets(
        gemini_api_key="g",
        nvidia_api_key="n",
        groq_api_key="q",
        cloudflare_account_id="a",
        cloudflare_api_token="t",
        local_enabled=True,
        local_model="local-model",
    )
    nvidia_secondary = next(
        slot for slot in router.legacy.MODEL_SLOTS
        if slot.provider == "nvidia" and "super" in slot.model
    )
    state.model_health[router.legacy._slot_key(nvidia_secondary)] = {
        "outcome": "ok",
        "last_attempt_at": router.time.time(),
        "last_success_at": router.time.time(),
        "elapsed": 1.0,
    }

    monkeypatch.setattr(router, "_configured", lambda _slot, _cfg: True)
    monkeypatch.setattr(router.rc22, "_active_cooldown_for_slot", lambda *_args, **_kwargs: None)

    routes = router._available_routes(
        cfg=cfg,
        state=state,
        skip_providers=set(),
        skip_models=set(),
    )

    assert routes[0].provider == "nvidia"
    assert routes[0].model == nvidia_secondary.model
    first_nvidia = next(i for i, slot in enumerate(routes) if slot.provider == "nvidia")
    second_nvidia = next(i for i, slot in enumerate(routes[first_nvidia + 1 :], first_nvidia + 1) if slot.provider == "nvidia")
    first_other_providers = {slot.provider for slot in routes[first_nvidia + 1 : second_nvidia]}
    assert {"codex", "gemini", "groq", "cloudflare"}.issubset(first_other_providers)
    assert routes[-1].provider == "local"


def test_rc25_quota_blocks_second_model_of_same_provider_in_same_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    groq1 = router.AIModelSlot(5, "groq", "g1", "Groq one")
    groq2 = router.AIModelSlot(6, "groq", "g2", "Groq two")
    nvidia = router.AIModelSlot(3, "nvidia", "n1", "NVIDIA one")
    state = router.legacy.AIRouterState()
    calls: list[str] = []

    monkeypatch.setattr(router.codex_rc24, "install_runtime", lambda: None)
    monkeypatch.setattr(router, "_normalize_state", lambda: None)
    monkeypatch.setattr(router, "load_provider_secrets", lambda: router.AIProviderSecrets())
    monkeypatch.setattr(router, "load_router_state", lambda: state)
    monkeypatch.setattr(router, "save_router_state", lambda _state: None)
    monkeypatch.setattr(router, "_available_routes", lambda **_kwargs: [groq1, groq2, nvidia])

    def fake_invoke(slot: router.AIModelSlot, *_args: object, **_kwargs: object):
        calls.append(slot.model)
        if slot.provider == "groq":
            raise router.AIModelError("rate limit", kind="quota", retry_after=60)
        return "успішний рерайт", slot

    monkeypatch.setattr(router, "_invoke_route", fake_invoke)

    result = router.run_ai("source", task_timeout_seconds=30)

    assert result.text == "успішний рерайт"
    assert calls == ["g1", "n1"]
    assert router.legacy._provider_key("groq") in state.cooldowns


def test_rc25_caps_local_emergency_slice(monkeypatch: pytest.MonkeyPatch) -> None:
    local = router.AIModelSlot(9, "local", "local-model", "Local", "local")
    state = router.legacy.AIRouterState()
    captured: dict[str, object] = {}

    monkeypatch.setattr(router.codex_rc24, "install_runtime", lambda: None)
    monkeypatch.setattr(router, "_normalize_state", lambda: None)
    monkeypatch.setattr(router, "load_provider_secrets", lambda: router.AIProviderSecrets(local_enabled=True))
    monkeypatch.setattr(router, "load_router_state", lambda: state)
    monkeypatch.setattr(router, "save_router_state", lambda _state: None)
    monkeypatch.setattr(router, "_available_routes", lambda **_kwargs: [local])

    def fake_invoke(slot: router.AIModelSlot, *_args: object, **kwargs: object):
        captured.update(kwargs)
        return "локальний результат", slot

    monkeypatch.setattr(router, "_invoke_route", fake_invoke)

    result = router.run_ai("source", local_timeout_seconds=120, task_timeout_seconds=30)

    assert result.text == "локальний результат"
    assert int(captured["timeout_seconds"]) <= 12
