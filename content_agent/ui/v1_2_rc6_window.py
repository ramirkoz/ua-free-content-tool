from __future__ import annotations

from .ai_workflow_v1_3_rc6 import AIWorkflowRC6Mixin
from .social_connections_v1_3_rc6 import SocialConnectionsRC6Mixin
from .v1_2_rc5_window import MainWindow as RC5Window


class MainWindow(AIWorkflowRC6Mixin, SocialConnectionsRC6Mixin, RC5Window):
    """RC6 field-feedback build: quiet Codex, global dedup, Telegram media and connection controls."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.root.title("UA FREE Content Tool — v1.2.0-dev RC6 · Codex + Rowboat")
        if hasattr(self, "topic_search_status_var"):
            self.topic_search_status_var.set(
                "Пошук схожих аналізує всі нові блоки за один прохід; виділяти один блок більше не потрібно."
            )
