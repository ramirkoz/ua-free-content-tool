from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from content_agent.timezone_settings_v1_4_rc19 import (
    SYSTEM_TIMEZONE,
    format_ui_timestamp,
    load_timezone_name,
    save_timezone_name,
)
from content_agent.ui.v1_4_rc19_window import _patch_runtime_timezone


def test_rc19_formats_same_utc_timestamp_for_kyiv_and_berlin() -> None:
    value = "2026-09-05T14:49:51+00:00"
    assert format_ui_timestamp(value, ZoneInfo("Europe/Kyiv")) == "05.09.2026 17:49:51"
    assert format_ui_timestamp(value, ZoneInfo("Europe/Berlin")) == "05.09.2026 16:49:51"


def test_rc19_timezone_conversion_is_dst_aware() -> None:
    berlin = ZoneInfo("Europe/Berlin")
    assert format_ui_timestamp("2026-01-05T12:00:00+00:00", berlin) == "05.01.2026 13:00:00"
    assert format_ui_timestamp("2026-07-05T12:00:00+00:00", berlin) == "05.07.2026 14:00:00"


def test_rc19_legacy_naive_internal_timestamp_is_treated_as_utc() -> None:
    assert format_ui_timestamp(
        "2026-09-05T14:49:51",
        ZoneInfo("Europe/Kyiv"),
    ) == "05.09.2026 17:49:51"


def test_rc19_timezone_store_defaults_to_system_and_roundtrips_override(tmp_path: Path) -> None:
    path = tmp_path / "timezone.json"
    assert load_timezone_name(path) == SYSTEM_TIMEZONE
    assert save_timezone_name("Europe/Berlin", path) == "Europe/Berlin"
    assert load_timezone_name(path) == "Europe/Berlin"
    assert save_timezone_name(SYSTEM_TIMEZONE, path) == SYSTEM_TIMEZONE
    assert load_timezone_name(path) == SYSTEM_TIMEZONE


def test_rc19_runtime_timezone_reaches_scheduler_database_and_rollover_modules() -> None:
    import content_agent.database_v1_4_rc18 as database_rc18
    import content_agent.news_logic as news_logic
    import content_agent.scheduling as scheduling
    import content_agent.ui.main_window as legacy_window
    import content_agent.ui.v1_4_rc18_window as window_rc18

    modules = (scheduling, news_logic, database_rc18, legacy_window, window_rc18)
    originals = [getattr(module, "KYIV") for module in modules]
    berlin = ZoneInfo("Europe/Berlin")
    try:
        _patch_runtime_timezone(berlin)
        for module in modules:
            assert getattr(module, "KYIV") is berlin
    finally:
        for module, original in zip(modules, originals):
            setattr(module, "KYIV", original)


def test_rc19_rc18_rollover_timer_uses_patched_working_timezone() -> None:
    import content_agent.ui.v1_4_rc18_window as window_rc18

    original = window_rc18.KYIV
    berlin = ZoneInfo("Europe/Berlin")
    try:
        _patch_runtime_timezone(berlin)
        now = datetime(2026, 9, 5, 23, 59, 59, tzinfo=berlin)
        assert window_rc18.milliseconds_until_next_kyiv_rollover(now=now) == 3000
    finally:
        _patch_runtime_timezone(original)


def test_rc19_storage_utc_and_display_timezone_are_separate() -> None:
    stored = datetime(2026, 9, 5, 14, 49, 51, tzinfo=timezone.utc).isoformat()
    assert stored.endswith("+00:00")
    assert format_ui_timestamp(stored, ZoneInfo("Europe/Berlin")) == "05.09.2026 16:49:51"
