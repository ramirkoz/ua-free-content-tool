from __future__ import annotations

import base64
import json
import threading
import time

import pytest


def test_ai_service_contract_matches_ui_calls() -> None:
    from content_agent.v2.ai import service
    from content_agent.v2.ui import window

    assert isinstance(service.backend_status(), dict)
    for name in ("openrouter", "router", "agent"):
        assert isinstance(service.backend_status_text(name), str)
    source = open(window.__file__, encoding="utf-8").read()
    assert "backend_status(" not in source
    assert "backend_status_text(" in source
    assert "test_connection()" not in source
    assert 'usage_summary(backend="openrouter")' in source


def test_release_manifest_known_good_vector() -> None:
    from content_agent.v2.supervisor.release_manifest import verify_release_manifest

    manifest = {
        "schema": "ua-free-content-tool-release-manifest-v1",
        "version": "2.0.0-rc51",
        "asset_name": "UA_FREE_Content_Tool_v2.0.0-rc51_Windows_Portable.zip",
        "sha256": "1" * 64,
        "minimum_updater_version": "2.0.0-rc50",
        "rollback_version": "2.0.0-rc50",
        "created_at": "2026-09-29T00:00:00+00:00",
    }
    signature = b"THzxFDeg5MZJWskAazgrQRk7IHT5zVOUHX6xwWRZxp4AuE7PspXIFFtlnCjD6bxCDV7Z2AWKJ9T+zPFk0CqsCA==\n"
    verified = verify_release_manifest(json.dumps(manifest).encode(), signature)
    assert verified.version == "2.0.0-rc51"
    assert verified.minimum_updater_version == "2.0.0-rc50"


def test_release_manifest_rejects_tamper() -> None:
    from content_agent.v2.supervisor.release_manifest import ReleaseManifestError, verify_release_manifest

    manifest = {
        "schema": "ua-free-content-tool-release-manifest-v1",
        "version": "2.0.0-rc51",
        "asset_name": "UA_FREE_Content_Tool_v2.0.0-rc51_Windows_Portable.zip",
        "sha256": "2" * 64,
        "minimum_updater_version": "2.0.0-rc50",
        "rollback_version": "2.0.0-rc50",
        "created_at": "2026-09-29T00:00:00+00:00",
    }
    signature = b"THzxFDeg5MZJWskAazgrQRk7IHT5zVOUHX6xwWRZxp4AuE7PspXIFFtlnCjD6bxCDV7Z2AWKJ9T+zPFk0CqsCA==\n"
    with pytest.raises(ReleaseManifestError):
        verify_release_manifest(json.dumps(manifest).encode(), signature)


def test_maintenance_gate_allows_shared_connections_and_exclusive_waits() -> None:
    from content_agent.maintenance import MaintenanceGate

    gate = MaintenanceGate()
    entered: list[str] = []
    release = threading.Event()

    def reader(name: str) -> None:
        with gate.shared():
            entered.append(name)
            release.wait(2)

    first = threading.Thread(target=reader, args=("r1",))
    second = threading.Thread(target=reader, args=("r2",))
    first.start(); second.start()
    deadline = time.time() + 2
    while len(entered) < 2 and time.time() < deadline:
        time.sleep(0.01)
    assert set(entered) == {"r1", "r2"}

    writer_entered = threading.Event()
    def writer() -> None:
        with gate:
            writer_entered.set()
    w = threading.Thread(target=writer)
    w.start()
    time.sleep(0.05)
    assert not writer_entered.is_set()
    release.set()
    first.join(2); second.join(2); w.join(2)
    assert writer_entered.is_set()


def test_composition_root_has_remaining_services() -> None:
    from content_agent.app.container import AppServices

    fields = set(AppServices.__dataclass_fields__)
    assert {"db", "config", "ai", "destinations", "collection", "publishing", "maintenance"} <= fields


def test_destination_registry_treats_drive_as_media_source() -> None:
    from content_agent.config import AppConfig
    from content_agent.v2.publishing.registry import DestinationRegistry

    registry = DestinationRegistry(AppConfig())
    drive = registry.by_key("google_drive")
    assert drive is not None
    assert drive.role == "media_source"
    assert drive.platform == "google_drive"


def test_numbered_migrations_own_manual_topics_schema() -> None:
    from content_agent.v2.storage.migrations import MIGRATIONS

    ids = [item[0] for item in MIGRATIONS]
    assert ids[-3:] == [
        "0009_publication_target_outcome",
        "0010_articles_discovered_at_index",
        "0011_manual_source_topics",
    ]
    source = open("content_agent/v2/storage/manual_topics.py", encoding="utf-8").read()
    assert "ALTER TABLE sources ADD COLUMN topic_id" not in source
    assert "CREATE TABLE IF NOT EXISTS manual_topics" not in source


def test_no_active_direct_router_runtime_monkeypatch() -> None:
    from pathlib import Path

    assert not Path("content_agent/v2/ai/direct_router_runtime.py").exists()
    service = Path("content_agent/v2/ai/service.py").read_text(encoding="utf-8")
    assert "install_direct_router_runtime" not in service


def test_rc50_adds_no_versioned_window_layer() -> None:
    from pathlib import Path

    bad = [p for p in Path("content_agent").rglob("*.py") if "rc50" in p.name.casefold() and "test" not in p.name.casefold()]
    assert bad == []


def test_active_ui_mro_does_not_grow() -> None:
    from content_agent.v2.ui.manual_topics_window_rc44 import MainWindow

    assert len(MainWindow.__mro__) <= 62
    assert MainWindow.__mro__[0].__module__ == "content_agent.v2.ui.manual_topics_window_rc44"
