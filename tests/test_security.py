from __future__ import annotations

from content_agent.security import redact_secrets, redact_url


def test_redacts_authorization_and_tokens() -> None:
    text = "Authorization: Bearer secret_token_abcdefghijklmnopqrstuvwxyz access_token=EA1234567890123456789012345"
    redacted = redact_secrets(text)
    assert "secret_token" not in redacted
    assert "EA123" not in redacted


def test_redacts_telegram_token_in_url_path() -> None:
    url = "https://api.telegram.org/bot123456:abcdefghijklmnopqrstuvwxyz/sendMessage?chat_id=x"
    redacted = redact_url(url)
    assert "abcdefghijklmnopqrstuvwxyz" not in redacted
    assert "chat_id" not in redacted
