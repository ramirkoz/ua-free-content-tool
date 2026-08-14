from __future__ import annotations

from .ai_engine_v1_3 import AIEngineV13Mixin
from .queue_migration_codex_v1_3 import CodexQueueMigrationDialog
from .v1_2_rc4_final_window import MainWindow as RC4FinalWindow
from . import main_window as legacy_ui


class MainWindow(AIEngineV13Mixin, RC4FinalWindow):
    def __init__(self, *args: object, **kwargs: object) -> None:
        legacy_ui.QueueMigrationDialog = CodexQueueMigrationDialog
        super().__init__(*args, **kwargs)
        self.root.title("UA FREE Content Tool — v1.2.0-dev RC5 · Codex + Rowboat")

    def scan_ollama_models(self, show_errors: bool = True) -> None:
        del show_errors
        return
