from __future__ import annotations

from pathlib import Path

from .reliable import Database


def create_database(path: Path | None = None) -> Database:
    """Create the single active Content Tool database composition.

    Keep all runtime entry points, restore flows and tests on the same V2 reliable
    composition instead of silently falling back to the legacy base Database.
    """
    return Database(path) if path is not None else Database()


__all__ = ["create_database"]
