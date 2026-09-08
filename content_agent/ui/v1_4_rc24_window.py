from __future__ import annotations

from ..ai_router import install_runtime
from .v1_4_rc23_window import MainWindow as Rc23MainWindow

# RC23 and RC22 install their historical runtime layers while importing.
# Re-apply RC24 after the inheritance chain is loaded and around each UI build.
install_runtime()


class MainWindow(Rc23MainWindow):
    """v1.4.0-rc24: live Codex model selection and one-pass provider recovery."""

    VERSION_LABEL = "1.4.0-rc24"

    def __init__(self, root, database, config) -> None:
        install_runtime()
        super().__init__(root, database, config)
        install_runtime()
        self._apply_v14_labels()
        self.refresh_ai_component_status()

    def _apply_v14_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v1.4.0-rc24")

    def _apply_language(self, refresh: bool = True) -> None:
        super()._apply_language(refresh=refresh)
        install_runtime()
        self._apply_v14_labels()
