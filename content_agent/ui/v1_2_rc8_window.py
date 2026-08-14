from __future__ import annotations

from datetime import datetime, timezone
from tkinter import ttk

from ..publication_policy_v1_2_rc4 import compose_publication_text_rc4
from ..scheduling import KYIV, next_publish_slot
from . import main_window as legacy_ui
from .v1_2_rc6_window import MainWindow as RC7Window


class MainWindow(RC7Window):
    """v1.2.0 final window: donation policy, queue recalculation and Codex UI wording."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        # Ancestor RC3 installs its historical composer during startup. v1.2.0
        # policy must win after the full MRO has initialized: Facebook + Threads
        # keep donation in comment/reply; LinkedIn + Telegram + Instagram keep it
        # inside the root post/caption.
        legacy_ui.compose_publication_text = compose_publication_text_rc4
        self._ensure_codex_rewrite_label()
        self.root.title("UA FREE Content Tool — v1.2.0 · Codex + Rowboat")

    def _build_queue_tab(self) -> None:
        super()._build_queue_tab()
        self._install_recalculate_queue_button()

    def _apply_language(self, refresh: bool = True) -> None:
        super()._apply_language(refresh=refresh)
        self._ensure_codex_rewrite_label()
        button = getattr(self, "recalculate_queue_button", None)
        if button is not None:
            button.configure(text="Перерахувати чергу")

    def _ensure_codex_rewrite_label(self) -> None:
        button = getattr(self, "rewrite_button", None)
        if button is not None:
            button.configure(text="Рерайт через Codex / ChatGPT")

    def _install_recalculate_queue_button(self) -> None:
        if not hasattr(self, "queue_tab"):
            return
        children = self.queue_tab.winfo_children()
        if not children:
            return
        toolbar = children[0]
        self.recalculate_queue_button = ttk.Button(
            toolbar,
            text="Перерахувати чергу",
            command=self.recalculate_pending_queue,
        )
        self.recalculate_queue_button.pack(side="left", padx=3)

    def recalculate_pending_queue(self) -> None:
        """Reflow every pending package using the current hours and interval.

        Sent/completed/cancelled/paused packages are untouched. The operation is
        performed under one SQLite write transaction so the publication worker
        cannot claim a package halfway through the recalculation.
        """

        start_hour = int(self.config.publish_start_hour)
        end_hour = int(self.config.publish_end_hour)
        interval = int(self.config.publish_interval_minutes)
        now = datetime.now(KYIV)

        if not self.msg.askyesno(
            "Перерахувати чергу",
            "Перерахувати час усіх пакетів зі статусом «очікує» за поточними налаштуваннями?\n\n"
            f"Вікно: {start_hour:02d}:00–{end_hour:02d}:00. Інтервал: {interval} хв.\n"
            "Уже опубліковані, призупинені, скасовані та пакети, що зараз публікуються, не змінюються.",
            parent=self.root,
        ):
            return

        schedules: list[tuple[int, datetime]] = []
        try:
            with self.db.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                try:
                    active = db.execute(
                        "SELECT id FROM publication_batches WHERE status='in_progress' LIMIT 1"
                    ).fetchone()
                    if active is not None:
                        raise RuntimeError(
                            "Зараз публікується пакет. Дочекайтеся завершення і натисніть «Перерахувати чергу» ще раз."
                        )
                    rows = db.execute(
                        "SELECT id FROM publication_batches "
                        "WHERE status='pending' ORDER BY julianday(scheduled_at), id"
                    ).fetchall()
                    latest: datetime | None = None
                    for row in rows:
                        slot = next_publish_slot(
                            now=now,
                            latest_scheduled=latest,
                            start_hour=start_hour,
                            end_hour=end_hour,
                            interval_minutes=interval,
                        )
                        batch_id = int(row[0])
                        db.execute(
                            "UPDATE publication_batches "
                            "SET scheduled_at=?, updated_at=? "
                            "WHERE id=? AND status='pending'",
                            (
                                slot.astimezone(timezone.utc).isoformat(timespec="seconds"),
                                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                batch_id,
                            ),
                        )
                        schedules.append((batch_id, slot))
                        latest = slot
                    db.execute("COMMIT")
                except Exception:
                    db.execute("ROLLBACK")
                    raise
        except Exception as exc:
            self._show_error(exc)
            return

        self.refresh_queue()
        if hasattr(self, "worker"):
            self.worker.wake()
        if not schedules:
            self.msg.showinfo(
                "Перерахувати чергу",
                "Пакетів зі статусом «очікує» немає.",
                parent=self.root,
            )
            return

        first = schedules[0][1].astimezone(KYIV)
        last = schedules[-1][1].astimezone(KYIV)
        self.msg.showinfo(
            "Чергу перераховано",
            f"Перераховано пакетів: {len(schedules)}.\n"
            f"Перший: {first.strftime('%d.%m.%Y %H:%M')}.\n"
            f"Останній: {last.strftime('%d.%m.%Y %H:%M')} (Київ).",
            parent=self.root,
        )
