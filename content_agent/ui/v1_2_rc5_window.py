from __future__ import annotations

import threading

from ..codex_engine_v1_3 import inspect_codex
from ..rowboat_bridge_v1_3 import inspect_rowboat
from .ai_engine_v1_3 import AIEngineV13Mixin
from .queue_migration_codex_v1_3 import CodexQueueMigrationDialog
from .v1_2_rc4_final_window import MainWindow as RC4FinalWindow
from . import main_window as legacy_ui


class MainWindow(AIEngineV13Mixin, RC4FinalWindow):
    def __init__(self, *args: object, **kwargs: object) -> None:
        self._ai_status_running = False
        legacy_ui.QueueMigrationDialog = CodexQueueMigrationDialog
        super().__init__(*args, **kwargs)
        self.root.title("UA FREE Content Tool — v1.2.0-dev RC5 · Codex + Rowboat")

    def scan_ollama_models(self, show_errors: bool = True) -> None:
        del show_errors
        return

    def refresh_ai_component_status(self) -> None:
        if self._ai_status_running or not hasattr(self, "codex_status_var"):
            return
        self._ai_status_running = True

        def worker() -> None:
            codex = inspect_codex()
            rowboat = inspect_rowboat()

            def apply() -> None:
                self._ai_status_running = False
                if not codex.installed:
                    self.codex_status_var.set("Codex: не встановлено")
                elif codex.authenticated:
                    suffix = f" · {codex.account_label}" if codex.account_label else ""
                    self.codex_status_var.set(f"Codex {codex.version}: готовий{suffix}")
                else:
                    self.codex_status_var.set(f"Codex {codex.version}: потрібен вхід через ChatGPT")
                self.rowboat_status_var.set(
                    f"Rowboat: знайдено · {rowboat.executable}" if rowboat.installed else "Rowboat: не знайдено"
                )
                self.memory_graph_status_var.set(f"Пам’ять: {rowboat.memory_root}")

            try:
                self.root.after(0, apply)
            except Exception:
                self._ai_status_running = False

        threading.Thread(target=worker, name="ai-component-status", daemon=True).start()
