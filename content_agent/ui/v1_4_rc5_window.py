from __future__ import annotations

from .v1_4_rc4_window import MainWindow as Rc4MainWindow


class MainWindow(Rc4MainWindow):
    """v1.4.0-rc5: stable duplicate columns and deterministic last-used targets."""

    VERSION_LABEL = "1.4.0-rc5"

    def _apply_v14_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v1.4.0-rc5")

    def _persist_live_target_selection(self) -> None:
        """Do not let transient UI state overwrite the last actually used targets.

        RC4 saved every checkbox fluctuation after 350 ms. Loading an existing
        material, rebuilding dynamic destinations, recommendations, or selecting
        all profiles could therefore replace publication_target_sets.json before
        the editor approved anything. The inherited approve_current(), explicit
        preset Apply, and Save preset paths already persist the real selection.
        RC5 intentionally leaves those authoritative paths as the only writers.
        """

        self._last_targets_save_after_id = None
