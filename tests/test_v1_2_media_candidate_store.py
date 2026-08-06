from __future__ import annotations

from pathlib import Path

import pytest

from content_agent.media_candidate_store import MediaCandidateStore, MediaCandidateStoreError
from content_agent.media_candidates import MediaCandidate


def test_store_round_trips_and_deduplicates(tmp_path: Path) -> None:
    store = MediaCandidateStore(tmp_path / "media.json")
    weak = MediaCandidate("https://x/a.jpg", "image", "One", "img", score=10)
    strong = MediaCandidate("https://x/a.jpg", "image", "One", "og:image", score=100)
    video = MediaCandidate("https://x/v.mp4", "video", "One", "og:video", score=90)
    assert store.save_group(42, [weak, strong, video]) == 2
    restored = store.list_group(42)
    assert [item.url for item in restored] == ["https://x/a.jpg", "https://x/v.mp4"]
    assert restored[0].origin == "og:image"


def test_store_clear_group_preserves_other_groups(tmp_path: Path) -> None:
    store = MediaCandidateStore(tmp_path / "media.json")
    one = MediaCandidate("https://x/1.jpg", "image", "One", "og:image")
    two = MediaCandidate("https://x/2.jpg", "image", "Two", "og:image")
    store.save_group(1, [one])
    store.save_group(2, [two])
    store.clear_group(1)
    assert store.list_group(1) == []
    assert store.list_group(2) == [two]


def test_store_fails_closed_on_corruption(tmp_path: Path) -> None:
    path = tmp_path / "media.json"
    path.write_text("not-json", encoding="utf-8")
    store = MediaCandidateStore(path)
    with pytest.raises(MediaCandidateStoreError, match="пошкоджене"):
        store.list_group(1)
