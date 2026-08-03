from __future__ import annotations

import pytest

from content_agent.platform_setup import (
    MetaPage,
    PlatformSetupError,
    inspect_linkedin_token,
    inspect_telegram_bot,
    load_meta_pages,
    inspect_threads_token,
)



def test_linkedin_token_returns_profile_without_pkce(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def fake_get(url: str, *, bearer: str = "") -> dict[str, object]:
        captured["url"] = url
        captured["bearer"] = bearer
        return {"sub": "123", "name": "Test User"}

    monkeypatch.setattr("content_agent.platform_setup._get_json", fake_get)
    profile = inspect_linkedin_token("linkedin-token")
    assert profile.author_urn == "urn:li:person:123"
    assert profile.name == "Test User"
    assert profile.access_token == "linkedin-token"
    assert captured == {"url": "https://api.linkedin.com/v2/userinfo", "bearer": "linkedin-token"}


def test_linkedin_token_is_required() -> None:
    with pytest.raises(PlatformSetupError, match="LinkedIn Access Token"):
        inspect_linkedin_token("")


def test_meta_user_token_loads_pages_without_device_login(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def fake_get(url: str, *, bearer: str = "") -> dict[str, object]:
        captured["url"] = url
        captured["bearer"] = bearer
        return {"data": [{"id": "1", "name": "Page", "access_token": "page-token"}]}

    monkeypatch.setattr("content_agent.platform_setup._get_json", fake_get)
    pages = load_meta_pages("user-token", "v24.0")
    assert pages == [MetaPage("1", "Page", "page-token")]
    assert captured["bearer"] == "user-token"
    assert "/me/accounts?" in captured["url"]


def test_meta_user_token_is_required() -> None:
    with pytest.raises(PlatformSetupError, match="User Access Token"):
        load_meta_pages("", "v24.0")


def test_threads_token_automatically_returns_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_get(url: str, *, bearer: str = "", timeout: float = 60.0) -> dict[str, object]:
        captured.update(url=url, bearer=bearer, timeout=timeout)
        return {"id": "42", "username": "uafree", "name": "UA FREE"}

    monkeypatch.setattr("content_agent.platform_setup._get_json", fake_get)
    profile = inspect_threads_token("token")
    assert profile.id == "42"
    assert profile.username == "uafree"
    assert str(captured["url"]).startswith("https://graph.threads.net/me?")
    assert "/v1.0/me" not in str(captured["url"])
    assert "access_token=" not in str(captured["url"])
    assert captured["bearer"] == "token"
    assert captured["timeout"] == 12


def test_threads_failed_to_decode_has_actionable_message(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, *, bearer: str = "", timeout: float = 60.0) -> dict[str, object]:
        raise PlatformSetupError("Failed to decode")

    monkeypatch.setattr("content_agent.platform_setup._get_json", fake_get)
    with pytest.raises(PlatformSetupError, match="Generate Threads Access Token"):
        inspect_threads_token("broken-token")


def test_telegram_check_uses_bot_and_target(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = iter(
        [
            {"ok": True, "result": {"id": 123456, "username": "uafree_bot", "first_name": "UA FREE"}},
            {"ok": True, "result": {"title": "UA FREE channel", "type": "channel"}},
            {"ok": True, "result": {"status": "administrator", "can_post_messages": True}},
        ]
    )
    monkeypatch.setattr("content_agent.platform_setup._get_json", lambda _url, bearer="": next(responses))
    profile = inspect_telegram_bot("123456:abcdefghijklmnopqrstuvwxyz", "@uafree")
    assert profile.username == "uafree_bot"
    assert profile.target_title == "UA FREE channel"


def test_linkedin_service_error_is_reported_instead_of_false_missing_sub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get(url: str, *, bearer: str = "") -> dict[str, object]:
        raise PlatformSetupError(
            "Not enough permissions to access: GET /userinfo",
            code=100,
            http_status=403,
        )

    monkeypatch.setattr("content_agent.platform_setup._get_json", fake_get)
    with pytest.raises(PlatformSetupError) as caught:
        inspect_linkedin_token("active-token")
    message = str(caught.value)
    assert "Not enough permissions" in message
    assert "openid, profile та w_member_social" in message


def test_telegram_channel_requires_admin_post_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        [
            {"ok": True, "result": {"id": 123, "username": "bot", "first_name": "Bot"}},
            {"ok": True, "result": {"title": "Channel", "type": "channel"}},
            {"ok": True, "result": {"status": "member"}},
        ]
    )
    monkeypatch.setattr("content_agent.platform_setup._get_json", lambda _url, bearer="": next(responses))
    with pytest.raises(PlatformSetupError, match="не є адміністратором"):
        inspect_telegram_bot("123:token", "@channel")


def test_linkedin_payload_level_status_is_parsed_as_error() -> None:
    from content_agent.platform_setup import _json_response

    with pytest.raises(PlatformSetupError) as caught:
        _json_response(
            b'{"status":403,"serviceErrorCode":100,"message":"Not enough permissions"}',
            http_status=200,
        )
    assert caught.value.code == 100
    assert caught.value.http_status == 403
    assert "Not enough permissions" in str(caught.value)
