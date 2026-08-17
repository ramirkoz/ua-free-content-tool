from __future__ import annotations

from pathlib import Path

import pytest

from content_agent import ai_provider_diagnostics_v1_2_1 as diagnostics
from content_agent import ai_router_v1_2_1 as legacy
from content_agent import ai_router_v1_2_2 as bounded
from content_agent import local_ai_runtime_v1_2_2 as local
from content_agent.ollama_client import OllamaError


def test_choose_ollama_model_prefers_existing_requested_model() -> None:
    models = ["qwen3:8b", "qwen3.5:27b", "nomic-embed-text:latest"]
    assert local.choose_ollama_model(models, "qwen3:8b") == "qwen3:8b"


def test_choose_ollama_model_skips_embedding_and_prefers_capable_local_model() -> None:
    models = ["nomic-embed-text:latest", "llama3.2:3b", "qwen3.5:27b", "gemma3:12b"]
    assert local.choose_ollama_model(models, "local-model") == "qwen3.5:27b"


def test_running_ollama_is_reused_without_start_or_download(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(local, "find_ollama_executable", lambda: Path(r"C:\Ollama\ollama.exe"))
    monkeypatch.setattr(local, "_list_ollama_models", lambda timeout=3: ["qwen3.5:27b"])

    def forbidden_start(*args, **kwargs):
        raise AssertionError("running Ollama must not be started again")

    monkeypatch.setattr(local, "start_installed_ollama", forbidden_start)
    target = local.resolve_local_target(preferred_model="local-model")
    assert target.engine == "ollama"
    assert target.model == "qwen3.5:27b"
    assert target.started_by_app is False


def test_installed_stopped_ollama_is_started_then_existing_model_is_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    executable = Path(r"C:\Users\user\AppData\Local\Programs\Ollama\ollama.exe")
    monkeypatch.setattr(local, "find_ollama_executable", lambda: executable)
    calls = {"probe": 0, "start": 0}

    def probe(timeout=3):
        calls["probe"] += 1
        if calls["probe"] == 1:
            raise OllamaError("offline")
        return ["gemma3:12b"]

    def start(*, wait_seconds=15.0):
        calls["start"] += 1
        return executable, True

    monkeypatch.setattr(local, "_list_ollama_models", probe)
    monkeypatch.setattr(local, "start_installed_ollama", start)
    target = local.resolve_local_target(preferred_model="local-model")
    assert target.engine == "ollama"
    assert target.model == "gemma3:12b"
    assert target.started_by_app is True
    assert calls["start"] == 1


def test_manual_llamacpp_is_only_fallback_when_ollama_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(local, "find_ollama_executable", lambda: None)
    monkeypatch.setattr(local, "_list_ollama_models", lambda timeout=3: (_ for _ in ()).throw(OllamaError("offline")))
    target = local.resolve_local_target(
        preferred_model="",
        manual_base_url="http://127.0.0.1:9090/v1",
        manual_model="qwen-local",
    )
    assert target.engine == "llama.cpp"
    assert target.base_url == "http://127.0.0.1:9090/v1"
    assert target.model == "qwen-local"


def test_no_ollama_and_default_placeholder_does_not_trigger_any_install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(local, "find_ollama_executable", lambda: None)
    monkeypatch.setattr(local, "_list_ollama_models", lambda timeout=3: (_ for _ in ()).throw(OllamaError("offline")))
    with pytest.raises(local.LocalAIRuntimeError, match="не знайдено"):
        local.resolve_local_target()


def test_bounded_router_uses_local_runtime_with_small_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}

    def fake_generate_local_text(**kwargs):
        seen.update(kwargs)
        return "OK", local.LocalAITarget("ollama", local.OLLAMA_BASE_URL, "qwen3.5:27b", "qwen3.5:27b / Ollama")

    monkeypatch.setattr(bounded, "generate_local_text", fake_generate_local_text)
    cfg = legacy.AIProviderSecrets(local_enabled=True)
    slot = legacy.AIModelSlot(17, "local", "local-model", "local", "local")
    assert bounded._local_call_limited(slot, cfg, "prompt", max_output_tokens=900) == "OK"
    assert seen["max_output_tokens"] == 900
    assert seen["temperature"] == 0.0


def test_provider_diagnostic_reports_actual_ollama_model(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = legacy.AIProviderSecrets(local_enabled=True)
    monkeypatch.setattr(diagnostics, "load_provider_secrets", lambda: cfg)
    monkeypatch.setattr(
        diagnostics,
        "_provider_slot_groups",
        lambda: [("local", [legacy.AIModelSlot(17, "local", "local-model", "local", "local")])],
    )
    monkeypatch.setattr(
        diagnostics,
        "test_local_runtime",
        lambda **kwargs: local.LocalAITarget("ollama", local.OLLAMA_BASE_URL, "qwen3.5:27b", "qwen3.5:27b / Ollama"),
    )
    rows = diagnostics.test_configured_providers()
    assert len(rows) == 1
    assert rows[0].status == "ok"
    assert rows[0].model == "qwen3.5:27b"
    assert "Ollama" in rows[0].detail

from content_agent.global_duplicates_v1_3_rc6 import parse_duplicate_clusters


def test_duplicate_parser_accepts_json_wrapped_in_model_commentary() -> None:
    raw = 'Звісно. Ось результат:\n```json\n{"clusters":[{"group_ids":[1,2],"confidence":91,"reason":"same"}]}\n```\n'
    rows = parse_duplicate_clusters(raw, {1, 2})
    assert len(rows) == 1
    assert rows[0].group_ids == (1, 2)


def test_duplicate_parser_ignores_unrelated_braces_before_valid_payload() -> None:
    raw = 'analysis {not-json} final {"clusters":[{"group_ids":[3,4],"confidence":88,"reason":"same"}]}'
    rows = parse_duplicate_clusters(raw, {3, 4})
    assert rows[0].group_ids == (3, 4)


def test_bounded_quota_cools_only_model_not_whole_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = legacy.AIProviderSecrets(nvidia_api_key="x", groq_api_key="y")
    state = legacy.AIRouterState()
    calls: list[str] = []
    monkeypatch.setattr(legacy, "load_provider_secrets", lambda: cfg)
    monkeypatch.setattr(legacy, "load_router_state", lambda: state)
    monkeypatch.setattr(legacy, "save_router_state", lambda _value: None)
    monkeypatch.setattr(legacy, "_configured", lambda slot, _cfg: slot.provider in {"nvidia", "groq"})

    def invoke(slot, _cfg, _prompt, _max_output_tokens):
        calls.append(slot.label)
        if slot.provider == "nvidia" and len([item for item in calls if "NVIDIA" in item]) == 1:
            raise legacy.AIModelError("model limit", kind="quota", retry_after=60)
        if slot.provider == "nvidia":
            return "OK"
        return "OTHER"

    monkeypatch.setattr(bounded, "_invoke_limited", invoke)
    result = bounded.run_ai("small task", max_output_tokens=900)
    assert result.provider == "nvidia"
    assert "provider:nvidia" not in state.cooldowns
    assert any(key.startswith("model:nvidia:") for key in state.cooldowns)


def test_bounded_router_retries_local_once_after_validation_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = legacy.AIProviderSecrets(local_enabled=True)
    state = legacy.AIRouterState()
    calls: list[str] = []
    target = local.LocalAITarget("ollama", local.OLLAMA_BASE_URL, "qwen3:4b", "qwen3:4b / Ollama")

    monkeypatch.setattr(legacy, "load_provider_secrets", lambda: cfg)
    monkeypatch.setattr(legacy, "load_router_state", lambda: state)
    monkeypatch.setattr(legacy, "save_router_state", lambda _value: None)
    monkeypatch.setattr(legacy, "_configured", lambda slot, _cfg: slot.provider == "local")

    def local_call(_cfg, prompt, *, max_output_tokens):
        calls.append(prompt)
        return ("BAD" if len(calls) == 1 else "VALID"), target

    monkeypatch.setattr(bounded, "_invoke_local_with_target", local_call)

    def validator(text: str) -> None:
        if text != "VALID":
            raise ValueError("invalid format")

    result = bounded.run_ai("return strict format", validator=validator, max_output_tokens=900)
    assert result.text == "VALID"
    assert result.model == "qwen3:4b"
    assert result.label == "qwen3:4b / Ollama"
    assert len(calls) == 2
