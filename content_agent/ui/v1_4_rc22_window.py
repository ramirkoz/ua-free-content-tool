from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..ai_router_v1_4_rc22 import (
    AIRouterError,
    install_runtime,
    last_ai_result_label,
    probe_provider,
    provider_health_rows,
    provider_health_text,
)
from ..codex_engine_v1_3 import clear_codex_status_cache, inspect_codex_cached

install_runtime()

from .v1_4_rc21_window import MainWindow as Rc21MainWindow

# The inherited UI imports compatibility router functions while it is loading.
# Patch those consumer globals now that the full inheritance chain exists.
install_runtime()


class MainWindow(Rc21MainWindow):
    """v1.4.0-rc22: resilient AI routing and truthful provider health."""

    VERSION_LABEL = "1.4.0-rc22"

    def __init__(self, root, database, config) -> None:
        self.ai_provider_health_var = tk.StringVar(master=root, value="AI-провайдери: стан ще не перевірено")
        self._rc22_health_label: ttk.Label | None = None
        install_runtime()
        super().__init__(root, database, config)
        install_runtime()
        self._install_provider_health_panel()
        self._apply_v14_labels()
        self.refresh_ai_component_status()

    def _apply_v14_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v1.4.0-rc22")

    def _apply_language(self, refresh: bool = True) -> None:
        super()._apply_language(refresh=refresh)
        self._apply_v14_labels()
        if hasattr(self, "ai_provider_health_var"):
            self.refresh_ai_component_status()

    def _find_ai_router_frame(self) -> ttk.LabelFrame | None:
        stack = list(self.notebook.winfo_children())
        while stack:
            widget = stack.pop()
            if isinstance(widget, ttk.LabelFrame):
                try:
                    label = str(widget.cget("text"))
                except tk.TclError:
                    label = ""
                if label.startswith("1. AI Router"):
                    return widget
            stack.extend(widget.winfo_children())
        return None

    def _install_provider_health_panel(self) -> None:
        if self._rc22_health_label is not None:
            return
        frame = self._find_ai_router_frame()
        if frame is None:
            return
        ttk.Separator(frame, orient="horizontal").grid(row=14, column=0, columnspan=5, sticky="ew", pady=(8, 5))
        ttk.Label(frame, text="Живий стан AI-провайдерів", font="TkHeadingFont").grid(
            row=15, column=0, sticky="nw", pady=(0, 4)
        )
        label = ttk.Label(
            frame,
            textvariable=self.ai_provider_health_var,
            justify="left",
            anchor="w",
            wraplength=1180,
            foreground="#444",
        )
        label.grid(row=16, column=0, columnspan=5, sticky="ew", pady=(0, 4))
        self._rc22_health_label = label

    def refresh_ai_component_status(self) -> None:
        install_runtime()
        super().refresh_ai_component_status()
        if not hasattr(self, "ai_provider_health_var"):
            return
        try:
            rows = provider_health_rows()
            configured = [row for row in rows if row["configured"]]
            without_cooldown = [row for row in configured if int(row["available_slots"] or 0) > 0]
            confirmed = [row for row in configured if str(row["last_outcome"] or "") == "ok"]
            cooling = len(configured) - len(without_cooldown)
            self.ai_router_status_var.set(
                f"AI Router: налаштовано провайдерів {len(configured)} · без cooldown {len(without_cooldown)}"
                f" · живим запитом підтверджено {len(confirmed)}"
                + (f" · cooldown {cooling}" if cooling else "")
                + f" · останній успішний: {last_ai_result_label()}"
            )
            self.ai_provider_health_var.set(provider_health_text())
        except Exception as exc:
            self.ai_provider_health_var.set(f"Не вдалося прочитати стан AI Router: {exc}")

    def check_codex_ui(self) -> None:
        clear_codex_status_cache()
        self.codex_status_var.set("… CODEX · перевіряю сесію та живий AI-запит…")

        def action() -> object:
            status = inspect_codex_cached(max_age_seconds=1.0, force=True)
            if not status.installed:
                raise AIRouterError("Codex SDK не встановлено.")
            if not status.authenticated:
                raise AIRouterError("Codex встановлено, але ChatGPT-сесію не авторизовано.")
            return probe_provider("codex")

        def success(result: object) -> None:
            self.refresh_ai_component_status()
            self.set_status(str(result))

        self.run_async(
            action,
            success,
            label="Перевіряю Codex: авторизація + живий запит",
            done_label="Codex перевірено живим запитом",
            timeout_seconds=50,
            timeout_message="Codex не завершив живу перевірку за 50 секунд.",
            modal_errors=True,
            modal_timeout=False,
            timeout_is_error=True,
        )
