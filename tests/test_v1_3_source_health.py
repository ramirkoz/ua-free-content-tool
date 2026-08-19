from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from content_agent.source_health import (
    record_source_error,
    record_source_success,
    source_health_map,
)


class TinyDatabase:
    def __init__(self, path):
        self.path = path

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        finally:
            db.close()


def test_source_health_is_additive_and_accumulates_yield_and_errors(tmp_path) -> None:
    path = tmp_path / "health.sqlite3"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE sources(id INTEGER PRIMARY KEY)")
    db.execute("INSERT INTO sources(id) VALUES(1)")
    db.commit()
    db.close()

    database = TinyDatabase(path)
    record_source_success(database, 1, 3)
    record_source_success(database, 1, 0)
    record_source_error(database, 1, "network timeout")

    health = source_health_map(database)[1]
    assert health.total_checks == 3
    assert health.total_inserted == 3
    assert health.total_errors == 1
    assert health.last_inserted_count == 0
    assert health.state.startswith("🔴")
