from __future__ import annotations

from types import SimpleNamespace

from content_agent.ui.v1_4_rc12_window import MainWindow, _SOURCE_COLUMNS


class _FakeTree:
    def __init__(self, columns: tuple[str, ...]) -> None:
        self.columns = columns
        self.labels: dict[str, str] = {}

    def cget(self, name: str):
        assert name == "columns"
        return self.columns

    def heading(self, column: str, **kwargs):
        if column not in self.columns:
            raise RuntimeError(f"invalid column {column}")
        if "text" in kwargs:
            self.labels[column] = str(kwargs["text"])


class _FakeRoot:
    def __init__(self) -> None:
        self.value = ""

    def title(self, value: str) -> None:
        self.value = value


def test_rc12_source_schema_restores_health_columns() -> None:
    assert _SOURCE_COLUMNS == (
        "id", "kind", "name", "health", "yield", "last_new", "errors", "checked", "url"
    )


def test_source_health_label_refresh_is_defensive_for_partial_tree() -> None:
    window = object.__new__(MainWindow)
    window.config = SimpleNamespace(ui_language="uk")
    window.sources_tree = _FakeTree(("id", "kind", "name", "checked", "url"))

    # This is the exact lifecycle mismatch that used to raise
    # `Invalid column index health` during localization.
    window._apply_source_health_labels_rc12()

    assert window.sources_tree.labels["id"] == "ID"
    assert "health" not in window.sources_tree.labels


def test_current_window_title_cannot_fall_back_to_rc7() -> None:
    window = object.__new__(MainWindow)
    window.root = _FakeRoot()
    window._apply_v14_labels()
    assert window.root.value == "UA FREE Content Tool — v1.4.0-rc12"
