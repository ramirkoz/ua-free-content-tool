from __future__ import annotations

from types import SimpleNamespace

import pytest

from content_agent import ai_router as legacy
from content_agent.v2.ai import direct_router_runtime
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


def test_direct_runtime_installs_current_groq_generation() -> None:
    direct_router_runtime.install_direct_router_runtime()
    models = [slot.model for slot in legacy.MODEL_SLOTS if slot.provider == "groq"]
    assert "qwen/qwen3.8-27b" in models
    assert "qwen/qwen3.6-27b" not in models


def test_patched_groq_call_uses_provider_fallback_transport(monkeypatch) -> None:
    direct_router_runtime.install_direct_router_runtime()
    captured = {}

    def fake_chat(provider: str, **kwargs):
        captured["provider"] = provider
        captured["model"] = kwargs["model"]
        return ProviderReply("OK", "openai/gpt-oss-20b", "fallback")

    monkeypatch.setattr(direct_router_runtime, "openai_compatible_chat", fake_chat)
    slot = next(item for item in legacy.MODEL_SLOTS if item.provider == "groq")
    cfg = SimpleNamespace(
        groq_api_key="key",
        nvidia_api_key="",
        cloudflare_api_token="",
        cloudflare_account_id="",
    )
    assert legacy._openai_call(slot, cfg, "test", max_output_tokens=64, timeout_seconds=5) == "OK"
    assert captured == {"provider": "groq", "model": slot.model}


def test_provider_error_kind_is_preserved_into_legacy_router(monkeypatch) -> None:
    direct_router_runtime.install_direct_router_runtime()

    def fail(*_args, **_kwargs):
        raise ProviderAPIError("HTTP 429: provider rate limit", kind="temporary", status=429, retry_after=2)

    monkeypatch.setattr(direct_router_runtime, "openai_compatible_chat", fail)
    slot = next(item for item in legacy.MODEL_SLOTS if item.provider == "groq")
    cfg = SimpleNamespace(
        groq_api_key="key",
        nvidia_api_key="",
        cloudflare_api_token="",
        cloudflare_account_id="",
    )
    with pytest.raises(legacy.AIModelError) as exc:
        legacy._openai_call(slot, cfg, "test", max_output_tokens=64, timeout_seconds=5)
    assert exc.value.kind == "temporary"
    assert exc.value.retry_after == 2
    assert legacy._classify_cooldown_reason(f"temporary: {exc.value}") == "temporary"
