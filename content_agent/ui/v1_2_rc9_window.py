from __future__ import annotations

from .v1_2_rc8_window import MainWindow as RC8Window


class MainWindow(RC8Window):
    """v1.2.1 RC2 window with automatic multi-provider AI Router."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._ensure_codex_rewrite_label()
        self.root.title("UA FREE Content Tool — v1.2.1 RC2 · AI Router + Rowboat")

    def _ensure_codex_rewrite_label(self) -> None:
        button = getattr(self, "rewrite_button", None)
        if button is not None:
            button.configure(text="Рерайт через AI Router")
