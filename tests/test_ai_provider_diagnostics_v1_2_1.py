from __future__ import annotations

import inspect

import pytest

from content_agent import ai_provider_diagnostics_v1_2_1 as diagnostics
from content_agent import ai_router_v1_2_1 as router
from content_agent.ui.v1_2_rc10_window import MainWindow


def test_provider_diagnostics_checks_each_configured_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = router.AIProviderSecrets(
        gemini_api_key="gem",
        nvidia_api_key="nv",
        groq_api_key="groq",
    )
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(diagnostics, "load_provider_secrets", lambda: cfg)
    monkeypatch.setattr(
        diagnostics,
        "_configured",
        lambda slot, _cfg: slot.provider in {"gemini", "nvidia", "groq"},
    )

    nvidia_models = [slot.model for slot in router.MODEL_SLOTS if slot.provider == "nvidia"]

    def invoke(slot: router.AIModelSlot, _cfg: router.AIProviderSecrets, _prompt: str) -> str:
        calls.append((slot.provider, slot.model))
        if slot.provider == "nvidia" and slot.model == nvidia_models[0]:
            raise router.AIModelError("first model unavailable", kind="model")
        if slot.provider == "groq":
            raise router.AIModelError("bad key", kind="auth")
        return "UA_FREE_PROVIDER_OK"

    monkeypatch.setattr(diagnostics, "_invoke_slot", invoke)
    rows = diagnostics.test_configured_providers()
    by_provider = {row.provider: row for row in rows}

    assert sum(provider == "gemini" for provider, _model in calls) == 1
    assert sum(provider == "nvidia" for provider, _model in calls) == 2
    assert sum(provider == "groq" for provider, _model in calls) == 1
    assert by_provider["gemini"].status == "ok"
    assert by_provider["nvidia"].status == "ok"
    assert by_provider["nvidia"].model == nvidia_models[1]
    assert by_provider["groq"].status == "error"


def test_provider_quota_stops_without_hammering_other_models(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = router.AIProviderSecrets(nvidia_api_key="nv")
    calls: list[str] = []
    monkeypatch.setattr(diagnostics, "load_provider_secrets", lambda: cfg)
    monkeypatch.setattr(diagnostics, "_configured", lambda slot, _cfg: slot.provider == "nvidia")

    def invoke(slot: router.AIModelSlot, _cfg: router.AIProviderSecrets, _prompt: str) -> str:
        calls.append(slot.model)
        raise router.AIModelError("quota", kind="quota")

    monkeypatch.setattr(diagnostics, "_invoke_slot", invoke)
    rows = diagnostics.test_configured_providers()
    by_provider = {row.provider: row for row in rows}

    assert len(calls) == 1
    assert by_provider["nvidia"].status == "warning"


def test_unconfigured_provider_is_not_called(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = router.AIProviderSecrets()
    calls: list[str] = []
    monkeypatch.setattr(diagnostics, "load_provider_secrets", lambda: cfg)
    monkeypatch.setattr(diagnostics, "_configured", lambda _slot, _cfg: False)
    monkeypatch.setattr(diagnostics, "_invoke_slot", lambda slot, _cfg, _prompt: calls.append(slot.provider) or "OK")

    rows = diagnostics.test_configured_providers()

    assert calls == []
    assert rows
    assert all(row.status == "unconfigured" for row in rows)


def test_provider_slot_groups_are_unique_and_only_production_providers_remain() -> None:
    groups = diagnostics._provider_slot_groups()
    providers = [provider for provider, _slots in groups]
    assert len(providers) == len(set(providers))
    assert providers[0] == "codex"
    assert providers[-1] == "local"
    assert set(providers) == {"codex", "gemini", "nvidia", "groq", "cloudflare", "local"}
    assert "sambanova" not in providers
    assert "cerebras" not in providers
    assert "openrouter" not in providers
    nvidia = dict(groups)["nvidia"]
    assert len(nvidia) >= 2


def test_final_single_test_button_runs_provider_diagnostics_and_router() -> None:
    source = inspect.getsource(MainWindow.test_ai_router_ui)
    assert "test_configured_providers" in source
    assert "test_ai_router" in source
    install_source = inspect.getsource(MainWindow._install_provider_diagnostics_ui)
    assert "Перевірити всі AI-провайдери" not in install_source
