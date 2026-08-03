from __future__ import annotations

from pathlib import Path

import pytest

from content_agent.config import AppConfig
from content_agent.connection_diagnostics import (
    STATUS_ATTENTION,
    STATUS_OK,
    STATUS_REPLACE,
    STATUS_TEMPORARY,
    diagnose_connections,
)
from content_agent.google_drive import GoogleDriveError, GoogleDriveProfile
from content_agent.platform_setup import (
    LinkedInProfile,
    MetaPage,
    MetaProfile,
    PlatformSetupError,
    TelegramProfile,
    ThreadsProfile,
)


def _full_config() -> AppConfig:
    return AppConfig(
        meta_user_access_token="meta-token",
        threads_token="threads-token",
        linkedin_token="linkedin-token",
        telegram_bot_token="telegram-token",
        telegram_chat_id="@channel",
        google_client_id="client.apps.googleusercontent.com",
        google_client_secret="secret",
        google_refresh_token="refresh-token",
        threads_trend_search_enabled=True,
    )


def test_diagnostics_distinguishes_bad_tokens_permissions_and_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "content_agent.connection_diagnostics.inspect_meta_token",
        lambda *_args: (_ for _ in ()).throw(
            PlatformSetupError("Invalid OAuth access token", code=190, http_status=401)
        ),
    )
    monkeypatch.setattr(
        "content_agent.connection_diagnostics.inspect_threads_token",
        lambda _token: ThreadsProfile("42", "uafree", "UA FREE"),
    )
    monkeypatch.setattr(
        "content_agent.connection_diagnostics.check_threads_keyword_access",
        lambda _token: (False, "Network request failed: DNS resolution failed"),
    )
    monkeypatch.setattr(
        "content_agent.connection_diagnostics.inspect_linkedin_token",
        lambda token: LinkedInProfile("urn:li:person:1", "User", token, 0),
    )
    monkeypatch.setattr(
        "content_agent.connection_diagnostics.inspect_telegram_bot",
        lambda *_args: (_ for _ in ()).throw(
            PlatformSetupError("бот не є адміністратором", http_status=403)
        ),
    )
    monkeypatch.setattr(
        "content_agent.connection_diagnostics.inspect_google_drive_connection",
        lambda *_args: (_ for _ in ()).throw(GoogleDriveError("invalid_grant")),
    )

    report = diagnose_connections(_full_config())
    statuses = {item.key: item.status for item in report.items}
    assert statuses == {
        "facebook": STATUS_REPLACE,
        "threads": STATUS_TEMPORARY,
        "linkedin": STATUS_OK,
        "telegram": STATUS_ATTENTION,
        "google_drive": STATUS_REPLACE,
    }
    telegram = next(item for item in report.items if item.key == "telegram")
    assert "права" in telegram.message.lower()
    threads = next(item for item in report.items if item.key == "threads")
    assert "токен автоматично" not in threads.message.lower() or "профіль працює" in threads.message.lower()


def test_diagnostics_returns_refreshed_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [MetaPage("1", "Page", "fresh-page-token")]
    monkeypatch.setattr(
        "content_agent.connection_diagnostics.inspect_meta_token",
        lambda *_args: (MetaProfile("7", "Owner"), pages),
    )
    monkeypatch.setattr(
        "content_agent.connection_diagnostics.inspect_threads_token",
        lambda _token: ThreadsProfile("42", "uafree", "UA FREE"),
    )
    monkeypatch.setattr(
        "content_agent.connection_diagnostics.check_threads_keyword_access",
        lambda _token: (True, "ok"),
    )
    monkeypatch.setattr(
        "content_agent.connection_diagnostics.inspect_linkedin_token",
        lambda token: LinkedInProfile("urn:li:person:1", "User", token, 0),
    )
    monkeypatch.setattr(
        "content_agent.connection_diagnostics.inspect_telegram_bot",
        lambda *_args: TelegramProfile("bot", "Bot", "Channel", "channel", "administrator", True),
    )
    monkeypatch.setattr(
        "content_agent.connection_diagnostics.inspect_google_drive_connection",
        lambda *_args: GoogleDriveProfile("user@example.com", "User"),
    )

    report = diagnose_connections(_full_config())
    assert all(item.status == STATUS_OK for item in report.items)
    assert report.meta_pages == tuple(pages)
    assert report.threads_profile and report.threads_profile.id == "42"
    assert report.linkedin_profile and report.linkedin_profile.author_urn.endswith(":1")
    assert report.telegram_profile and report.telegram_profile.can_post_messages is True
    assert report.google_profile and report.google_profile.account_email == "user@example.com"


def test_fix14_ui_has_automatic_and_manual_token_diagnostics() -> None:
    source = Path("content_agent/ui/main_window.py").read_text(encoding="utf-8")
    assert "TOKEN_DIAGNOSTIC_INTERVAL_MS = 6 * 60 * 60 * 1000" in source
    assert "Перевірити всі підключення зараз" in source
    assert "self.root.after(2200, lambda: self.run_connection_diagnostics(automatic=True))" in source
    assert "can_post_messages" in source
