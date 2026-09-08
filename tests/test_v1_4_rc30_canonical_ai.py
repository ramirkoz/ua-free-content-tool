from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from content_agent import ai_router
from content_agent import codex_runtime


def test_ui_engine_uses_canonical_router_objects() -> None:
    module = importlib.import_module("content_agent.ui.ai_engine_v1_3")
    assert module.test_ai_router is ai_router.test_ai_router
    assert module.clear_router_cooldowns is ai_router.clear_router_cooldowns
    assert module.router_overview_cached is ai_router.router_overview_cached
    assert module.codex_router_status is ai_router.codex_router_status


def test_current_window_chain_cannot_downgrade_router() -> None:
    pytest.importorskip("tzlocal")
    names = [
        "content_agent.ui.v1_4_rc22_window",
        "content_agent.ui.v1_4_rc23_window",
        "content_agent.ui.v1_4_rc24_window",
        "content_agent.ui.v1_4_rc25_window",
        "content_agent.ui.v1_4_rc26_window",
        "content_agent.ui.v1_4_rc27_window",
        "content_agent.ui.v1_4_rc28_window",
        "content_agent.ui.v1_4_rc29_window",
        "content_agent.ui.v1_4_rc30_window",
    ]
    for name in names:
        importlib.import_module(name)
    engine = importlib.import_module("content_agent.ui.ai_engine_v1_3")
    assert engine.test_ai_router is ai_router.test_ai_router


def test_active_ai_consumers_have_no_versioned_router_imports() -> None:
    root = Path(__file__).resolve().parents[1] / "content_agent"
    targets = [
        root / "ui" / "ai_engine_v1_3.py",
        *sorted((root / "ui").glob("v1_4_rc2[2-9]_window.py")),
        root / "ui" / "v1_4_rc30_window.py",
        root / "codex_news_v1_3.py",
        root / "rewrite_pipeline_v1_3.py",
        root / "rewrite_pipeline_v1_4_rc26.py",
        root / "rewrite_pipeline_v1_4_rc27.py",
        root / "ai_provider_diagnostics_v1_2_1.py",
        root / "active_ai_providers_v1_2_1.py",
    ]
    for path in targets:
        text = path.read_text(encoding="utf-8")
        assert "ai_router_v1_" not in text, path
        assert "codex_engine_v1_" not in text, path


def test_diagnostics_cannot_restore_12_second_codex_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, int] = {}
    slot = next(item for item in ai_router.MODEL_SLOTS if item.provider == "codex")
    cfg = ai_router.AIProviderSecrets()

    def fake_invoke(runtime_slot, _cfg, _prompt, *, max_output_tokens, timeout_seconds, local_prompt, local_max_output_tokens):
        captured["timeout"] = int(timeout_seconds)
        return "OK", runtime_slot

    monkeypatch.setattr(ai_router, "_invoke_route", fake_invoke)
    assert ai_router._invoke_limited(slot, cfg, "x", 64, timeout_seconds=12) == "OK"
    assert captured["timeout"] >= 45


def test_router_test_never_caps_codex_at_ten_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    codex = next(item for item in ai_router.MODEL_SLOTS if item.provider == "codex")
    state = ai_router.AIRouterState()
    captured: list[int] = []

    monkeypatch.setattr(ai_router, "load_provider_secrets", lambda: ai_router.AIProviderSecrets())
    monkeypatch.setattr(ai_router, "load_router_state", lambda: state)
    monkeypatch.setattr(ai_router, "save_router_state", lambda _state: None)
    monkeypatch.setattr(ai_router, "_normalize_state", lambda: None)
    monkeypatch.setattr(ai_router, "_available_routes", lambda **_kwargs: [codex])

    def fake_invoke(slot, cfg, prompt, *, max_output_tokens, timeout_seconds, local_prompt, local_max_output_tokens):
        captured.append(int(timeout_seconds))
        return "AI Router працює", slot

    monkeypatch.setattr(ai_router, "_invoke_route", fake_invoke)
    result = ai_router.run_ai("test", max_output_tokens=128, cloud_timeout_seconds=10, task_timeout_seconds=90)
    assert result.provider == "codex"
    assert captured == [45]


def test_local_fallback_is_after_best_cloud_not_after_whole_cloud_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = ai_router.AIProviderSecrets(
        gemini_api_key="g",
        nvidia_api_key="n",
        groq_api_key="q",
        cloudflare_account_id="a",
        cloudflare_api_token="t",
        local_enabled=True,
        local_model="local-model",
    )
    state = ai_router.AIRouterState()
    monkeypatch.setattr(ai_router, "_configured", lambda _slot, _cfg: True)
    routes = ai_router._available_routes(cfg=cfg, state=state, skip_providers=set(), skip_models=set())
    providers = [slot.provider for slot in routes]
    assert "local" in providers
    assert providers.index("local") == 1


def test_codex_runtime_is_canonical_and_side_by_side() -> None:
    assert codex_runtime.CODEX_PACKAGE == "openai-codex==0.147.0"
    source = Path(codex_runtime.__file__).read_text(encoding="utf-8")
    assert "codex_versions" in source
    assert "--target" in source
    assert "codex_engine_v1_" not in source
