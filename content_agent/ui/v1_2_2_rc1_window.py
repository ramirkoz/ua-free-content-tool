from __future__ import annotations

from .v1_2_rc10_window import MainWindow as V121Window


class MainWindow(V121Window):
    """v1.2.2 RC5 window with resilient duplicate search and Ollama-first local fallback."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.root.title("UA FREE Content Tool — v1.2.2 RC5 · resilient duplicates + Ollama fallback + AI Router + Rowboat")
