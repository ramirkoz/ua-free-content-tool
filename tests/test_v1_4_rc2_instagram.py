from __future__ import annotations


def test_instagram_discovery_does_not_request_removed_account_type(monkeypatch) -> None:
    from content_agent import instagram_accounts_v1_4 as module

    seen_urls: list[str] = []

    def fake_get(url: str, token: str) -> dict[str, object]:
        seen_urls.append(url)
        assert token == "user-token"
        return {
            "data": [
                {
                    "id": "page-1",
                    "name": "Page One",
                    "access_token": "page-token",
                    "instagram_business_account": {"id": "ig-1", "username": "ig_one"},
                }
            ]
        }

    monkeypatch.setattr(module, "_get", fake_get)
    rows = module.discover_instagram_accounts("user-token", "v26.0")
    assert len(rows) == 1
    assert rows[0].id == "ig-1"
    assert rows[0].username == "ig_one"
    assert rows[0].account_type == "Professional"
    assert seen_urls
    assert all("account_type" not in url for url in seen_urls)


def test_instagram_profile_inspection_does_not_request_removed_account_type(monkeypatch) -> None:
    from content_agent import instagram_api_v1_2_rc4 as module

    seen_urls: list[str] = []

    def fake_request(url: str, *, method: str = "GET", fields=None) -> dict[str, object]:
        seen_urls.append(url)
        return {"id": "ig-1", "username": "ig_one"}

    monkeypatch.setattr(module, "_graph_request", fake_request)
    profile = module.inspect_instagram_profile("ig-1", "page-token", "v26.0")
    assert profile.user_id == "ig-1"
    assert profile.username == "ig_one"
    assert profile.account_type == "Professional"
    assert seen_urls
    assert all("account_type" not in url for url in seen_urls)
