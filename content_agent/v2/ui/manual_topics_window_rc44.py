from __future__ import annotations

import logging
import queue
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from ...app.container import AppServices, build_services
from ...backup import import_backup
from ...config import AppConfig, ConfigError, load_config
from ...i18n import language_label
from ..storage.factory import create_database
from .manual_topics_window import ALL_SOURCES, ALL_TOPICS, MainWindow as Rc43MainWindow

logger = logging.getLogger("content_agent.v2.ui.rc44")


class MainWindow(Rc43MainWindow):
    """Stable V2 shell for visible filters plus reliability/composition overrides.

    The file name stays stable intentionally: new behavior moves toward services
    and explicit composition rather than another version-numbered MainWindow layer.
    """

    def __init__(self, root, database_or_services, config=None) -> None:
        if isinstance(database_or_services, AppServices):
            services = database_or_services
            self.services = services
            super().__init__(root, services.db, services.config)
        else:
            super().__init__(root, database_or_services, config)
            self.services = build_services(config=self.config, database=self.db)
        try:
            setattr(self.root, "_ua_free_post_ui", self._post_ui)
        except Exception:
            logger.exception("Could not expose UI dispatcher to child dialogs")

    def _drain_ui_events(self) -> None:
        """Keep Tk alive while making queued callback failures observable."""
        self._ui_dispatch_after_id = None
        self._ui_last_pulse = time.monotonic()
        if getattr(self, "_closing", False):
            return
        processed = 0
        while processed < 200:
            try:
                callback = self._ui_event_queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except Exception:
                logger.exception("Queued UI callback failed")
            processed += 1
        if not getattr(self, "_closing", False):
            try:
                self._ui_dispatch_after_id = self.root.after(50, self._drain_ui_events)
            except tk.TclError:
                self._ui_dispatch_after_id = None

    def import_backup_ui(self) -> None:
        """Restore through the same reliable database composition as startup."""
        selected = self.files.askopenfilename(
            parent=self.root,
            title="Оберіть backup",
            filetypes=[("UA FREE backup", "*.zip")],
        )
        if not selected:
            return
        if not self.msg.askyesno(
            "Імпорт",
            "Поточні дані спочатку буде збережено в safety backup. Продовжити?",
            parent=self.root,
        ):
            return

        def success(result: object) -> None:
            try:
                self.config = load_config()
            except ConfigError:
                self.config = AppConfig()
            self.publisher_factory.config = self.config
            self.db = create_database()
            self.services = build_services(config=self.config, database=self.db)
            self.worker.database = self.db
            self.refresh_sources()
            self.refresh_groups()
            self.refresh_queue()
            self.refresh_history()
            self._update_target_availability()
            self.ui_language_var.set(language_label(self.config.ui_language))
            self._apply_language()
            self.refresh_learning_stats()
            self.msg.showinfo(
                "Імпорт",
                f"Імпорт завершено. Safety backup: {getattr(result, 'safety_backup', '')}",
                parent=self.root,
            )

        self.run_async(
            lambda: import_backup(Path(selected)),
            success,
            label="Імпортую резервну копію",
            done_label="Імпорт завершено",
        )

    def _install_manual_topic_inbox_filters(self) -> None:
        if hasattr(self, "inbox_source_filter_box"):
            return
        tree = getattr(self, "groups_tree", None)
        if tree is None:
            return

        tree_frame = tree.master
        tab = tree_frame.master
        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=(0, 6), before=tree_frame)
        self._manual_topic_filter_bar = bar

        self.inbox_source_filter_var = tk.StringVar(value=ALL_SOURCES)
        self.inbox_topic_filter_var = tk.StringVar(value=ALL_TOPICS)

        ttk.Label(bar, text="Фільтри:").pack(side="left")
        ttk.Label(bar, text="Джерело:").pack(side="left", padx=(10, 4))
        self.inbox_source_filter_box = ttk.Combobox(
            bar,
            textvariable=self.inbox_source_filter_var,
            state="readonly",
            width=28,
        )
        self.inbox_source_filter_box.pack(side="left", padx=(0, 10))
        self.inbox_source_filter_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh_groups())

        ttk.Label(bar, text="Тема:").pack(side="left", padx=(0, 4))
        self.inbox_topic_filter_box = ttk.Combobox(
            bar,
            textvariable=self.inbox_topic_filter_var,
            state="readonly",
            width=24,
        )
        self.inbox_topic_filter_box.pack(side="left", padx=(0, 10))
        self.inbox_topic_filter_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh_groups())

        ttk.Button(
            bar,
            text="Скинути фільтри",
            command=self.reset_manual_topic_filters,
        ).pack(side="left")

        self._refresh_inbox_filter_choices()


__all__ = ["MainWindow"]
