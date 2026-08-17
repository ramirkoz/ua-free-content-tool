from __future__ import annotations

from .v1_2_rc10_window import MainWindow as V121Window


class MainWindow(V121Window):
    """v1.2.2 RC1 window; behavior is inherited from the stable v1.2.1 UI."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.root.title("UA FREE Content Tool — v1.2.2 RC1 · AI Router + Rowboat")
