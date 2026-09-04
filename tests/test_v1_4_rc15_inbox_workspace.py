from __future__ import annotations

from pathlib import Path

from content_agent.database_v1_4_rc15 import Database
from content_agent.models import CollectedArticle
from content_agent.ui.inbox_management_v1_4_rc15 import safe_workspace_geometry
from content_agent.ui.v1_4_rc15_window import ALL_SOURCES_LABEL, visible_group_ids_for_source


def _add(db: Database, source_id: int, *, external_id: str, title: str) -> int:
    assert db.insert_collected(
        source_id,
        [
            CollectedArticle(
                external_id=external_id,
                title=title,
                url=f"https://example.test/{external_id}",
                raw_text=f"Текст {title}",
                published_at="2026-09-04T09:00:00+03:00",
            )
        ],
        enforce_today=False,
    ) == 1
    return next(group.id for group in db.list_groups(limit=None) if group.canonical_title == title)


def test_source_lookup_keeps_every_source_inside_merged_group(tmp_path: Path) -> None:
    db = Database(tmp_path / "content.sqlite3")
    first_source = db.add_source("url", "Alpha News", "https://alpha.test/")
    second_source = db.add_source("url", "Beta Media", "https://beta.test/")
    target_id = _add(db, first_source, external_id="alpha", title="Спільна подія")
    second_id = _add(db, second_source, external_id="beta", title="Друга згадка")
    db.merge_groups(target_id, [target_id, second_id])

    mapping = db.source_names_for_group_ids([target_id])
    assert set(mapping[target_id]) == {"Alpha News", "Beta Media"}


def test_source_filter_matches_merged_group_when_any_member_source_matches() -> None:
    mapping = {
        10: ("Alpha News", "Beta Media"),
        11: ("Gamma",),
    }
    assert visible_group_ids_for_source([10, 11], mapping, "Beta Media") == [10]
    assert visible_group_ids_for_source([10, 11], mapping, ALL_SOURCES_LABEL) == [10, 11]


def test_workspace_geometry_is_near_fullscreen_but_taskbar_safe() -> None:
    width, height, x, y = safe_workspace_geometry(1920, 1080)
    assert (x, y) == (0, 0)
    assert width == 1908
    assert height == 984
