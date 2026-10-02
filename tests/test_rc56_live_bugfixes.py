from __future__ import annotations

import inspect
from io import BytesIO

from PIL import Image

from content_agent.anti_slop import assess_ukrainian_slop
from content_agent.media_candidates import ValidatedMedia
from content_agent.telegram_media_v1_3_rc6 import _resolve_details, discover_telegram_post_media
from content_agent.v2.media_rc56 import normalize_instagram_safe_image
from content_agent.v2.storage.manual_topics import ManualTopicsMixin
from content_agent.v2.ui.manual_topics_window_rc44 import MainWindow
from content_agent.v2.ui.tabs.inbox import InboxTabController


def _png(width: int, height: int) -> bytes:
    image = Image.new("RGB", (width, height), "white")
    data = BytesIO()
    image.save(data, "PNG")
    return data.getvalue()


def test_rc56_instagram_static_image_is_normalized_to_supported_ratio():
    raw = _png(100, 400)
    media = ValidatedMedia(raw, "image", "image/png", "https://example.test/a.png", len(raw))
    normalized = normalize_instagram_safe_image(media)
    with Image.open(BytesIO(normalized.data)) as image:
        width, height = image.size
    assert normalized.mime_type == "image/jpeg"
    assert 4 / 5 <= width / height <= 1.91
    assert width >= 320


def test_rc56_anti_slop_blocks_vague_source_authority():
    for text in (
        "Офіційні джерела повідомляють про завершення перевірки.",
        "За даними джерел, рішення вже ухвалили.",
    ):
        result = assess_ukrainian_slop(text, profile="news")
        assert not result.publishable
        assert any(item.rule == "S10" and item.severity == "blocker" for item in result.findings)


def test_rc56_settings_ai_duplicate_is_removed_by_canonical_shell():
    source = inspect.getsource(MainWindow._replace_ollama_settings_panel)
    assert "AI configuration lives only in the dedicated AI tab" in source
    assert "widget.destroy()" in source


def test_rc56_media_discovery_has_visible_dedicated_progress():
    source = inspect.getsource(MainWindow)
    assert "_rc56_media_progress" in source
    assert "progress.start(12)" in source
    assert "progress.stop" in source


def test_rc56_inbox_search_uses_unicode_casefold_sql():
    source = inspect.getsource(ManualTopicsMixin.list_inbox_groups)
    assert 'create_function("CASEFOLD"' in source
    assert "token.casefold()" in source
    assert "CASEFOLD(g.canonical_title)" in source


def test_rc56_inbox_refresh_preserves_a_surviving_viewport_anchor():
    source = inspect.getsource(InboxTabController.refresh)
    assert "viewport_anchors" in source
    assert "next((iid for iid in viewport_anchors" in source
    assert "new_children.index(anchor)" in source


def test_rc56_telegram_exact_media_retries_and_reports_resolution_failure():
    discovery_source = inspect.getsource(discover_telegram_post_media)
    resolution_source = inspect.getsource(_resolve_details)
    assert "for attempt in range(" in discovery_source
    assert '"Cache-Control": "no-cache"' in discovery_source
    assert "extract_html_media" in resolution_source
    assert "TELEGRAM_MEDIA_NOT_RESOLVED" in discovery_source


def test_rc56_does_not_add_another_versioned_window_layer():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "content_agent"
    assert not list(root.rglob("*window_rc56*.py"))
