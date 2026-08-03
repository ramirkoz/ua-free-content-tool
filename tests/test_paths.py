from __future__ import annotations

from pathlib import Path

from content_agent.paths import data_dir, database_path


def test_single_stable_data_directory(isolated_data: Path) -> None:
    assert data_dir() == isolated_data
    assert database_path() == isolated_data / "content_agent.sqlite3"
    assert not any("migration" in item.name.lower() for item in isolated_data.iterdir())
