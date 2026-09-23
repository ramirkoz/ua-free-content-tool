from __future__ import annotations

import threading

from ..codex_runtime import inspect_codex, install_codex, login_chatgpt
from ..rowboat_bridge_v1_3 import inspect_rowboat, install_rowboat
from .ai_engine_v1_3 import AIEngineV13Mixin
from .queue_migration_codex_v1_3 import CodexQueueMigrationDialog
from .v1_2_rc4_final_window import MainWindow as RC4FinalWindow
from . import main_window as legacy_ui


class MainWindow(AIEngineV13Mixin, RC4FinalWindow):
    def __init__(self, *args: object, **kwargs: object) -> None:
        self._ai_status_running = False
        legacy_ui.QueueMigrationDialog = CodexQueueMigrationDialog
        super().__init__(*args, **kwargs)
        if hasattr(self, "rewrite_button"):
            self.rewrite_button.configure(text="Рерайт через Codex / ChatGPT")
        self.root.title("UA FREE Content Tool — v1.3.1-rc7")

    def scan_ollama_models(self, show_errors: bool = True) -> None:
        del show_errors
        return

    def refresh_ai_component_status(self) -> None:
        return AIEngineV13Mixin.refresh_ai_component_status(self)

    def check_codex_ui(self) -> None:
        return AIEngineV13Mixin.check_codex_ui(self)

    def install_codex_ui(self) -> None:
        return AIEngineV13Mixin.install_codex_ui(self)

    def login_codex_ui(self) -> None:
        return AIEngineV13Mixin.login_codex_ui(self)

    def check_rowboat_ui(self) -> None:
        status = inspect_rowboat()
        self.refresh_ai_component_status()
        if status.installed:
            self.set_status(f"Rowboat знайдено: {status.executable}")
            return
        install_now = self.msg.askyesno(
            "Rowboat не знайдено",
            "Rowboat не встановлено. Встановити останню офіційну Windows x64 версію з GitHub Releases?\n\n"
            "UA FREE створить окремий Rowboat WorkDir і локальний Markdown-граф редакційної пам’яті.",
            parent=self.root,
        )
        if install_now:
            self.install_rowboat_ui()

    def install_rowboat_ui(self) -> None:
        def success(result: object) -> None:
            self.refresh_ai_component_status()
            self.set_status(f"Rowboat встановлено: {result}")

        self.run_async(
            install_rowboat,
            success,
            label="Завантажую та встановлюю Rowboat",
            done_label="Rowboat встановлено",
        )
