from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable


@dataclass(slots=True)
class InboxFilterState:
    source_id: int | None = None
    topic_id: int | None = None
    search: str = ""

    def normalized_search(self) -> str:
        return str(self.search or "").strip()


class InboxController:
    """Own Inbox filter state independently from Tk widgets.

    The UI can rebuild comboboxes without losing active Source/Topic/Search state,
    which was the root cause of the RC46 filter reset regression.
    """

    def __init__(self, refresh: Callable[[InboxFilterState], object]) -> None:
        self.state = InboxFilterState()
        self._refresh = refresh

    def set_source(self, source_id: int | None) -> None:
        self.state.source_id = int(source_id) if source_id is not None else None
        self._refresh(self.state)

    def set_topic(self, topic_id: int | None) -> None:
        self.state.topic_id = int(topic_id) if topic_id is not None else None
        self._refresh(self.state)

    def set_search(self, value: str) -> None:
        self.state.search = str(value or "")
        self._refresh(self.state)

    def reset(self) -> None:
        self.state = InboxFilterState()
        self._refresh(self.state)


__all__ = ["InboxController", "InboxFilterState"]
