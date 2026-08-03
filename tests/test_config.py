from __future__ import annotations

import os
from pathlib import Path

import pytest

from content_agent.config import AppConfig, ConfigError, load_config, save_config


def test_config_roundtrip_in_test_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UA_FREE_TEST_PLAINTEXT_CONFIG", "1")
    path = tmp_path / "config.dpapi"
    original = AppConfig(
        ollama_model="qwen3:8b",
        ollama_fallback_model="gemma3:4b",
        telegram_bot_token="123456:ABC_secret_token_value",
        telegram_chat_id="@uafree_test",
        publish_interval_minutes=20,
    )
    save_config(original, path)
    loaded = load_config(path)
    assert loaded.ollama_model == "qwen3:8b"
    assert loaded.ollama_fallback_model == "gemma3:4b"
    assert loaded.telegram_bot_token == original.telegram_bot_token
    assert loaded.publish_interval_minutes == 20
    raw = path.read_bytes()
    if os.name == "nt":
        # Production Windows behavior must keep DPAPI even when the test-only
        # environment variable is present. Never weaken secret storage.
        assert not raw.startswith(b"UA_FREE_TEST_PLAINTEXT_V1\n")
        assert original.telegram_bot_token.encode("utf-8") not in raw
    else:
        assert raw.startswith(b"UA_FREE_TEST_PLAINTEXT_V1\n")


def test_config_rejects_remote_ollama() -> None:
    with pytest.raises(ConfigError):
        AppConfig(ollama_base_url="https://example.com").validate()


def test_config_rejects_unknown_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UA_FREE_TEST_PLAINTEXT_CONFIG", "1")
    path = tmp_path / "config.dpapi"
    path.write_bytes(b'UA_FREE_TEST_PLAINTEXT_V1\n{"unknown": true}')
    with pytest.raises(ConfigError):
        load_config(path)


def test_publish_interval_cannot_be_shorter_than_15_minutes() -> None:
    import pytest
    from content_agent.config import ConfigError

    with pytest.raises(ConfigError):
        AppConfig(publish_interval_minutes=14).validate()


def test_platform_ready_requires_only_derived_runtime_credentials() -> None:
    config = AppConfig(
        facebook_page_1_id="1",
        facebook_page_1_token="page-token",
        threads_user_id="2",
        threads_token="threads-token",
        linkedin_author_urn="urn:li:person:3",
        linkedin_token="linkedin-token",
        telegram_bot_token="bot-token",
        telegram_chat_id="@channel",
    )
    assert config.platform_ready("facebook:1")
    assert config.platform_ready("threads")
    assert config.platform_ready("linkedin")
    assert config.platform_ready("telegram")
    assert not config.platform_ready("facebook:2")


def test_old_empty_api_versions_are_migrated_to_hidden_defaults() -> None:
    config = AppConfig.from_json_bytes(
        b'{"ollama_base_url":"http://127.0.0.1:11434","meta_graph_version":"","linkedin_version":""}'
    )
    assert config.meta_graph_version == "v24.0"
    assert config.linkedin_version == "202607"
