from __future__ import annotations

import inspect

from content_agent.network import HttpResponse
from content_agent.telegram_media_v1_3_rc6 import (
    _exact_public_post_fragment,
    discover_telegram_post_media,
    extract_telegram_post_media,
)
from content_agent.v2.ui.manual_topics_window_rc44 import MainWindow


def test_rc60_opening_material_does_not_auto_start_media_scan() -> None:
    source = inspect.getsource(MainWindow.load_group)
    assert "super(MediaWorkflowMixin, self).load_group(group_id)" in source
    assert "self.discover_current_group_media" not in source
    assert "Натисніть «Знайти медіа в джерелах»" in source


def test_rc60_progress_tracks_selected_media_download_and_upload() -> None:
    source = inspect.getsource(MainWindow.use_selected_media_candidate)
    assert "self._begin_media_busy()" in source
    assert "download_media_candidate(candidate)" in source
    assert "upload_validated_media" in source
    assert "self._post_ui(self._finish_media_busy)" in source


def test_rc60_local_upload_also_tracks_media_progress() -> None:
    source = inspect.getsource(MainWindow._upload_media)
    assert "self._begin_media_busy()" in source
    assert "upload_validated_media" in source
    assert "self._post_ui(self._finish_media_busy)" in source


def test_rc60_public_telegram_fragment_excludes_neighbour_posts() -> None:
    html = (
        '<div class="tgme_widget_message" data-post="ctrlua/100">'
        '<div class="tgme_widget_message_video"><video src="https://cdn.telegram.org/a.mp4"></video></div>'
        '</div>'
        '<div class="tgme_widget_message" data-post="ctrlua/101">'
        '<div class="tgme_widget_message_video"><video src="https://cdn.telegram.org/b.mp4"></video></div>'
        '</div>'
    )
    fragment = _exact_public_post_fragment(html, "ctrlua", "100")
    assert "a.mp4" in fragment
    assert "b.mp4" not in fragment
    media = extract_telegram_post_media(fragment, "https://t.me/s/ctrlua/100", "CTRL+UA")
    assert [item.url for item in media] == ["https://cdn.telegram.org/a.mp4"]


def test_rc60_telegram_falls_back_to_scoped_public_post(monkeypatch) -> None:
    import content_agent.telegram_media_v1_3_rc6 as telegram_media

    calls: list[str] = []

    def fake_fetch(url: str, **kwargs):
        calls.append(url)
        if "?embed=1" in url:
            html = b"<html><body>embed without media</body></html>"
        else:
            html = (
                b'<div class="tgme_widget_message" data-post="ctrlua/100">'
                b'<div class="tgme_widget_message_video">'
                b'<video src="https://cdn.telegram.org/live.mp4"></video>'
                b'</div></div>'
                b'<div class="tgme_widget_message" data-post="ctrlua/101">'
                b'<div class="tgme_widget_message_video">'
                b'<video src="https://cdn.telegram.org/wrong.mp4"></video>'
                b'</div></div>'
            )
        return HttpResponse(200, {"content-type": "text/html"}, html, url)

    monkeypatch.setattr(telegram_media, "fetch_url", fake_fetch)
    monkeypatch.setattr(telegram_media.time, "sleep", lambda _seconds: None)
    result = discover_telegram_post_media("https://t.me/ctrlua/100", "CTRL+UA")
    assert [item.url for item in result] == ["https://cdn.telegram.org/live.mp4"]
    assert any("/s/ctrlua/100" in url for url in calls)
