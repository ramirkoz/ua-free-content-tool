from __future__ import annotations

from content_agent.ui.media_workflow import (
    MediaWorkflowMixin,
    format_media_size,
    media_filename_from_url,
)
from content_agent.ui.v1_2_combined_window import MainWindow
from content_agent.ui.v1_2_window import MainWindow as EditorialMemoryMainWindow


def test_combined_window_keeps_both_v1_2_layers() -> None:
    assert issubclass(MainWindow, MediaWorkflowMixin)
    assert issubclass(MainWindow, EditorialMemoryMainWindow)


def test_media_display_helpers() -> None:
    assert format_media_size(0) == "0 Б"
    assert format_media_size(1536) == "1.5 КБ"
    assert format_media_size(2 * 1024 * 1024) == "2.0 МБ"
    assert media_filename_from_url("https://cdn.example/path/photo.bad?x=1", "image/jpeg") == "photo.jpg"
