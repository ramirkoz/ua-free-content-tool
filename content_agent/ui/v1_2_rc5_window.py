from __future__ import annotations

import threading

from ..codex_engine_v1_3 import inspect_codex, install_codex, login_chatgpt
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

    def check_codex_ui(self) -> None:
        status = inspect_codex()
        if not status.installed:
            install_now = self.msg.askyesno(
                "Codex не встановлено",
                "Codex не знайдено у локальному AI-runtime. Встановити офіційний openai-codex зараз?",
                parent=self.root,
            )
            if install_now:
                self.install_codex_ui()
            return
        if not status.authenticated:
            login_now = self.msg.askyesno(
                "Потрібен вхід через ChatGPT",
                "Codex встановлено, але не авторизовано. Відкрити вхід через ChatGPT зараз?",
                parent=self.root,
            )
            if login_now:
                self.login_codex_ui()
            return
        self.refresh_ai_component_status()
        self.set_status(f"Codex готовий: {status.account_label or 'ChatGPT account'}")

    def install_codex_ui(self) -> None:
        def success(_result: object) -> None:
            self.refresh_ai_component_status()
            self.set_status("Codex встановлено. Потрібен вхід через ChatGPT.")
            login_now = self.msg.askyesno(
                "Codex встановлено",
                "Встановлення завершено. Увійти через ChatGPT зараз?",
                parent=self.root,
            )
            if login_now:
                self.login_codex_ui()

        self.run_async(
            install_codex,
            success,
            label="Встановлюю Codex у локальний AI-runtime",
            done_label="Codex встановлено",
        )

    def login_codex_ui(self) -> None:
        def success(_result: object) -> None:
            self.refresh_ai_component_status()
            self.set_status("Вхід через ChatGPT завершено. Codex готовий.")

        self.run_async(
            login_chatgpt,
            success,
            label="Очікую вхід через ChatGPT",
            done_label="Codex авторизовано",
        )

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
