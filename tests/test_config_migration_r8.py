from __future__ import annotations

import json

from content_agent.config import AppConfig


def test_r7_json_config_loads_with_r8_defaults_and_preserves_tokens() -> None:
    old_payload = {
        "ollama_base_url": "http://127.0.0.1:11434",
        "ollama_model": "model-a",
        "meta_user_access_token": "meta-token",
        "threads_user_id": "threads-user",
        "threads_token": "threads-token",
        "linkedin_author_urn": "urn:li:person:123",
        "linkedin_token": "linkedin-token",
        "telegram_bot_token": "telegram-token",
        "telegram_chat_id": "@uafree_org",
    }
    config = AppConfig.from_json_bytes(json.dumps(old_payload).encode("utf-8"))
    assert config.meta_user_access_token == "meta-token"
    assert config.threads_token == "threads-token"
    assert config.linkedin_token == "linkedin-token"
    assert config.telegram_bot_token == "telegram-token"
    assert config.google_client_id == ""
    assert config.google_refresh_token == ""
    assert config.auto_collect_on_start is True
