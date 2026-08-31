from __future__ import annotations

import inspect

from content_agent.ui.global_duplicates_dialog_v1_3_rc6 import GlobalDuplicatesDialog
from content_agent.ui.v1_4_rc5_window import MainWindow


def test_rc5_duplicate_columns_do_not_auto_stretch_or_snap_back() -> None:
    source = inspect.getsource(GlobalDuplicatesDialog.__init__)
    assert 'self.tree.column("cluster"' in source
    assert 'self.tree.column("reason"' in source
    assert 'stretch=True' not in source
    assert 'orient="horizontal"' in source
    assert 'command=self.tree.xview' in source
    assert 'xscrollcommand=self.tree_x_scroll.set' in source


def test_rc5_transient_checkbox_changes_do_not_overwrite_last_used_targets() -> None:
    source = inspect.getsource(MainWindow._persist_live_target_selection)
    assert "_remember_last_target_selection" not in source
    assert "self._last_targets_save_after_id = None" in source


def test_rc5_actual_approval_still_persists_the_selection() -> None:
    source = inspect.getsource(MainWindow.approve_current)
    assert "_remember_last_target_selection" in source
    assert "selected" in source


def test_rc5_preset_apply_still_persists_the_selected_set() -> None:
    source = inspect.getsource(MainWindow.apply_selected_target_preset)
    assert "_remember_last_target_selection" in source
    assert "_apply_target_keys" in source


def test_rc5_version_label() -> None:
    assert MainWindow.VERSION_LABEL == "1.4.0-rc5"
