from __future__ import annotations

from pathlib import Path

from .reliable import Database
from .restore_pending import apply_pending_restore, has_pending_restore


def create_database(path: Path | None = None) -> Database:
    """Create the single active Content Tool database composition.

    For the live default Data path, a staged restore is applied before any active
    Database object is constructed. Explicit test/fixture paths never consume the
    operator's pending restore marker.
    """
    if path is None and has_pending_restore():
        apply_pending_restore()
    return Database(path) if path is not None else Database()


__all__ = ["create_database"]
