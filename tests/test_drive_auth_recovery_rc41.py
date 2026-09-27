from __future__ import annotations

from unittest.mock import patch

from content_agent.drive_auth_recovery import _is_true_drive_auth_error
from content_agent.worker import PublicationWorker


def test_drive_auth_classifier_does_not_treat_generic_403_as_reauth() -> None:
    assert _is_true_drive_auth_error(RuntimeError("HTTP 401 unauthorized"))
    assert _is_true_drive_auth_error(RuntimeError("invalid_grant"))
    assert not _is_true_drive_auth_error(RuntimeError("HTTP 403 permission denied"))
    assert PublicationWorker._is_drive_auth_error(RuntimeError("HTTP 401 unauthorized"))
    assert not PublicationWorker._is_drive_auth_error(RuntimeError("HTTP 403 permission denied"))


def test_blocked_drive_session_self_heals_when_refresh_token_is_valid() -> None:
    worker = object.__new__(PublicationWorker)
    worker._auth_blocks = {"google_drive": "Google Drive / медіа: HTTP 403"}
    worker._auth_block_lock = __import__("threading").Lock()
    worker.factory = type("Factory", (), {"config": type("Config", (), {
        "google_client_id": "cid",
        "google_client_secret": "secret",
        "google_refresh_token": "refresh",
    })()})()

    with patch("content_agent.drive_auth_recovery.inspect_google_drive_connection") as inspect:
        assert worker.auth_block_reason("google_drive") == ""
        inspect.assert_called_once_with("cid", "secret", "refresh")
    assert worker.auth_block_reason("google_drive") == ""
