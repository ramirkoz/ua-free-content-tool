from __future__ import annotations

import inspect
from pathlib import Path

from content_agent.v2.ui.manual_topics_window_rc44 import MainWindow


def test_rc55_version_files_are_final_candidate() -> None:
    root = Path(__file__).parents[1]
    assert (root / "VERSION.txt").read_text(encoding="utf-8").strip() == "2.0.0-rc55"
    assert (root / "PUBLIC_VERSION.txt").read_text(encoding="utf-8").strip() == "2.0.0-rc55"


def test_rc55_inbox_contract_has_only_operator_columns() -> None:
    assert MainWindow.INBOX_DISPLAY_COLUMNS == ("title", "topic", "sources", "published")
    source = inspect.getsource(MainWindow)
    assert 'tree.configure(displaycolumns=self.INBOX_DISPLAY_COLUMNS)' in source
    assert 'tree.heading("title", text="Подія")' in source
    assert 'tree.heading("topic", text="Тема")' in source
    assert 'tree.heading("sources", text="Джерел")' in source
    assert 'tree.heading("published", text="Час")' in source


def test_rc55_legacy_search_and_column_reset_are_removed_but_block_composition_stays() -> None:
    source = inspect.getsource(MainWindow)
    assert '"Пошук у Вхідних:"' in source
    assert '"Знайти"' in source
    assert '"Колонки"' in source
    assert "widget.destroy()" in source
    assert "def reset_inbox_columns" in source
    assert "self._enforce_rc55_inbox_columns()" in source
    legacy = (Path(__file__).parents[1] / "content_agent" / "v2" / "ui" / "legacy_manual_topics_window_rc44.py").read_text(encoding="utf-8")
    assert "show_group_composition" in legacy
    assert "Склад блоку" in legacy


def test_rc55_does_not_add_numbered_window_layer() -> None:
    ui = Path(__file__).parents[1] / "content_agent" / "v2" / "ui"
    assert not list(ui.rglob("*rc55*window*.py"))
    assert not list(ui.rglob("*window*rc55*.py"))
