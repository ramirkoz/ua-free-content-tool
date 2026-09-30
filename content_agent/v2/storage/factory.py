from __future__ import annotations

import os
from pathlib import Path

from .reliable import Database
from .restore_pending import (
    apply_pending_restore,
    has_pending_restore,
    pending_restore_requires_password,
)

_RESTORE_PASSWORD_ENV = "UA_FREE_RESTORE_PASSWORD"


def create_database(path: Path | None = None) -> Database:
    """Create the single active Content Tool database composition.

    For the live default Data path, a staged restore is applied before any active
    Database object is constructed. Explicit test/fixture paths never consume the
    operator's pending restore marker.
    """
    if path is None and has_pending_restore():
        password = os.environ.pop(_RESTORE_PASSWORD_ENV, None)
        if pending_restore_requires_password() and not password:
            raise RuntimeError(
                "Є відкладене відновлення migration backup, але пароль не передано. "
                "Повторіть імпорт із запущеної програми."
            )
        apply_pending_restore(credential_password=password)
    return Database(path) if path is not None else Database()


__all__ = ["create_database"]
