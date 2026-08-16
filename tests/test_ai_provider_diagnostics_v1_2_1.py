from __future__ import annotations

import pytest

from content_agent import ai_provider_diagnostics_v1_2_1 as diagnostics
from content_agent import ai_router_v1_2_1 as router


def test_provider_diagnostics_checks_each_configured_provider_once(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = router.AIProviderSecrets(
        gemini_api_key="gem",
        nvidia_api_key="nv",
        cerebras_api_key="cer",
    )
    calls: list[str] = []

    monkeypatch.setattr(diagnostics, "load_provider_secrets", lambda: cfg)
    monkeypatch.setattr(
        diagnostics,
        "_configured",
        lambda slot, _cfg: slot.provider in {"gemini", "nvidia", "cerebras"},
    )

    def invoke(slot: router.AIModelSlot, _cfg: router.AIProviderSecrets, _prompt: str) -> str:
        calls.append(slot.provider)
        if slot.provider == "nvidia":
            raise router.AIModelError("quota", kind="quota")
        if slot.provider == "cerebras":
            raise router.AIModelError("bad key", kind="auth")
        return "UA_FREE_PROVIDER_OK"

    monkeypatch.setattr(diagnostics, "_invoke_slot", invoke)
    rows = diagnostics.test_configured_providers()
    by_provider = {row.provider: row for row in rows}

    assert calls.count("gemini") == 1
    assert calls.count("nvidia") == 1
    assert calls.count("cerebras") == 1
    assert by_provider["gemini"].status == "ok"
    assert by_provider["nvidia"].status == "warning"
    assert by_provider["cerebras"].status == "error"


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


def test_provider_diagnostics_uses_only_first_model_per_provider() -> None:
    providers = [slot.provider for slot in diagnostics._representative_slots()]
    assert len(providers) == len(set(providers))
    assert providers[0] == "codex"
    assert "nvidia" in providers
    assert "sambanova" in providers
    assert providers[-1] == "local"
