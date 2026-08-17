from __future__ import annotations

import json

import pytest

from content_agent import ai_router_v1_2_1 as legacy
from content_agent import ai_router_v1_2_2 as router


def test_request_too_large_does_not_cool_healthy_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = legacy.AIProviderSecrets(nvidia_api_key="x", groq_api_key="y")
    state = legacy.AIRouterState()
    calls: list[str] = []

    monkeypatch.setattr(legacy, "load_provider_secrets", lambda: cfg)
    monkeypatch.setattr(legacy, "load_router_state", lambda: state)
    monkeypatch.setattr(legacy, "save_router_state", lambda _value: None)
    monkeypatch.setattr(legacy, "_configured", lambda slot, _cfg: slot.provider in {"nvidia", "groq"})

    def invoke(slot, _cfg, _prompt, _max_output_tokens):
        calls.append(slot.provider)
        if slot.provider == "nvidia":
            raise legacy.AIModelError("too big", kind="request_too_large")
        return "OK"

    monkeypatch.setattr(router, "_invoke_limited", invoke)
    result = router.run_ai("small task", max_output_tokens=900)
    assert result.provider == "groq"
    assert "provider:nvidia" not in state.cooldowns
    assert not any(key.startswith("model:nvidia:") for key in state.cooldowns)
    assert calls[0] == "nvidia"


def test_openai_limited_accepts_problem_json_and_classifies_413(monkeypatch: pytest.MonkeyPatch) -> None:
    slot = legacy.AIModelSlot(1, "groq", "openai/gpt-oss-120b", "Groq")
    cfg = legacy.AIProviderSecrets(groq_api_key="x")
    seen = {}

    class Response:
        status = 413
        headers = {}
        body = b'{"error":{"message":"Request too large"}}'

    def fake_fetch(url, **kwargs):
        seen.update(kwargs)
        return Response()

    monkeypatch.setattr(router, "fetch_url", fake_fetch)
    with pytest.raises(legacy.AIModelError) as error:
        router._openai_call_limited(slot, cfg, "x", max_output_tokens=900)
    assert error.value.kind == "request_too_large"
    assert "application/problem+json" in seen["allowed_content_types"]
    payload = json.loads(seen["body"].decode("utf-8"))
    assert payload["max_tokens"] == 900
