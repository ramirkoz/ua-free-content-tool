from __future__ import annotations

from pathlib import Path

from content_agent import media_candidates
from content_agent.media_candidates import MediaCandidate, download_media_candidate
from content_agent.network import HttpResponse, NetworkError
from content_agent.telegram_media_v1_3_rc6 import discover_telegram_post_media
from content_agent.v2.media_rc56 import Rc56ManagedGoogleDriveClient


ROOT = Path(__file__).resolve().parents[1]


def test_rc59_readable_media_filename_survives_rc56_client() -> None:
    client = Rc56ManagedGoogleDriveClient(
        "client",
        "secret",
        "refresh",
        post_title="Нова модель робота Figure працює на заводі",
        group_id=77,
    )
    name = client._publication_filename("video/mp4")
    assert "Нова модель робота Figure працює на заводі" in name
    assert "post-77" in name
    assert name.endswith(".mp4")


def test_rc59_media_download_retries_transient_read_failure(monkeypatch) -> None:
    calls: list[str] = []

    def fake_fetch(url: str, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            raise NetworkError("temporary CDN miss")
        return HttpResponse(
            200,
            {"content-type": "image/jpeg"},
            b"\xff\xd8\xff" + b"x" * 32,
            url,
        )

    monkeypatch.setattr(media_candidates, "fetch_url", fake_fetch)
    monkeypatch.setattr(media_candidates.time, "sleep", lambda _seconds: None)
    candidate = MediaCandidate(
        url="https://example.com/preview.jpg",
        kind="image",
        source_label="test",
        origin="og:image",
    )
    result = download_media_candidate(candidate)
    assert result.kind == "image"
    assert len(calls) == 2


def test_rc59_telegram_exact_post_retries_empty_embed(monkeypatch) -> None:
    import content_agent.telegram_media_v1_3_rc6 as telegram_media

    calls = 0

    def fake_fetch(url: str, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            html = b"<html><body>temporary empty embed</body></html>"
        else:
            html = (
                b'<div class="tgme_widget_message_video">'
                b'<video src="https://cdn.telegram.org/media/test.mp4"></video>'
                b"</div>"
            )
        return HttpResponse(200, {"content-type": "text/html"}, html, url)

    monkeypatch.setattr(telegram_media, "fetch_url", fake_fetch)
    monkeypatch.setattr(telegram_media.time, "sleep", lambda _seconds: None)
    found = discover_telegram_post_media("https://t.me/example/123", "example")
    assert calls == 2
    assert len(found) == 1
    assert found[0].kind == "video"


def test_rc59_media_progress_stays_visible_and_is_reference_counted() -> None:
    src = (ROOT / "content_agent" / "v2" / "ui" / "manual_topics_window_rc44.py").read_text(encoding="utf-8")
    assert "progress.grid_remove()" not in src
    assert "_rc59_media_busy_count" in src
    assert "def _begin_media_busy" in src
    assert "def _finish_media_busy" in src
    assert "if count == 1:" in src
    assert "if count == 0:" in src
    assert "progress.start(12)" in src
    assert "progress.stop()" in src


def test_rc59_ui_passes_publication_context_to_drive_client() -> None:
    src = (ROOT / "content_agent" / "v2" / "ui" / "manual_topics_window_rc44.py").read_text(encoding="utf-8")
    assert "post_title=self._current_media_title()" in src
    assert 'group_id=int(getattr(self, "current_group_id", 0) or 0)' in src
