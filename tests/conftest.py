from __future__ import annotations

import os
from pathlib import Path

import pytest

from content_agent.paths import reset_path_cache_for_tests


@pytest.fixture
def isolated_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data = tmp_path / "data"
    monkeypatch.setenv("UA_FREE_CONTENT_DATA", str(data))
    monkeypatch.setenv("UA_FREE_TEST_PLAINTEXT_CONFIG", "1")
    reset_path_cache_for_tests()
    yield data
    reset_path_cache_for_tests()
