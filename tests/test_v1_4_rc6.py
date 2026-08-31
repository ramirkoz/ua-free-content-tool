from __future__ import annotations

import inspect

from content_agent.ui.global_duplicates_dialog_v1_3_rc6 import (
    DEFAULT_AUTO_SELECT_CONFIDENCE,
    HIGH_CONFIDENCE,
    GlobalDuplicatesDialog,
    confidence_visual_class,
    default_cluster_selected,
)
from content_agent.ui.v1_4_rc6_window import MainWindow


def test_rc6_confidence_colour_is_independent_from_auto_selection() -> None:
    assert HIGH_CONFIDENCE == 80
    assert DEFAULT_AUTO_SELECT_CONFIDENCE == 90
    assert confidence_visual_class(79) == "possible"
    assert confidence_visual_class(80) == "strong"
    assert confidence_visual_class(86) == "strong"
    assert confidence_visual_class(89) == "strong"
    assert confidence_visual_class(90) == "strong"
    assert default_cluster_selected(86) is False
    assert default_cluster_selected(89) is False
    assert default_cluster_selected(90) is True


def test_rc6_duplicate_footer_has_reserved_grid_row() -> None:
    source = inspect.getsource(GlobalDuplicatesDialog.__init__)
    assert "self.rowconfigure(1, weight=1)" in source
    assert 'table.grid(row=1, column=0, sticky="nsew"' in source
    assert 'actions.grid(row=2, column=0, sticky="ew")' in source
    assert 'actions.pack(fill="x")' not in source


def test_rc6_maximized_dialog_keeps_manual_columns_non_stretching() -> None:
    source = inspect.getsource(GlobalDuplicatesDialog.__init__)
    assert 'self.tree.column("cluster"' in source
    assert 'self.tree.column("reason"' in source
    assert 'stretch=True' not in source
    assert 'orient="horizontal"' in source


def test_rc6_version_label() -> None:
    assert MainWindow.VERSION_LABEL == "1.4.0-rc6"
