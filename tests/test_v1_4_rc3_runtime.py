from __future__ import annotations


def test_rc3_reconciles_discovered_instagram_with_page_token(monkeypatch) -> None:
    from content_agent.config import AppConfig
    from content_agent.destinations_v1_4 import InstagramDestination
    from content_agent.ui import v1_4_rc3_window as module

    config = AppConfig(
        instagram_enabled=False,
        facebook_pages=[{"id": "page-1", "name": "Page One", "access_token": "page-token"}],
    )
    account = InstagramDestination(
        id="ig-1",
        username="ig_one",
        account_type="Professional",
        page_id="page-1",
        page_name="Page One",
        auth_mode="facebook_login",
    )
    monkeypatch.setattr(module, "load_instagram_catalog", lambda: [account])

    assert module.reconcile_instagram_runtime(config) is True
    assert config.instagram_enabled is True


def test_rc3_does_not_enable_stale_instagram_without_page_token(monkeypatch) -> None:
    from content_agent.config import AppConfig
    from content_agent.destinations_v1_4 import InstagramDestination
    from content_agent.ui import v1_4_rc3_window as module

    config = AppConfig(instagram_enabled=False, facebook_pages=[])
    account = InstagramDestination(
        id="ig-1",
        username="ig_one",
        page_id="page-1",
        auth_mode="facebook_login",
    )
    monkeypatch.setattr(module, "load_instagram_catalog", lambda: [account])

    assert module.reconcile_instagram_runtime(config) is False
    assert config.instagram_enabled is False


def test_rc3_removes_inherited_five_minute_catchup_gap() -> None:
    from content_agent.ui.v1_4_rc3_window import Rc3PublicationWorker
    from content_agent.worker_v1_2_rc4 import Rc4PublicationWorker

    assert Rc4PublicationWorker.CATCHUP_GAP_SECONDS == 5 * 60
    assert Rc3PublicationWorker.CATCHUP_GAP_SECONDS == 0
    assert Rc3PublicationWorker.INTER_TARGET_DELAY_SECONDS == 0.0
