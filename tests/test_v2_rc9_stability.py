from __future__ import annotations

import pytest

from content_agent.paths import DATA_ENV, reset_path_cache_for_tests
from content_agent.v2.storage.compat import Database as CompatDatabase
from content_agent.v2.storage.reliable import Database as ReliableDatabase
from content_agent.v2.supervisor.resilient_runtime import ResilientSupervisorRuntime


def _use_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv(DATA_ENV, str(tmp_path))
    reset_path_cache_for_tests()


def test_external_success_receipt_survives_local_commit_failure(monkeypatch, tmp_path) -> None:
    _use_data_dir(monkeypatch, tmp_path)
    database = ReliableDatabase()

    def fail_sent(self, target_id, remote_id):
        raise OSError("database is locked")

    monkeypatch.setattr(CompatDatabase, "mark_target_sent", fail_sent)

    with pytest.raises(OSError):
        database.mark_target_sent(77, "remote-77")

    receipt = ReliableDatabase._receipt_path(77)
    assert receipt.exists()
    assert 77 in database._uncertain_external_targets

    failed_calls: list[int] = []
    monkeypatch.setattr(
        CompatDatabase,
        "mark_target_failed",
        lambda self, target_id, error: failed_calls.append(int(target_id)),
    )
    database.mark_target_failed(77, "later worker error")

    assert failed_calls == []
    assert receipt.exists()


def test_external_success_receipt_reconciles_before_retry(monkeypatch, tmp_path) -> None:
    _use_data_dir(monkeypatch, tmp_path)
    database = ReliableDatabase()
    database._write_receipt(81, "remote-81")

    committed: list[tuple[int, str | None]] = []
    monkeypatch.setattr(
        CompatDatabase,
        "mark_target_sent",
        lambda self, target_id, remote_id: committed.append((int(target_id), remote_id)),
    )

    assert database.reconcile_external_successes() == 1
    assert committed == [(81, "remote-81")]
    assert not ReliableDatabase._receipt_path(81).exists()


def test_drive_auth_errors_receive_long_backoff_classification() -> None:
    assert ResilientSupervisorRuntime._is_drive_auth_error(RuntimeError("Google Drive API HTTP 401"))
    assert ResilientSupervisorRuntime._is_drive_auth_error(RuntimeError("invalid_grant refresh token"))
    assert not ResilientSupervisorRuntime._is_drive_auth_error(RuntimeError("temporary network timeout"))


def teardown_module() -> None:
    reset_path_cache_for_tests()
