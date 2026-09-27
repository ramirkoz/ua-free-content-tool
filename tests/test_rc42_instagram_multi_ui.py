from __future__ import annotations

from pathlib import Path

from content_agent.config import AppConfig
from content_agent.destinations_v1_4 import (
    InstagramDestination,
    destination_specs,
    instagram_token_for,
    save_instagram_catalog,
)


def test_multiple_instagram_accounts_are_separate_publish_destinations(isolated_data) -> None:
    rows = [
        InstagramDestination(
            id="17841400000000001",
            username="first_profile",
            page_id="1001",
            page_name="First Page",
        ),
        InstagramDestination(
            id="17841400000000002",
            username="second_profile",
            page_id="1002",
            page_name="Second Page",
        ),
    ]
    save_instagram_catalog(rows)
    config = AppConfig(
        instagram_enabled=True,
        facebook_enabled=True,
        facebook_pages=[
            {"id": "1001", "name": "First Page", "access_token": "token-one"},
            {"id": "1002", "name": "Second Page", "access_token": "token-two"},
        ],
    )

    instagram = [spec for spec in destination_specs(config) if spec.platform == "instagram"]
    assert [spec.key for spec in instagram] == [
        "instagram:17841400000000001",
        "instagram:17841400000000002",
    ]
    assert "@first_profile" in instagram[0].label
    assert "@second_profile" in instagram[1].label
    assert instagram_token_for(config, rows[0]) == "token-one"
    assert instagram_token_for(config, rows[1]) == "token-two"


def test_rc42_instagram_settings_are_collapsed_by_default() -> None:
    source = (Path(__file__).parents[1] / "content_agent" / "ui" / "v1_4_rc30_window.py").read_text(encoding="utf-8")
    assert 'text="Показати акаунти ▾"' in source
    assert "details.pack_forget()" in source
    assert "_toggle_instagram_details_rc42" in source
    assert "Перед публікацією можна вибрати один або кілька профілів" in source
    assert 'text="Знайти / оновити всі акаунти"' in source


def test_rc42_keeps_legacy_secret_fields_compatibility_without_primary_token_form() -> None:
    source = (Path(__file__).parents[1] / "content_agent" / "ui" / "v1_4_rc30_window.py").read_text(encoding="utf-8")
    assert 'self.settings_vars.setdefault("instagram_user_id"' in source
    assert 'self.settings_vars.setdefault("instagram_token"' in source
    assert 'text="Instagram Access Token"' not in source
