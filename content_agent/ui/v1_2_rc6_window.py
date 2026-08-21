from __future__ import annotations

import tkinter as tk

from .ai_workflow_v1_3_rc6 import AIWorkflowRC6Mixin
from .social_connections_v1_3_rc6 import SocialConnectionsRC6Mixin
from .v1_2_rc5_window import MainWindow as RC5Window


class MainWindow(AIWorkflowRC6Mixin, SocialConnectionsRC6Mixin, RC5Window):
    """RC6 field-feedback build: quiet Codex, global dedup, Telegram media and connection controls."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.root.title("UA FREE Content Tool — v1.3.1-rc7")
        self._register_global_search_button_rc6(self.root)
        if hasattr(self, "topic_search_status_var"):
            self.topic_search_status_var.set(
                "Пошук схожих аналізує всі нові блоки за один прохід; виділяти один блок більше не потрібно."
            )

    def _register_global_search_button_rc6(self, parent: tk.Misc) -> bool:
        for child in parent.winfo_children():
            if isinstance(child, tk.Button):
                try:
                    text = str(child.cget("text"))
                except tk.TclError:
                    text = ""
                if text == "Пошук схожих за темою матеріалів":
                    if child not in self.operation_buttons:
                        self.operation_buttons.append(child)
                    return True
            if self._register_global_search_button_rc6(child):
                return True
        return False
