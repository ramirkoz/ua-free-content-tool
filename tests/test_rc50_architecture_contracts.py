from __future__ import annotations

from content_agent.app.container import build_services
from content_agent.config import AppConfig
from content_agent.v2.collection import CollectionService
from content_agent.v2.publishing.destinations import DestinationRegistry
from content_agent.v2.storage.backup_api import BackupService
from content_agent.v2.storage.factory import create_database


def test_composition_root_owns_core_services(tmp_path) -> None:
    db = create_database(tmp_path / "content_agent.sqlite3")
    services = build_services(config=AppConfig(), database=db)
    assert services.db is db
    assert isinstance(services.collection, CollectionService)
    assert isinstance(services.destinations, DestinationRegistry)
    assert isinstance(services.backups, BackupService)
    assert services.collection.supported_kinds() == ("rss", "telegram", "url")


def test_destination_registry_has_one_canonical_platform_view() -> None:
    cfg = AppConfig(
        telegram_enabled=True,
        telegram_bot_token="token",
        telegram_chat_id="@channel",
        facebook_enabled=True,
        facebook_pages=[{"id": "123", "name": "Page", "access_token": "page-token"}],
        instagram_enabled=True,
        instagram_user_id="ig-id",
        instagram_token="ig-token",
        threads_enabled=True,
        threads_user_id="threads-id",
        threads_token="threads-token",
        linkedin_enabled=True,
        linkedin_author_urn="urn:li:person:1",
        linkedin_token="li-token",
    )
    registry = DestinationRegistry(cfg)
    keys = {item.key for item in registry.all()}
    assert {"telegram", "facebook:123", "instagram", "threads", "linkedin", "google_drive"} <= keys
    assert registry.get("instagram").managed_elsewhere is True
    assert registry.get("telegram").publisher_factory_key == "telegram"


def test_ui_components_and_inbox_controller_are_unversioned() -> None:
    from content_agent.v2.ui import components, inbox_controller

    assert components.__name__.endswith(".components")
    assert inbox_controller.__name__.endswith(".inbox_controller")
    assert "rc50" not in components.__name__.casefold()
    assert "rc50" not in inbox_controller.__name__.casefold()
