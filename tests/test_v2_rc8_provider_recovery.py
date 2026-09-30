from __future__ import annotations

from types import SimpleNamespace

import pytest

from content_agent import ai_router as legacy
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
    gemini = _gemini_candidates("gemini-2.5-flash-lite")
    assert gemini[0] == "gemini-2.5-flash-lite"
    assert len(gemini) == len(set(gemini))


def test_canonical_router_owns_current_provider_models_without_runtime_patch() -> None:
    groq_models = [slot.model for slot in legacy.MODEL_SLOTS if slot.provider == "groq"]
    assert "openai/gpt-oss-120b" in groq_models
    assert "qwen/qwen3-32b" in groq_models
    assert "qwen/qwen3.6-27b" not in groq_models
    assert "qwen/qwen3.8-27b" not in groq_models


def test_canonical_groq_call_uses_provider_fallback_transport(monkeypatch) -> None:
    captured = {}

    def fake_chat(provider: str, **kwargs):
        captured["provider"] = provider
        captured["model"] = kwargs["model"]
        return ProviderReply("OK", "openai/gpt-oss-20b", "fallback")

    monkeypatch.setattr(legacy, "openai_compatible_chat", fake_chat)
    slot = next(item for item in legacy.MODEL_SLOTS if item.provider == "groq")
    cfg = SimpleNamespace(
        groq_api_key="key",
        nvidia_api_key="",
        cloudflare_api_token="",
        cloudflare_account_id="",
    )
    assert legacy._openai_call(slot, cfg, "test", max_output_tokens=64, timeout_seconds=5) == "OK"
    assert captured == {"provider": "groq", "model": slot.model}


def test_provider_error_kind_is_preserved_into_canonical_router(monkeypatch) -> None:
    def fail(*_args, **_kwargs):
        raise ProviderAPIError("HTTP 429: provider rate limit", kind="temporary", status=429, retry_after=2)

    monkeypatch.setattr(legacy, "openai_compatible_chat", fail)
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
