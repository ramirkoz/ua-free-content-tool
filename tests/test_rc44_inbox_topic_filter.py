from __future__ import annotations

import inspect

from content_agent.main import MainWindow
from content_agent.v2.ui.components import FilterBar
from content_agent.v2.ui.manual_topics_window_rc44 import MainWindow as Rc44MainWindow


def test_active_entrypoint_uses_rc44_window():
    assert MainWindow is Rc44MainWindow


def test_rc44_topic_filter_has_its_own_visible_row():
    # RC53 keeps the RC44 contract but moves widget construction into the shared
    # FilterBar. Verify the active shell still installs one full-width authoritative
    # row rather than requiring label literals to remain inside this method body.
    source = inspect.getsource(Rc44MainWindow._install_manual_topic_inbox_filters)
    component = inspect.getsource(FilterBar.__init__)
    assert "_rc14_inbox_tools_frame" not in source
    assert "tree_frame = tree.master" in source
    assert "tab = tree_frame.master" in source
    assert 'bar.pack(fill="x", pady=(0, 6), before=tree_frame)' in source
    assert 'text="Джерело:"' in component
    assert 'text="Тема:"' in component
    assert "inbox_source_filter_box" in source
    assert "inbox_topic_filter_box" in source
    assert "reset_manual_topic_filters" in source


def test_rc44_keeps_rc43_filter_logic_and_manual_topic_source_of_truth():
    assert hasattr(Rc44MainWindow, "_active_inbox_source_id")
    assert hasattr(Rc44MainWindow, "_active_inbox_topic_id")
    assert hasattr(Rc44MainWindow, "refresh_groups")
    assert hasattr(Rc44MainWindow, "_refresh_inbox_filter_choices")
