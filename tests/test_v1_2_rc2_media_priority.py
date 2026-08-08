from __future__ import annotations

from content_agent.media_candidates import MediaCandidate
from content_agent.media_priority_v1_2 import prioritize_media_candidates
from content_agent.ui.v1_2_rc2_window import MainWindow


def test_video_from_same_source_precedes_high_score_poster() -> None:
    poster = MediaCandidate(
        url="https://cdn.example/poster.jpg",
        kind="image",
        source_label="Telegram source",
        origin="og:image",
        score=100,
    )
    video = MediaCandidate(
        url="https://cdn.example/video.mp4",
        kind="video",
        source_label="Telegram source",
        origin="telegram:data-video",
        score=82,
    )

    ordered = prioritize_media_candidates([poster, video])
    assert ordered[0] is video
    assert ordered[1] is poster


def test_stale_poster_replacement_prefers_fresh_video_from_same_source() -> None:
    stale = MediaCandidate(
        url="https://cdn4.telesco.pe/expired.jpg",
        kind="image",
        source_label="Channel A",
        origin="html:background-image",
        score=90,
    )
    other_image = MediaCandidate(
        url="https://example.com/other.jpg",
        kind="image",
        source_label="Other source",
        origin="og:image",
        score=100,
    )
    fresh_video = MediaCandidate(
        url="https://cdn4.telesco.pe/fresh.mp4",
        kind="video",
        source_label="Channel A",
        origin="html:video:src",
        score=70,
    )

    replacement = MainWindow._replacement_candidate(
        stale,
        prioritize_media_candidates([other_image, fresh_video]),
    )
    assert replacement is fresh_video
