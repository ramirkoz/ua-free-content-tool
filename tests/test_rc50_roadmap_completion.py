from __future__ import annotations

import os
from pathlib import Path

import pytest


def test_ai_service_accepts_stable_ui_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UA_FREE_CONTENT_DATA", str(tmp_path / "Data"))
    from content_agent.paths import reset_path_cache_for_tests
    reset_path_cache_for_tests()

    from content_agent.v2.ai.service import backend_status
    from content_agent.v2.ai.settings import BACKEND_AGENT, BACKEND_OPENROUTER, BACKEND_ROUTER
    from content_agent.v2.ai.usage import usage_summary

    structured = backend_status()
    assert isinstance(structured, dict)
    assert isinstance(backend_status(BACKEND_ROUTER), str)
    assert isinstance(backend_status(BACKEND_AGENT), str)
    assert isinstance(backend_status(BACKEND_OPENROUTER, openrouter_key="x"), str)
    budget = usage_summary(25.0)
    assert budget["budget"] == 25.0
    assert budget["remaining"] >= 0.0


def test_authenticated_release_manifest_fixture() -> None:
    from content_agent.v2.supervisor.release_manifest import verify_manifest

    payload = {
        "schema": "ua-free-content-tool-release-v1",
        "version": "2.0.0-rc50",
        "asset_name": "UA_FREE_Content_Tool_v2.0.0-rc50_Windows_Portable.zip",
        "sha256": "1" * 64,
        "minimum_updater_version": "2.0.0-rc50",
        "rollback_version": "2.0.0-rc49",
    }
    signature = "ZAPZqv1rP56yggDgiwK34uW8gnh5ji7fXE4YslFM+KdrQkKJkTg8CD3l6vkhu0mt+DuAV2+6sTsQo32uty6rBA=="
    result = verify_manifest(payload, signature)
    assert result.version == "2.0.0-rc50"
    broken = dict(payload)
    broken["sha256"] = "2" * 64
    with pytest.raises(RuntimeError, match="SIGNATURE"):
        verify_manifest(broken, signature)


def test_composition_owns_destinations_and_backup_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UA_FREE_CONTENT_DATA", str(tmp_path / "Data"))
    from content_agent.paths import reset_path_cache_for_tests
    reset_path_cache_for_tests()

    from content_agent.app.container import build_services
    from content_agent.config import AppConfig

    services = build_services(config=AppConfig())
    assert services.destinations.labels() == {}
    assert callable(services.backups.create)
    assert callable(services.ai.execute)


@pytest.mark.skipif(os.name != "nt", reason="real Tk startup smoke is a Windows product gate")
def test_real_main_window_builds_all_tabs_and_ai_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UA_FREE_CONTENT_DATA", str(tmp_path / "Data"))
    monkeypatch.setenv("UA_FREE_PORTABLE_ROOT", str(tmp_path / "Portable"))
    from content_agent.paths import reset_path_cache_for_tests
    reset_path_cache_for_tests()

    import tkinter as tk
    from content_agent.app.container import build_services
    from content_agent.config import AppConfig
    from content_agent.v2.ui.manual_topics_window_rc44 import MainWindow

    root = tk.Tk()
    root.withdraw()
    try:
        services = build_services(config=AppConfig())
        window = MainWindow(root, services)
        # This is the path that RC49 manual testing exposed twice. Construct the
        # complete real window, then execute the status refresh that used to crash.
        window.refresh_v2_ai_status()
        labels = [window.notebook.tab(i, "text") for i in range(window.notebook.index("end"))]
        assert "AI" in labels
        assert getattr(window, "inbox_source_filter_box", None) is not None
        assert getattr(window, "inbox_topic_filter_box", None) is not None
        assert isinstance(window.v2_ai_status_var.get(), str)
        assert window.v2_ai_status_var.get()
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def test_no_rc50_window_layer_added() -> None:
    root = Path(__file__).resolve().parents[1] / "content_agent"
    bad = [path for path in root.rglob("*.py") if "rc50" in path.name.casefold() and "window" in path.name.casefold()]
    assert bad == []
