from __future__ import annotations

from pathlib import Path

import pytest

from content_agent import ai_router_v1_2_1 as router


def test_provider_secrets_round_trip_is_encrypted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(router, "data_dir", lambda: tmp_path)
    value = router.AIProviderSecrets(
        nvidia_api_key="nv-secret",
        gemini_api_key="gem-secret",
        groq_api_key="groq-secret",
        cloudflare_account_id="acct",
        cloudflare_api_token="cf-secret",
        local_enabled=True,
        local_model="test-model",
    )
    router.save_provider_secrets(value)
    encrypted = (tmp_path / "ai_providers.secure").read_bytes()
    assert b"nv-secret" not in encrypted
    assert b"groq-secret" not in encrypted
    loaded = router.load_provider_secrets()
    assert loaded.nvidia_api_key == "nv-secret"
    assert loaded.gemini_api_key == "gem-secret"
    assert loaded.cloudflare_account_id == "acct"
    assert loaded.local_enabled is True
    assert loaded.local_model == "test-model"


def test_model_quota_falls_to_next_model_before_next_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = router.AIProviderSecrets(nvidia_api_key="x", groq_api_key="y")
    state = router.AIRouterState()
    saved: list[router.AIRouterState] = []
    calls: list[str] = []

    monkeypatch.setattr(router, "load_provider_secrets", lambda: cfg)
    monkeypatch.setattr(router, "load_router_state", lambda: state)
    monkeypatch.setattr(router, "save_router_state", lambda value: saved.append(value))
    monkeypatch.setattr(
        router,
        "_configured",
        lambda slot, _cfg: slot.provider in {"nvidia", "groq"},
    )

    def invoke(slot: router.AIModelSlot, _cfg: router.AIProviderSecrets, _prompt: str) -> str:
        calls.append(slot.label)
        if slot.provider == "nvidia" and len([value for value in calls if "NVIDIA" in value]) == 1:
            raise router.AIModelError("model quota", kind="quota", retry_after=3600)
        if slot.provider == "nvidia":
            return "OK"
        return "GROQ"

    monkeypatch.setattr(router, "_invoke_slot", invoke)
    result = router.run_ai("test")
    assert result.provider == "nvidia"
    assert calls[0] == "DeepSeek V4 Pro / NVIDIA"
    assert any("Nemotron 3 Ultra" in value for value in calls)
    assert not any("Groq" in value for value in calls)
    assert "provider:nvidia" not in state.cooldowns
    assert any(key.startswith("model:nvidia:") for key in state.cooldowns)
    assert saved


def test_invalid_model_output_falls_to_next_model(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = router.AIProviderSecrets(nvidia_api_key="x")
    state = router.AIRouterState()
    calls: list[str] = []

    monkeypatch.setattr(router, "load_provider_secrets", lambda: cfg)
    monkeypatch.setattr(router, "load_router_state", lambda: state)
    monkeypatch.setattr(router, "save_router_state", lambda _value: None)
    monkeypatch.setattr(router, "_configured", lambda slot, _cfg: slot.provider == "nvidia")

    def invoke(slot: router.AIModelSlot, _cfg: router.AIProviderSecrets, _prompt: str) -> str:
        calls.append(slot.label)
        return "BAD" if len(calls) == 1 else "VALID"

    monkeypatch.setattr(router, "_invoke_slot", invoke)

    def validator(text: str) -> None:
        if text != "VALID":
            raise ValueError("schema")

    result = router.run_ai("test", validator=validator)
    assert result.text == "VALID"
    assert len(calls) == 2
    assert calls[0] == "DeepSeek V4 Pro / NVIDIA"
    assert calls[1] == "Nemotron 3 Ultra 550B / NVIDIA"


def test_registry_prioritizes_quality_and_keeps_only_production_providers() -> None:
    labels = [slot.label for slot in router.MODEL_SLOTS]
    assert labels[:6] == [
        "Codex / ChatGPT",
        "Gemini 3.5 Flash / Google",
        "DeepSeek V4 Pro / NVIDIA",
        "Nemotron 3 Ultra 550B / NVIDIA",
        "GLM-5.2 / NVIDIA",
        "Qwen 3.5 397B / NVIDIA",
    ]
    assert {slot.provider for slot in router.MODEL_SLOTS} == {
        "codex",
        "gemini",
        "nvidia",
        "groq",
        "cloudflare",
        "local",
    }
    assert len(router.MODEL_SLOTS) == 13
    assert router.MODEL_SLOTS[-1].provider == "local"
    assert [slot.priority for slot in router.MODEL_SLOTS] == list(range(1, len(router.MODEL_SLOTS) + 1))
