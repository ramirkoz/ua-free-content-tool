from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from content_agent.paths import reset_path_cache_for_tests


@pytest.fixture(autouse=True)
def _fresh_manual_drive_tokens(monkeypatch: pytest.MonkeyPatch):
    """Keep tests that inject a private Drive access token independent of runner uptime.

    Production GoogleDriveClient refreshes tokens after 45 minutes using monotonic
    time. Older tests set only ``_access_token='access'`` and left its timestamp at
    zero, so they passed or failed depending on whether the CI VM itself had been up
    for 45 minutes. Explicitly dated token-expiry tests remain untouched because this
    shim only fills the zero/unset timestamp used by those manual fixtures.
    """
    from content_agent.google_drive import GoogleDriveClient

    original = GoogleDriveClient._token

    def deterministic_token(self, *, force_refresh: bool = False):
        if getattr(self, "_access_token", "") and float(getattr(self, "_access_token_at", 0.0) or 0.0) <= 0.0:
            self._access_token_at = time.monotonic()
        return original(self, force_refresh=force_refresh)

    monkeypatch.setattr(GoogleDriveClient, "_token", deterministic_token)
    yield


@pytest.fixture
def isolated_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data = tmp_path / "data"
    monkeypatch.setenv("UA_FREE_CONTENT_DATA", str(data))
    monkeypatch.setenv("UA_FREE_TEST_PLAINTEXT_CONFIG", "1")
    reset_path_cache_for_tests()
    yield data
    reset_path_cache_for_tests()
