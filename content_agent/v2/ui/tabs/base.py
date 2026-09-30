from __future__ import annotations

from typing import Protocol


class TabController(Protocol):
    """Behavioral boundary for one operator-facing tab."""

    def refresh(self) -> None: ...

    def focus_primary(self) -> None: ...

    def reset(self) -> None: ...


__all__ = ["TabController"]
