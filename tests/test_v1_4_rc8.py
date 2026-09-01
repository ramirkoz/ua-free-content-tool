from __future__ import annotations

from types import SimpleNamespace

from content_agent.donation_settings_v1_3_1_rc8 import DonationSettings
import content_agent.ui.v1_4_rc8_window as rc8
import content_agent.ui.v1_4_rc7_window as rc7


class _Var:
    def __init__(self, value=False) -> None:
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value


def test_rc8_version_and_parent() -> None:
    assert rc8.MainWindow.VERSION_LABEL == "1.4.0-rc8"
    assert issubclass(rc8.MainWindow, rc7.MainWindow)


def test_rc8_exact_destination_donation_policy() -> None:
    settings = DonationSettings(text="Support", targets=["facebook:123", "telegram"])
    assert rc8.donation_enabled_for_destination(settings, "facebook:123", "facebook") is True
    assert rc8.donation_enabled_for_destination(settings, "facebook:456", "facebook") is False
    assert rc8.donation_enabled_for_destination(settings, "telegram", "telegram") is True


def test_rc8_legacy_generic_instagram_policy_is_visible_on_concrete_accounts() -> None:
    settings = DonationSettings(text="Support", targets=["instagram"])
    assert rc8.donation_enabled_for_destination(settings, "instagram:111", "instagram") is True
    assert rc8.donation_enabled_for_destination(settings, "instagram:222", "instagram") is True
    assert rc8.donation_enabled_for_destination(settings, "facebook:111", "facebook") is False


def test_rc8_status_counts_visible_destination_switches() -> None:
    window = object.__new__(rc8.MainWindow)
    window._donation_settings = DonationSettings(text="Support", targets=[])
    window.donation_vars = {
        "facebook:123": _Var(True),
        "instagram:111": _Var(True),
        "telegram": _Var(False),
    }
    window.donation_status_var = _Var("")

    rc8.MainWindow._refresh_donation_status(window)

    assert window.donation_status_var.get() == "текст збережено · увімкнено профілів: 2"


def test_rc8_rebuild_uses_v14_destination_readiness(monkeypatch) -> None:
    # The concrete implementation must not fall back to AppConfig.platform_ready
    # for instagram:<id>; that was the v1.4 regression path.
    source = rc8.MainWindow._rebuild_target_controls.__code__.co_names
    assert "destination_ready" in source
    assert "_donation_target_toggled" in source
