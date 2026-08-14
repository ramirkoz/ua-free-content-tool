from __future__ import annotations

from .v1_2_rc6_window import MainWindow as RC7Window


class MainWindow(RC7Window):
    """RC8 live-gate build: LinkedIn isolation plus correct Codex UI wording."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._ensure_codex_rewrite_label()
        self.root.title("UA FREE Content Tool — v1.2.0-dev RC8 · Codex + Rowboat")

    def _apply_language(self, refresh: bool = True) -> None:
        super()._apply_language(refresh=refresh)
        self._ensure_codex_rewrite_label()

    def _ensure_codex_rewrite_label(self) -> None:
        button = getattr(self, "rewrite_button", None)
        if button is not None:
            button.configure(text="Рерайт через Codex / ChatGPT")
