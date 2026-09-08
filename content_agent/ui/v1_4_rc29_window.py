from __future__ import annotations

from ..ai_router_v1_4_rc28 import install_runtime as install_router_runtime
from ..codex_engine_v1_4_rc28 import install_codex as install_codex_safe
from ..restart_helper_v1_4_rc29 import schedule_delayed_restart
from ..rewrite_pipeline_v1_4_rc27 import install_runtime as install_rewrite_runtime
from .v1_4_rc28_window import MainWindow as Rc28MainWindow


class MainWindow(Rc28MainWindow):
    """v1.4.0-rc29: make Codex installation atomic from the user's point of view."""

    VERSION_LABEL = "1.4.0-rc29"

    def __init__(self, root, database, config) -> None:
        install_router_runtime()
        install_rewrite_runtime()
        super().__init__(root, database, config)
        install_router_runtime()
        install_rewrite_runtime()
        self._apply_v14_labels()
        self.refresh_ai_component_status()

    def _apply_v14_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v1.4.0-rc29")

    def _apply_language(self, refresh: bool = True) -> None:
        super()._apply_language(refresh=refresh)
        install_router_runtime()
        install_rewrite_runtime()
        self._apply_v14_labels()

    def install_codex_ui(self) -> None:
        def success(_result: object) -> None:
            try:
                from ..ai_router_v1_2_1 import clear_router_cooldowns
                clear_router_cooldowns()
            except Exception:
                pass
            self.set_status("Codex runtime встановлено. Автоматично перезапускаю програму…")
            try:
                schedule_delayed_restart()
            except Exception as exc:
                self._show_error(RuntimeError(
                    "Codex runtime встановлено, але автоматичний перезапуск не вдався. "
                    f"Закрийте й відкрийте програму вручну. Деталі: {exc}"
                ))
                return
            self.root.after(250, self.root.destroy)

        self.run_async(
            install_codex_safe,
            success,
            label="Встановлюю Codex у новий runtime",
            done_label="Codex runtime підготовлено до перезапуску",
            timeout_seconds=660,
            timeout_message="Встановлення Codex не завершилося за 11 хвилин.",
            modal_errors=True,
            modal_timeout=True,
            timeout_is_error=True,
        )
