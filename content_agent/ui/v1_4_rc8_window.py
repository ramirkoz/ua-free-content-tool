from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..destinations_v1_4 import destination_ready
from .v1_4_rc7_window import MainWindow as Rc7MainWindow


def donation_enabled_for_destination(settings, key: str, platform: str) -> bool:
    """Return the visible per-destination donation state.

    v1.4 replaced the old generic platform targets with concrete destination keys
    (for example ``facebook:<page_id>`` and ``instagram:<account_id>``).  RC7 kept
    the old donation policy object, but its v1.4 target-control rebuild discarded
    the per-profile donation checkboxes.  This helper also preserves the one legacy
    generic Instagram preference until the user next changes a concrete checkbox.
    """

    target = str(key or "").strip()
    kind = str(platform or "").strip()
    if settings.enabled_for(target):
        return True
    return kind == "instagram" and settings.enabled_for("instagram")


class MainWindow(Rc7MainWindow):
    """v1.4.0-rc8: restore editable per-destination donation switches."""

    VERSION_LABEL = "1.4.0-rc8"

    def _apply_v14_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v1.4.0-rc8")

    def _rebuild_target_controls(self) -> None:
        # v1.4 rebuilds the whole destination grid and therefore destroys every
        # child widget.  Clear stale references before delegating to that rebuild.
        self.donation_vars = {}
        self.donation_checks = {}

        super()._rebuild_target_controls()
        if not hasattr(self, "targets_row"):
            return

        # Re-create one independent donation switch for every concrete publishing
        # destination.  Availability must use the v1.4 destination resolver rather
        # than AppConfig.platform_ready(), which does not understand instagram:<id>.
        for spec in self._destination_specs():
            if spec.key not in self.target_vars:
                continue
            variable = tk.BooleanVar(
                value=donation_enabled_for_destination(
                    self._donation_settings,
                    spec.key,
                    spec.platform,
                )
            )
            ready = destination_ready(self.config, spec.key)
            check = ttk.Checkbutton(
                self.targets_row,
                text="Донатний блок",
                variable=variable,
                state="normal" if ready else "disabled",
                command=lambda key=spec.key: self._donation_target_toggled(key),
            )
            self.donation_vars[spec.key] = variable
            self.donation_checks[spec.key] = check

        # The inherited layout deliberately places donation controls on the row
        # directly beneath their corresponding destination checkbox.
        self._layout_target_controls()
        self._refresh_donation_status()

    def _refresh_donation_status(self) -> None:
        variable = getattr(self, "donation_status_var", None)
        if variable is None:
            return
        enabled_count = sum(
            1 for item in getattr(self, "donation_vars", {}).values() if bool(item.get())
        )
        text_state = "текст порожній" if not self._donation_settings.text.strip() else "текст збережено"
        variable.set(f"{text_state} · увімкнено профілів: {enabled_count}")
