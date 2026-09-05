from __future__ import annotations

import threading
from datetime import datetime, time, timedelta, timezone

from ..scheduling import KYIV
from .v1_4_rc17_window import MainWindow as Rc17MainWindow


ROLLOVER_GRACE_SECONDS = 2


def milliseconds_until_next_kyiv_rollover(*, now: datetime | None = None) -> int:
    """Return a DST-safe Tk delay to just after the next Kyiv midnight."""
    current = (now or datetime.now(KYIV)).astimezone(KYIV)
    next_date = current.date() + timedelta(days=1)
    target = datetime.combine(next_date, time(0, 0, ROLLOVER_GRACE_SECONDS), tzinfo=KYIV)
    elapsed = target.astimezone(timezone.utc) - current.astimezone(timezone.utc)
    return max(1000, int(elapsed.total_seconds() * 1000))


class MainWindow(Rc17MainWindow):
    """v1.4.0-rc18: current-Kyiv-day Inbox with automatic midnight rollover."""

    VERSION_LABEL = "1.4.0-rc18"

    def __init__(self, root, database, config) -> None:
        self.inbox_rollover_after_id: str | None = None
        self.inbox_rollover_running = False
        super().__init__(root, database, config)
        self._schedule_inbox_rollover()

    def _apply_v14_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v1.4.0-rc18")

    def _schedule_inbox_rollover(self) -> None:
        if getattr(self, "_closing", False) or self.stop_event.is_set():
            return
        if self.inbox_rollover_after_id is not None:
            try:
                self.root.after_cancel(self.inbox_rollover_after_id)
            except Exception:
                pass
            self.inbox_rollover_after_id = None
        delay_ms = milliseconds_until_next_kyiv_rollover()
        self.inbox_rollover_after_id = self.root.after(delay_ms, self._start_inbox_rollover)

    def _start_inbox_rollover(self) -> None:
        self.inbox_rollover_after_id = None
        if getattr(self, "_closing", False) or self.stop_event.is_set():
            return

        # Arm tomorrow before doing any database work. If the PC wakes from sleep
        # after midnight, Tk fires this callback on wake and the same cleanup runs.
        self._schedule_inbox_rollover()
        if self.inbox_rollover_running:
            return
        self.inbox_rollover_running = True

        def worker() -> None:
            try:
                result = self.db.rollover_inbox_day()
            except Exception as exc:
                self._post_ui(lambda error=exc: self._finish_inbox_rollover(error=error))
                return
            self._post_ui(lambda summary=result: self._finish_inbox_rollover(summary=summary))

        threading.Thread(
            target=worker,
            name="inbox-daily-rollover",
            daemon=True,
        ).start()

    def _finish_inbox_rollover(
        self,
        *,
        summary: dict[str, int] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.inbox_rollover_running = False
        if getattr(self, "_closing", False):
            return
        if error is not None:
            self.status_var.set(f"Не вдалося очистити Вхідні після зміни доби: {error}")
            return

        self.refresh_groups()
        data = summary or {}
        archived_groups = int(data.get("archived_groups", 0))
        trimmed_groups = int(data.get("trimmed_groups", 0))
        archived_articles = int(data.get("archived_articles", 0))
        self.status_var.set(
            "Вхідні переведено на нову добу: "
            f"архівовано блоків {archived_groups}, очищено змішаних блоків {trimmed_groups}, "
            f"прибрано старих новин {archived_articles}."
        )

    def close(self) -> None:
        if self.inbox_rollover_after_id is not None:
            try:
                self.root.after_cancel(self.inbox_rollover_after_id)
            except Exception:
                pass
            self.inbox_rollover_after_id = None
        super().close()
