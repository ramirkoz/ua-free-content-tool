from __future__ import annotations

from ..ai_router_v1_4_rc28 import install_runtime as install_router_runtime
from ..codex_engine_v1_4_rc28 import install_codex as install_codex_safe
from ..rewrite_pipeline_v1_4_rc27 import install_runtime as install_rewrite_runtime
from .v1_4_rc27_window import MainWindow as Rc27MainWindow


class MainWindow(Rc27MainWindow):
    """v1.4.0-rc28: restore AI runtime deadlines and safe Codex updates."""

    VERSION_LABEL = "1.4.0-rc28"

    def __init__(self, root, database, config) -> None:
        install_router_runtime()
        install_rewrite_runtime()
        super().__init__(root, database, config)
        install_router_runtime()
        install_rewrite_runtime()
        self._apply_v14_labels()
        self.refresh_ai_component_status()

    def _apply_v14_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v1.4.0-rc28")

    def _apply_language(self, refresh: bool = True) -> None:
        super()._apply_language(refresh=refresh)
        install_router_runtime()
        install_rewrite_runtime()
        self._apply_v14_labels()

    def install_codex_ui(self) -> None:
        def success(result: object) -> None:
            # The newly installed SDK is intentionally activated on restart when
            # the current process already has Codex/Pydantic DLLs loaded.
            try:
                from ..ai_router_v1_2_1 import clear_router_cooldowns
                clear_router_cooldowns()
            except Exception:
                pass
            self.refresh_ai_component_status()
            message = str(result or "Codex встановлено.").strip()
            self.set_status(message)
            if "Перезапустіть" in message:
                self.msg.showinfo("Codex оновлено", message, parent=self.root)

        self.run_async(
            install_codex_safe,
            success,
            label="Встановлюю Codex у новий runtime",
            done_label="Codex встановлено",
        )
