from __future__ import annotations

from types import SimpleNamespace

from content_agent.source_health import SourceHealth
from content_agent.ui.source_health_v1_3 import SourceHealthV13Mixin


def _mixin(language: str) -> SourceHealthV13Mixin:
    value = SourceHealthV13Mixin()
    value.config = SimpleNamespace(ui_language=language)
    return value


def test_source_health_labels_follow_interface_language() -> None:
    health = SourceHealth(source_id=1, last_success_at="2026-08-18T10:00:00+00:00")
    assert _mixin("uk")._health_label(health) == "🟢 працює"
    assert _mixin("en")._health_label(health) == "🟢 working"


def test_source_health_error_is_compact_and_bilingual() -> None:
    health = SourceHealth(
        source_id=1,
        last_success_at="2026-08-18T10:00:00+00:00",
        last_error_at="2026-08-18T10:01:00+00:00",
        last_error="network timeout",
    )
    assert _mixin("uk")._health_label(health).startswith("🔴 помилка: network timeout")
    assert _mixin("en")._health_label(health).startswith("🔴 error: network timeout")
