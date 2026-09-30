from __future__ import annotations

from types import SimpleNamespace

import pytest

from content_agent import ai_router as legacy
from content_agent.v2.ai import router_backend
from content_agent.v2.ai.provider_api import (
    ProviderAPIError,
    ProviderReply,
    _classify_http,
    _gemini_candidates,
    _groq_candidates,
)


def test_bare_429_is_transient_rate_limit_not_hard_quota() -> None:
    exc = _classify_http(429, '{"error":{"message":"rate limit exceeded"}}', {})
    assert exc.kind == "temporary"
    assert exc.status == 429


def test_explicit_daily_quota_is_hard_quota() -> None:
    exc = _classify_http(429, '{"error":{"message":"requests per day quota exceeded"}}', {})
    assert exc.kind == "quota"


def test_reviewed_provider_fallbacks_are_present() -> None:
    assert _groq_candidates("openai/gpt-oss-120b") == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
    gemini = _gemini_candidates("gemini-3.5-flash")
    assert gemini[0] == "gemini-3.5-flash"
    assert "gemini-3.5-flash-lite" in gemini
    assert "gemini-3.1-flash-lite" in gemini


def test_canonical_router_uses_current_groq_generation_without_mutating_legacy() -> None:
    backend = router_backend.CanonicalRouterBackend()
    old = next(slot for slot in legacy.MODEL_SLOTS if slot.provider == "groq" and "qwen" in slot.model)
    reviewed = backend._reviewed_slot(old)
    assert reviewed.model == "qwen/qwen3.8-27b"
    assert old.model == "qwen/qwen3.6-27b"


def test_canonical_groq_call_uses_provider_fallback_transport(monkeypatch) -> None:
    captured = {}

    def fake_chat(provider: str, **kwargs):
        captured["provider"] = provider
        captured["model"] = kwargs["model"]
        return ProviderReply("OK", "openai/gpt-oss-20b", "fallback")

    monkeypatch.setattr(router_backend, "openai_compatible_chat", fake_chat)
    slot = next(item for item in legacy.MODEL_SLOTS if item.provider == "groq")
    cfg = SimpleNamespace(
        groq_api_key="key",
        nvidia_api_key="",
        cloudflare_api_token="",
        cloudflare_account_id="",
    )
    output, runtime_slot = router_backend.CanonicalRouterBackend()._invoke_cloud(
        slot,
        cfg,
        "test",
        max_output_tokens=64,
        timeout_seconds=5,
    )
    assert output == "OK"
    assert runtime_slot.model == "openai/gpt-oss-20b"
    assert captured == {"provider": "groq", "model": slot.model}


def test_provider_error_kind_is_preserved_into_canonical_router(monkeypatch) -> None:
    def fail(*_args, **_kwargs):
        raise ProviderAPIError("HTTP 429: provider rate limit", kind="temporary", status=429, retry_after=2)

    monkeypatch.setattr(router_backend, "openai_compatible_chat", fail)
    slot = next(item for item in legacy.MODEL_SLOTS if item.provider == "groq")
    cfg = SimpleNamespace(
        groq_api_key="key",
        nvidia_api_key="",
        cloudflare_api_token="",
        cloudflare_account_id="",
    )
    with pytest.raises(legacy.AIModelError) as exc:
        router_backend.CanonicalRouterBackend()._invoke_cloud(
            slot,
            cfg,
            "test",
            max_output_tokens=64,
            timeout_seconds=5,
        )
    assert exc.value.kind == "temporary"
    assert exc.value.retry_after == 2
