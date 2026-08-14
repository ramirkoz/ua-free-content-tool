from __future__ import annotations

from .ai_engine_v1_3 import AIEngineV13Mixin
from .v1_2_rc4_final_window import MainWindow as RC4FinalWindow


class MainWindow(AIEngineV13Mixin, RC4FinalWindow):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.root.title("UA FREE Content Tool — v1.2.0-dev RC5 · Codex + Rowboat")
