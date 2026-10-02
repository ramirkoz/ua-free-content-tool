from content_agent.v2.ui.manual_topics_window_rc44 import MainWindow


def test_rc58_restores_launch_hooks_lost_during_branch_composition() -> None:
    assert callable(getattr(MainWindow, "_rename_system_tab", None))
    assert callable(getattr(MainWindow, "_apply_rc54_publication_layout", None))
