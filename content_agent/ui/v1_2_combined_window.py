from __future__ import annotations

from .media_workflow import MediaWorkflowMixin
from .v1_2_window import MainWindow as EditorialMemoryMainWindow


class MainWindow(MediaWorkflowMixin, EditorialMemoryMainWindow):
    """Combined v1.2 window: clear editorial memory plus automatic media workflow."""

    pass
