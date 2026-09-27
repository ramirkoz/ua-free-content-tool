from __future__ import annotations

import time
from typing import Any

from .google_drive import inspect_google_drive_connection

_INSTALLED = False


def _is_true_drive_auth_error(exc: BaseException) -> bool:
    """Return True only for errors that really require OAuth re-authorization.

    A generic HTTP 403 from Drive is not proof that OAuth is dead. It can mean a
    file permission, policy or quota problem and must not poison publication until
    the operator presses the Sign in button again.
    """
    text = str(exc).casefold()
    return any(
        token in text
        for token in (
            "token has been expired or revoked",
            "invalid_grant",
            "unauthorized_client",
            "refresh token",
            "oauth2",
            "http 401",
        )
    )


def install_drive_auth_recovery() -> None:
    """Make a blocked Drive publication session self-heal when refresh still works."""
    global _INSTALLED
    if _INSTALLED:
        return

    from .worker import PublicationWorker

    previous_reason = PublicationWorker.auth_block_reason

    def auth_block_reason(self: Any, platform: str) -> str:
        reason = previous_reason(self, platform)
        if platform != "google_drive" or not reason:
            return reason

        # A previous request may have misclassified a temporary Drive failure as
        # OAuth loss. Before forcing a human browser login, prove that the stored
        # refresh token is actually dead. Limit probes to one per minute.
        now = time.monotonic()
        last = float(getattr(self, "_drive_auth_recovery_last_check", 0.0) or 0.0)
        if now - last < 60.0:
            return reason
        self._drive_auth_recovery_last_check = now

        config = self.factory.config
        try:
            inspect_google_drive_connection(
                str(config.google_client_id or ""),
                str(config.google_client_secret or ""),
                str(config.google_refresh_token or ""),
            )
        except Exception:
            return reason

        self.clear_auth_blocks("google_drive")
        return ""

    PublicationWorker._is_drive_auth_error = staticmethod(_is_true_drive_auth_error)
    PublicationWorker.auth_block_reason = auth_block_reason
    _INSTALLED = True
