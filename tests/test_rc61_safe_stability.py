"""RC61 focused stability regressions, without changes to accepted RC60 media behavior."""
from __future__ import annotations

import pytest

from content_agent import ai_router as legacy
from content_agent.network import NetworkError
from content_agent.v2.ai import openrouter_backend as backend_module
from content_agent.v2.ai import provider_api
from content_agent.v2.ai.contracts import AITask, QualityTier
from content_agent.v2.ai.openrouter_backend import ModelInfo, OpenRouterBackend, OpenRouterError
from content_agent.v2.ai.service import _backend_for
from content_agent.v2.ai.settings import AIBackendSettings


def _text_model(model_id: str, price: float = 0.0000001) -> ModelInfo:
    return ModelInfo(
        id=model_id,
        name=model_id,
        prompt_price=price,
        completion_price=price,
        context_length=32768,
        quality=1,
        free=False,
    )


def test_rc61_cloudflare_retired_slot_is_replaced_without_changing_other_providers() -> None:
    slots = tuple(legacy.MODEL_SLOTS)
    assert len(slots) == 9
    assert len([slot for slot in slots if slot.provider == "cloudflare"]) == 2
    assert any(
        slot.provider == "cloudflare"
        and slot.model == "@cf/google/gemma-4-26b-a4b-it"
        for slot in slots
    )
    assert any(
        slot.provider == "cloudflare"
        and slot.model == "@cf/zai-org/glm-4.7-flash"
        for slot in slots
    )
    assert not any(
        slot.provider == "cloudflare"
        and slot.model == "@cf/nvidia/nemotron-3-120b-a12b"
        for slot in slots
    )
    assert any(
        slot.provider == "nvidia"
        and slot.model == "nvidia/nemotron-3-ultra-550b-a55b"
        for slot in slots
    )


def test_rc61_cloudflare_gemma_uses_existing_openai_compatible_transport(monkeypatch) -> None:
    observed = {}

    def fake_request(url, **kwargs):
        observed["url"] = url
        observed["body"] = kwargs["payload"]
        return 200, {}, {
            "model": "@cf/google/gemma-4-26b-a4b-it",
            "choices": [{"message": {"content": "Український текст."}}],
        }

    monkeypatch.setattr(provider_api, "_request_json", fake_request)
    result = provider_api.openai_compatible_chat(
        "cloudflare",
        model="@cf/google/gemma-4-26b-a4b-it",
        account_id="account-id",
        api_key="test-token",
        prompt="Напиши українською.",
        max_output_tokens=256,
        timeout_seconds=20,
    )
    assert observed["url"].endswith("/accounts/account-id/ai/v1/chat/completions")
    assert observed["body"]["model"] == "@cf/google/gemma-4-26b-a4b-it"
    assert observed["body"]["max_completion_tokens"] == 256
    assert result.text == "Український текст."


def test_rc61_cached_specialized_models_never_selected_for_generic_chat() -> None:
    # RC60 could already have cached these specialized endpoints on disk.
    cached = (
        _text_model("scaledown/extract", 0.000000001),
        _text_model("scaledown/summarize", 0.000000002),
        _text_model("mistralai/mistral-nemo", 0.0000001),
    )
    selected = backend_module._candidate_models(
        cached,
        QualityTier.FAST_CHEAP,
        prompt_chars=100,
        max_output_tokens=128,
        strategy="balanced",
        task=AITask.SUPERVISOR,
    )
    assert [row.id for row in selected] == ["mistralai/mistral-nemo"]


def _prepare_backend(monkeypatch) -> OpenRouterBackend:
    backend = OpenRouterBackend(AIBackendSettings(active_backend="openrouter"))
    monkeypatch.setattr(backend, "configured", lambda: True)
    monkeypatch.setattr(backend, "_ensure_budget", lambda: None)
    monkeypatch.setattr(backend_module, "model_catalog", lambda: (
        _text_model("one/model"), _text_model("two/model")
    ))
    monkeypatch.setattr(backend_module, "_quarantined_model_ids", lambda: set())
    monkeypatch.setattr(backend_module, "_record_event", lambda **_kwargs: None)
    monkeypatch.setattr(backend_module, "_clear_model_quarantine", lambda _model: None)
    monkeypatch.setattr(backend_module, "record_usage", lambda _usage: None)
    return backend


def test_rc61_openrouter_dns_outage_does_not_retry_same_hostname_with_other_models(monkeypatch) -> None:
    backend = _prepare_backend(monkeypatch)
    attempts = []

    def fail_dns(_prompt, model, **_kwargs):
        attempts.append(model.id)
        raise NetworkError("DNS resolution failed for openrouter.ai.")

    monkeypatch.setattr(backend, "_call", fail_dns)
    with pytest.raises(OpenRouterError) as failure:
        backend.run("Supervisor status.", task=AITask.SUPERVISOR, max_output_tokens=96)
    assert failure.value.kind == "network"
    assert attempts == ["one/model"]


def test_rc61_other_transient_network_failures_still_use_model_fallback(monkeypatch) -> None:
    backend = _prepare_backend(monkeypatch)
    attempts = []

    def intermittent(_prompt, model, **_kwargs):
        attempts.append(model.id)
        if model.id == "one/model":
            raise NetworkError("Network request failed: https://openrouter.ai/api/v1/chat/completions")
        payload = {
            "usage": {"prompt_tokens": 10, "completion_tokens": 1, "cost": 0.00001},
            "choices": [{"finish_reason": "stop", "message": {"content": "OK"}}],
        }
        return "OK", model.id, payload, model

    monkeypatch.setattr(backend, "_call", intermittent)
    result = backend.run("Supervisor status.", task=AITask.SUPERVISOR, max_output_tokens=96)
    assert result.text == "OK"
    assert attempts == ["one/model", "two/model"]


def test_rc61_openrouter_mode_remains_exclusive_in_content_tool() -> None:
    settings = AIBackendSettings(active_backend="openrouter")
    assert _backend_for("openrouter", settings).name == "openrouter"
    assert _backend_for("router", settings).name == "router"
