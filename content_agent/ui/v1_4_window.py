from __future__ import annotations

import json
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from ..destinations_v1_4 import (
    DestinationSchedule,
    DestinationScheduleStore,
    destination_labels,
    destination_ready,
    destination_specs,
    load_instagram_catalog,
    make_display_title,
    normalize_legacy_target_keys,
    save_instagram_catalog,
)
from ..google_drive import GoogleDriveError
from ..instagram_accounts_v1_4 import discover_instagram_accounts
from ..publication_text import TextLimitError, validate_editorial_text, validate_media_message
from ..publisher_factory_v1_4 import V14PublisherFactory
from ..scheduling import KYIV, next_publish_slot, parse_iso
from ..worker import WorkerResult
from ..worker_v1_4 import V14PublicationWorker
from . import main_window as legacy_ui
from .rc14_window import MainWindow as Rc14Window


class MainWindow(Rc14Window):
    """v1.4: every concrete page/profile/channel owns its queue and clock."""

    VERSION_LABEL = "1.4.0-rc1"

    def __init__(self, root: tk.Tk, database, config) -> None:
        self._instagram_catalog = load_instagram_catalog()
        self._destination_schedule_store = DestinationScheduleStore(config)
        self.queue_trees: dict[str, ttk.Treeview] = {}
        self.history_trees: dict[str, ttk.Treeview] = {}
        self.history_rows: dict[int, dict[str, object]] = {}
        self._schedule_vars: dict[str, tuple[tk.StringVar, tk.StringVar, tk.StringVar]] = {}
        super().__init__(root, database, config)

        # Replace the inherited batch-oriented runtime before RC14 starts the
        # background worker. The old worker thread has not been started yet.
        self.publisher_factory = V14PublisherFactory(self.config, self._donation_settings)
        self.worker = V14PublicationWorker(
            self.db,
            self.publisher_factory,
            inter_target_delay_seconds=5.0,
            progress_callback=self._publication_progress_from_worker,
            result_callback=self._publication_result_from_worker,
            managed_media_registry=self.managed_media_registry,
            image_store=self.multi_image_store,
        )
        self.worker_thread = threading.Thread(
            target=self.worker.run_loop,
            args=(self.stop_event,),
            name="publication-worker-v14",
            daemon=True,
        )
        self._install_destination_schedule_settings()
        self._refresh_destination_views(rebuild=True)
        self._apply_v14_labels()

    def _apply_v14_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v1.4.0-rc1")

    def _apply_language(self, refresh: bool = True) -> None:
        super()._apply_language(refresh=refresh)
        self._apply_v14_labels()

    # ------------------------------------------------------------------
    # Destination registry / labels.
    # ------------------------------------------------------------------
    def _destination_specs(self):
        return destination_specs(self.config)

    def _destination_labels(self) -> dict[str, str]:
        return destination_labels(self.config)

    def _short_destination_label(self, key: str) -> str:
        label = self._destination_labels().get(key, key)
        for suffix in (" (Facebook)", " (Instagram)", " (Threads)", " (LinkedIn)", " (Telegram)"):
            if label.endswith(suffix):
                return label[: -len(suffix)]
        return label

    def _target_display_name(self, key: str) -> str:
        return self._destination_labels().get(key, key)

    def _rebuild_target_controls(self) -> None:
        if not hasattr(self, "targets_row"):
            return
        previous = {key: variable.get() for key, variable in getattr(self, "target_vars", {}).items()}
        for child in self.targets_row.winfo_children():
            child.destroy()
        self.target_vars = {}
        self.target_checks = {}
        for spec in self._destination_specs():
            variable = tk.BooleanVar(value=previous.get(spec.key, False))
            ready = destination_ready(self.config, spec.key)
            check = ttk.Checkbutton(
                self.targets_row,
                text=spec.label,
                variable=variable,
                state="normal" if ready else "disabled",
                command=self._update_selected_targets_summary,
            )
            self.target_vars[spec.key] = variable
            self.target_checks[spec.key] = check
        if "telegram" in self.target_vars and destination_ready(self.config, "telegram") and not any(
            variable.get() for variable in self.target_vars.values()
        ):
            self.target_vars["telegram"].set(True)
        self._layout_target_controls()
        self._update_selected_targets_summary()

    def _update_selected_targets_summary(self) -> None:
        selected = sum(1 for variable in getattr(self, "target_vars", {}).values() if variable.get())
        available = sum(1 for key in getattr(self, "target_vars", {}) if destination_ready(self.config, key))
        self.selected_targets_var.set(f"Вибрано: {selected} з {available}")
        # Preserve the inherited target-preset UX without forcing it to understand
        # the old single generic Instagram key.
        if not getattr(self, "_target_preset_syncing", True) and hasattr(self, "target_preset_var"):
            try:
                self.target_preset_var.set(self._matching_current_target_preset_label())
            except Exception:
                pass

    def select_all_targets(self) -> None:
        for key, variable in self.target_vars.items():
            variable.set(destination_ready(self.config, key))
        self._update_selected_targets_summary()

    def _apply_target_keys(self, keys: list[str]) -> None:
        normalized = set(normalize_legacy_target_keys(self.config, keys))
        self._target_preset_syncing = True
        try:
            for key, variable in self.target_vars.items():
                variable.set(key in normalized and destination_ready(self.config, key))
        finally:
            self._target_preset_syncing = False
        self._update_selected_targets_summary()

    def apply_recommendations(self, recommendations: list[str]) -> None:
        for variable in self.target_vars.values():
            variable.set(False)
        wanted = {str(value) for value in recommendations}
        for spec in self._destination_specs():
            if not destination_ready(self.config, spec.key):
                continue
            if spec.platform in wanted or spec.key in wanted:
                self.target_vars[spec.key].set(True)
        if not any(variable.get() for variable in self.target_vars.values()) and "telegram" in self.target_vars:
            if destination_ready(self.config, "telegram"):
                self.target_vars["telegram"].set(True)
        self._update_selected_targets_summary()

    # ------------------------------------------------------------------
    # Instagram: discover every professional account attached to accessible Pages.
    # ------------------------------------------------------------------
    def _rebuild_instagram_section_rc6(self) -> None:
        old = self._find_platform_frame("Instagram")
        facebook = self._find_platform_frame("Facebook Pages")
        if facebook is None:
            return
        parent = facebook.master
        if old is not None:
            old.destroy()

        # Keep legacy encrypted variables alive for config compatibility, but the
        # new UI never asks the user to copy one Instagram id/token at a time.
        self.settings_vars.setdefault("instagram_user_id", tk.StringVar(value=self.config.instagram_user_id))
        self.settings_vars.setdefault("instagram_token", tk.StringVar(value=self.config.instagram_token))
        self.instagram_status_var = tk.StringVar(value="")

        frame = ttk.LabelFrame(parent, text="Instagram", padding=8)
        frame.pack(fill="x", pady=4, after=facebook)
        top = ttk.Frame(frame)
        top.pack(fill="x")
        ttk.Button(top, text="Знайти / оновити всі Instagram-акаунти", command=self.connect_instagram).pack(side="left")
        ttk.Button(top, text="Вимкнути", command=lambda: self._disconnect_social("instagram")).pack(
            side="left", padx=(6, 0)
        )
        ttk.Label(top, textvariable=self.instagram_status_var, foreground="#555").pack(side="left", padx=(10, 0))

        columns = ("account", "page", "type")
        self.instagram_accounts_tree = ttk.Treeview(frame, columns=columns, show="headings", height=4)
        self.instagram_accounts_tree.heading("account", text="Instagram")
        self.instagram_accounts_tree.heading("page", text="Пов’язана Facebook Page")
        self.instagram_accounts_tree.heading("type", text="Тип")
        self.instagram_accounts_tree.column("account", width=260, anchor="w")
        self.instagram_accounts_tree.column("page", width=420, anchor="w")
        self.instagram_accounts_tree.column("type", width=130, anchor="w")
        self.instagram_accounts_tree.pack(fill="x", pady=(7, 3))
        ttk.Label(
            frame,
            text=(
                "Токени Instagram окремо не дублюються: програма використовує зашифрований Page Access Token "
                "від відповідної Facebook Page. Кожен акаунт стає окремим потоком, чергою та розкладом."
            ),
            foreground="#666",
            wraplength=1200,
        ).pack(anchor="w")
        self._refresh_instagram_accounts_view()

    def _refresh_instagram_accounts_view(self) -> None:
        tree = getattr(self, "instagram_accounts_tree", None)
        if tree is None:
            return
        tree.delete(*tree.get_children())
        self._instagram_catalog = load_instagram_catalog()
        for row in self._instagram_catalog:
            account = f"@{row.username}" if row.username else row.id
            tree.insert("", "end", iid=row.id, values=(account, row.page_name or row.page_id or "—", row.account_type or "Professional"))
        if self._instagram_catalog:
            self.instagram_status_var.set(f"Підключено акаунтів: {len(self._instagram_catalog)}")
        elif self.config.instagram_user_id and self.config.instagram_token:
            self.instagram_status_var.set("Підключено 1 старий Instagram-профіль; оновіть список для мультиакаунта.")
        else:
            self.instagram_status_var.set("Відключено")

    def connect_instagram(self) -> None:
        token = str(self.config.meta_user_access_token or "").strip()
        if not token:
            self.msg.showinfo(
                "Instagram",
                "Спочатку підключіть Facebook Pages і збережіть Facebook User Access Token.",
                parent=self.root,
            )
            return
        self.instagram_status_var.set("Шукаю Instagram Professional accounts…")

        def action() -> object:
            return discover_instagram_accounts(token, self.config.meta_graph_version)

        def success(value: object) -> None:
            rows = list(value)  # type: ignore[arg-type]
            save_instagram_catalog(rows)
            self._instagram_catalog = rows
            self.config.instagram_enabled = bool(rows)
            if rows:
                first = rows[0]
                self.config.instagram_user_id = first.id
                self.config.instagram_profile_name = first.username or first.id
                page = self.config.facebook_page(first.page_id) if first.page_id else None
                self.config.instagram_token = str(page.get("access_token") or "") if page else ""
                self.settings_vars["instagram_user_id"].set(first.id)
                self.settings_vars["instagram_token"].set(self.config.instagram_token)
            self._persist_connected_config("Instagram: список професійних акаунтів оновлено")
            self._refresh_instagram_accounts_view()
            self._rebuild_target_controls()
            self._refresh_destination_views(rebuild=True)
            self._rebuild_destination_schedule_rows()
            self.worker.clear_auth_blocks()
            if rows:
                self.msg.showinfo(
                    "Instagram",
                    f"Знайдено й підключено професійних Instagram-акаунтів: {len(rows)}.",
                    parent=self.root,
                )
            else:
                self.msg.showwarning(
                    "Instagram",
                    "Meta не повернула жодного Instagram Professional account, прив’язаного до доступних Facebook Pages.",
                    parent=self.root,
                )

        self.run_async(
            action,
            success,
            label="Instagram: отримую всі професійні акаунти через Facebook Login",
            done_label="Instagram-акаунти оновлено",
        )

    def _disconnect_social(self, platform: str) -> None:
        super()._disconnect_social(platform)
        if platform == "instagram" and not self.config.instagram_enabled:
            save_instagram_catalog([])
            self._instagram_catalog = []
            self._refresh_instagram_accounts_view()
            self._refresh_destination_views(rebuild=True)
            self._rebuild_destination_schedule_rows()

    # ------------------------------------------------------------------
    # Independent per-destination schedules.
    # ------------------------------------------------------------------
    def _install_destination_schedule_settings(self) -> None:
        platforms = self._find_platform_frame("Facebook Pages")
        if platforms is None:
            return
        parent = platforms.master
        old = getattr(self, "destination_schedule_frame", None)
        if old is not None:
            try:
                old.destroy()
            except tk.TclError:
                pass
        self.destination_schedule_frame = ttk.LabelFrame(parent, text="Розклад окремо для кожного потоку", padding=8)
        self.destination_schedule_frame.pack(fill="x", pady=4)
        ttk.Label(
            self.destination_schedule_frame,
            text="Кожна сторінка, профіль і канал має власні слоти. Пропущений Telegram не рухає Facebook і навпаки.",
            foreground="#666",
        ).grid(row=0, column=0, columnspan=5, sticky="w", pady=(0, 6))
        self._rebuild_destination_schedule_rows()

    def _rebuild_destination_schedule_rows(self) -> None:
        frame = getattr(self, "destination_schedule_frame", None)
        if frame is None:
            return
        for child in list(frame.winfo_children())[1:]:
            child.destroy()
        self._schedule_vars = {}
        for column, text in enumerate(("Потік", "Від", "До", "Інтервал, хв", "")):
            ttk.Label(frame, text=text, font="TkHeadingFont" if column == 0 else None).grid(
                row=1, column=column, sticky="w", padx=(0, 8)
            )
        for index, spec in enumerate(self._destination_specs(), start=2):
            schedule = self._destination_schedule_store.get(spec.key)
            start_var = tk.StringVar(value=str(schedule.start_hour))
            end_var = tk.StringVar(value=str(schedule.end_hour))
            interval_var = tk.StringVar(value=str(schedule.interval_minutes))
            self._schedule_vars[spec.key] = (start_var, end_var, interval_var)
            ttk.Label(frame, text=self._short_destination_label(spec.key)).grid(row=index, column=0, sticky="w", padx=(0, 8), pady=2)
            ttk.Spinbox(frame, from_=0, to=23, textvariable=start_var, width=6).grid(row=index, column=1, sticky="w")
            ttk.Spinbox(frame, from_=1, to=24, textvariable=end_var, width=6).grid(row=index, column=2, sticky="w")
            ttk.Combobox(
                frame,
                textvariable=interval_var,
                values=("15", "30", "45", "60", "90", "120", "180", "240"),
                width=8,
            ).grid(row=index, column=3, sticky="w")
        action_row = max(2, len(self._destination_specs()) + 2)
        ttk.Button(frame, text="Зберегти розклади", command=self._save_destination_schedules).grid(
            row=action_row, column=4, sticky="e", pady=(6, 0)
        )
        frame.columnconfigure(0, weight=1)

    def _save_destination_schedules(self) -> None:
        try:
            for key, (start_var, end_var, interval_var) in self._schedule_vars.items():
                self._destination_schedule_store.set(
                    key,
                    DestinationSchedule(int(start_var.get()), int(end_var.get()), int(interval_var.get())),
                )
            self._destination_schedule_store.remove_missing(self._schedule_vars)
            self._destination_schedule_store.save()
        except (TypeError, ValueError) as exc:
            self._show_error(exc)
            return
        self.refresh_queue()
        self.set_status("Окремі розклади профілів, сторінок і каналів збережено.")

    # ------------------------------------------------------------------
    # Approval creates one batch per destination, each with its own next slot.
    # ------------------------------------------------------------------
    def approve_current(self) -> None:
        if self.current_group_id is None or not self.save_current():
            return
        selected = [key for key, variable in self.target_vars.items() if variable.get()]
        if not selected:
            self.msg.showwarning("Черга", "Оберіть хоча б один профіль, сторінку або канал.", parent=self.root)
            return
        if hasattr(self, "_remember_last_target_selection"):
            try:
                self._remember_last_target_selection(selected)
            except Exception:
                pass

        group = self.db.get_group(self.current_group_id)
        headline, _fact_card, rewrite, _platform_texts = self._editor_values()
        targets: dict[str, str] = {}
        schedules: dict[str, str] = {}
        now_kyiv = datetime.now(KYIV)
        try:
            validate_editorial_text(rewrite)
            for target in selected:
                logical = (
                    "facebook" if target.startswith("facebook:")
                    else "instagram" if target.startswith("instagram:")
                    else target
                )
                final = legacy_ui.compose_publication_text(
                    rewrite,
                    logical,
                    include_source_link=group.include_source_link,
                    source_url=group.primary_url,
                )
                validate_media_message(final, logical, has_media=bool(group.media_file_id))
                targets[target] = final
                rule = self._destination_schedule_store.get(target)
                latest = parse_iso(self.db.latest_scheduled_for_target(target, exclude_group_id=group.id))
                slot = next_publish_slot(
                    now=now_kyiv,
                    latest_scheduled=latest,
                    start_hour=rule.start_hour,
                    end_hour=rule.end_hour,
                    interval_minutes=rule.interval_minutes,
                )
                schedules[target] = slot.isoformat(timespec="seconds")
        except (TextLimitError, ValueError) as exc:
            self._show_error(exc)
            return
        if group.media_file_id and not self.config.platform_ready("google_drive"):
            self._show_error(GoogleDriveError("Google Drive не підключено, медіа неможливо завантажити."))
            return

        display_title = make_display_title(headline, rewrite)
        try:
            result = self.db.queue_independent_targets(
                self.db.lead_article_id(group.id),
                targets,
                schedules,
                display_title=display_title,
            )
        except Exception as exc:
            self._show_error(exc)
            return

        learned = self.db.record_editorial_example(
            group.id,
            final_text=rewrite,
            headline=headline,
            language=self.config.ui_language,
        )
        if self.config.learning_enabled:
            self.db.record_learning_event(
                "publication_approved",
                language=self.config.ui_language,
                group_id=group.id,
                payload={
                    "batch_ids": result.batch_ids,
                    "targets": sorted(targets),
                    "example_added": learned,
                    "display_title": display_title,
                },
            )
        self.worker.wake()
        self.refresh_groups()
        self.refresh_queue()
        self.notebook.select(self.queue_tab)

        labels = self._destination_labels()
        lines: list[str] = []
        for key in result.added:
            when = parse_iso(result.scheduled_at.get(key, ""))
            stamp = when.astimezone(KYIV).strftime("%d.%m %H:%M") if when else "?"
            lines.append(f"{labels.get(key, key)} → {stamp}")
        for key in result.updated:
            when = parse_iso(result.scheduled_at.get(key, ""))
            stamp = when.astimezone(KYIV).strftime("%d.%m %H:%M") if when else "?"
            lines.append(f"{labels.get(key, key)} → {stamp} (оновлено)")
        if result.already_final:
            lines.append("Уже завершено, дубль не створено: " + ", ".join(labels.get(key, key) for key in result.already_final))
        if result.removed:
            lines.append("Прибрано з черги: " + ", ".join(labels.get(key, key) for key in result.removed))
        self.msg.showinfo(
            "Черга",
            display_title + ("\n\n" + "\n".join(lines) if lines else "\n\nНових завдань не створено."),
            parent=self.root,
        )

    # ------------------------------------------------------------------
    # Queue UI: separate tabs per destination.
    # ------------------------------------------------------------------
    def _build_queue_tab(self) -> None:
        self.queue_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.queue_tab, text="Черга")
        actions = ttk.Frame(self.queue_tab)
        actions.pack(fill="x", pady=(0, 6))
        ttk.Button(actions, text="Оновити", command=self.refresh_queue).pack(side="left")
        ttk.Button(actions, text="Відкрити й редагувати", command=self.open_selected_batch).pack(side="left", padx=6)
        ttk.Button(actions, text="Скасувати / прибрати", command=self.cancel_selected_batches).pack(side="left")
        ttk.Button(actions, text="Запустити наступну публікацію зараз", command=self.run_worker_once).pack(side="right")
        self.queue_summary_var = tk.StringVar(value="Черга: завантаження…")
        ttk.Label(self.queue_tab, textvariable=self.queue_summary_var, font="TkHeadingFont").pack(fill="x", pady=(0, 5))
        self.queue_alert_var = tk.StringVar(value="")
        ttk.Label(self.queue_tab, textvariable=self.queue_alert_var, foreground="#9a5b00").pack(fill="x")
        self.queue_dest_notebook = ttk.Notebook(self.queue_tab)
        self.queue_dest_notebook.pack(fill="both", expand=True, pady=(5, 0))
        self.queue_dest_notebook.bind("<<NotebookTabChanged>>", self._queue_destination_changed)
        self._rebuild_queue_destination_tabs()

    def _make_queue_tree(self, parent) -> ttk.Treeview:
        columns = ("id", "title", "schedule", "status", "error")
        tree = ttk.Treeview(parent, columns=columns, show="headings", selectmode="extended")
        for column, title, width in (
            ("id", "ID", 70),
            ("title", "Матеріал", 560),
            ("schedule", "Час", 170),
            ("status", "Статус", 130),
            ("error", "Помилка", 420),
        ):
            tree.heading(column, text=title)
            tree.column(column, width=width, anchor="w", stretch=(column in {"title", "error"}))
        tree.pack(fill="both", expand=True)
        tree.bind("<Double-1>", lambda _event: self.open_selected_batch())
        tree.bind("<Delete>", self._delete_selected_queue_rows)
        return tree

    def _rebuild_queue_destination_tabs(self) -> None:
        if not hasattr(self, "queue_dest_notebook"):
            return
        for tab in self.queue_dest_notebook.tabs():
            self.queue_dest_notebook.forget(tab)
        self.queue_trees = {}
        for key, label in [("__all__", "Усі"), *[(row.key, self._short_destination_label(row.key)) for row in self._destination_specs()]]:
            frame = ttk.Frame(self.queue_dest_notebook, padding=4)
            self.queue_dest_notebook.add(frame, text=label)
            self.queue_trees[key] = self._make_queue_tree(frame)
        self.queue_tree = self.queue_trees.get("__all__") or next(iter(self.queue_trees.values()))

    def _active_queue_key(self) -> str:
        selected = self.queue_dest_notebook.select() if hasattr(self, "queue_dest_notebook") else ""
        for key, tree in self.queue_trees.items():
            if str(tree.master) == selected:
                return key
        return "__all__"

    def _queue_destination_changed(self, _event=None) -> None:
        key = self._active_queue_key()
        self.queue_tree = self.queue_trees.get(key, self.queue_trees.get("__all__"))
        self._update_queue_summary()

    def refresh_queue(self) -> None:
        if not hasattr(self, "queue_trees"):
            return
        for tree in self.queue_trees.values():
            tree.delete(*tree.get_children())
        labels = self._destination_labels()
        batches = self.db.list_batches(limit=5000, statuses={"pending", "in_progress", "paused"})
        titles = self.db.group_labels_for_batches(batch.id for batch in batches)
        for batch in reversed(batches):
            for target in batch.targets:
                key = target.platform
                title = titles.get(batch.id, "Матеріал без редакційного заголовка")
                when, parsed = legacy_ui._format_kyiv_schedule(batch.scheduled_at)
                status = legacy_ui.BATCH_STATUS_LABELS.get(batch.status, batch.status)
                error = " ".join(str(target.last_error or "").split())
                if len(error) > 300:
                    error = error[:299] + "…"
                values = (batch.id, title, when + " (Київ)", status, error or "—")
                all_tree = self.queue_trees.get("__all__")
                if all_tree is not None:
                    all_tree.insert("", "end", iid=str(batch.id), values=values)
                tree = self.queue_trees.get(key)
                if tree is not None:
                    tree.insert("", "end", iid=str(batch.id), values=values)
        self._update_queue_summary()

    def _update_queue_summary(self) -> None:
        if not hasattr(self, "queue_summary_var"):
            return
        key = self._active_queue_key() if hasattr(self, "queue_dest_notebook") else "__all__"
        batches = self.db.list_batches(limit=5000, statuses={"pending", "in_progress", "paused"})
        if key != "__all__":
            batches = [batch for batch in batches if any(target.platform == key for target in batch.targets)]
        pending = sum(batch.status == "pending" for batch in batches)
        publishing = sum(batch.status == "in_progress" for batch in batches)
        paused = sum(batch.status == "paused" for batch in batches)
        if key == "__all__":
            self.queue_summary_var.set(
                f"Усі потоки: очікує {pending} · публікується {publishing} · призупинено {paused}"
            )
            return
        future = []
        now = datetime.now(KYIV)
        for batch in batches:
            parsed = parse_iso(batch.scheduled_at)
            if parsed is not None and parsed.astimezone(KYIV) >= now:
                future.append(parsed.astimezone(KYIV))
        next_text = min(future).strftime("%d.%m %H:%M") if future else "немає"
        self.queue_summary_var.set(
            f"{self._short_destination_label(key)}: у черзі {pending} · публікується {publishing} · наступна {next_text}"
        )

    # ------------------------------------------------------------------
    # History UI: one tab and one row per destination attempt.
    # ------------------------------------------------------------------
    def _build_history_tab(self) -> None:
        self.history_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.history_tab, text="Історія публікацій")
        actions = ttk.Frame(self.history_tab)
        actions.pack(fill="x", pady=(0, 6))
        ttk.Button(actions, text="Оновити", command=self.refresh_history).pack(side="left")
        self.history_refresh_selected_button = ttk.Button(
            actions, text="Оновити статистику вибраної", command=self.refresh_selected_history_metrics
        )
        self.history_refresh_selected_button.pack(side="left", padx=6)
        self.history_refresh_all_button = ttk.Button(
            actions, text="Оновити статистику за 7 діб", command=self.refresh_all_history_metrics
        )
        self.history_refresh_all_button.pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Відкрити допис", command=self.open_history_post).pack(side="left")
        self.operation_buttons.extend([self.history_refresh_selected_button, self.history_refresh_all_button])
        self.history_summary_var = tk.StringVar(value="Історія: завантаження…")
        ttk.Label(actions, textvariable=self.history_summary_var, foreground="#555").pack(side="right")

        pane = ttk.Panedwindow(self.history_tab, orient="vertical")
        pane.pack(fill="both", expand=True)
        top = ttk.Frame(pane)
        bottom = ttk.Frame(pane)
        pane.add(top, weight=3)
        pane.add(bottom, weight=2)
        self.history_dest_notebook = ttk.Notebook(top)
        self.history_dest_notebook.pack(fill="both", expand=True)
        self.history_dest_notebook.bind("<<NotebookTabChanged>>", self._history_destination_changed)
        self._rebuild_history_destination_tabs()
        ttk.Label(bottom, text="Текст і результат публікації").pack(anchor="w", pady=(6, 2))
        self.history_details = ScrolledText(bottom, wrap="word", height=12)
        self.history_details.pack(fill="both", expand=True)
        self.history_details.configure(state="disabled")

    def _make_history_tree(self, parent) -> ttk.Treeview:
        columns = ("title", "published", "status", "views", "likes", "shares", "comments", "error")
        tree = ttk.Treeview(parent, columns=columns, show="headings", selectmode="browse")
        definitions = (
            ("title", "Матеріал", 500),
            ("published", "Дата і час", 155),
            ("status", "Статус", 175),
            ("views", "Перегляди", 85),
            ("likes", "Реакції", 80),
            ("shares", "Репости", 80),
            ("comments", "Коментарі", 90),
            ("error", "Помилка", 360),
        )
        for column, title, width in definitions:
            tree.heading(column, text=title)
            tree.column(column, width=width, anchor="w", stretch=(column in {"title", "error"}))
        tree.pack(fill="both", expand=True)
        tree.bind("<<TreeviewSelect>>", lambda _event: self.show_history_details())
        tree.bind("<Double-1>", lambda _event: self.open_history_post())
        return tree

    def _rebuild_history_destination_tabs(self) -> None:
        if not hasattr(self, "history_dest_notebook"):
            return
        for tab in self.history_dest_notebook.tabs():
            self.history_dest_notebook.forget(tab)
        self.history_trees = {}
        for key, label in [("__all__", "Усі"), *[(row.key, self._short_destination_label(row.key)) for row in self._destination_specs()]]:
            frame = ttk.Frame(self.history_dest_notebook, padding=4)
            self.history_dest_notebook.add(frame, text=label)
            self.history_trees[key] = self._make_history_tree(frame)
        self.history_tree = self.history_trees.get("__all__") or next(iter(self.history_trees.values()))

    def _active_history_key(self) -> str:
        selected = self.history_dest_notebook.select() if hasattr(self, "history_dest_notebook") else ""
        for key, tree in self.history_trees.items():
            if str(tree.master) == selected:
                return key
        return "__all__"

    def _history_destination_changed(self, _event=None) -> None:
        key = self._active_history_key()
        self.history_tree = self.history_trees.get(key, self.history_trees.get("__all__"))
        self.show_history_details()

    def _refresh_destination_views(self, *, rebuild: bool = False) -> None:
        if rebuild:
            self._rebuild_queue_destination_tabs()
            self._rebuild_history_destination_tabs()
        self.refresh_queue()
        self.refresh_history()

    def refresh_history(self) -> None:
        if not hasattr(self, "history_trees"):
            return
        for tree in self.history_trees.values():
            tree.delete(*tree.get_children())
        self.history_rows = {}
        rows = self.db.list_publication_history(limit=5000)
        for row in rows:
            targets = row.get("targets") if isinstance(row.get("targets"), list) else []
            for target in targets:
                if not isinstance(target, dict):
                    continue
                target_id = int(target.get("id") or 0)
                if target_id <= 0:
                    continue
                platform = str(target.get("platform") or "")
                progress = target.get("progress") if isinstance(target.get("progress"), dict) else {}
                metrics = progress.get("metrics") if isinstance(progress.get("metrics"), dict) else {}
                status = str(target.get("status") or "")
                status_text = "Опубліковано" if status == "sent" else "Завершено з помилкою"
                terminal_raw = str(target.get("updated_at") or row.get("published_at") or row.get("scheduled_at") or "")
                terminal, _ = legacy_ui._format_kyiv_schedule(terminal_raw)
                error = " ".join(str(target.get("last_error") or "").split())
                short_error = error if len(error) <= 280 else error[:279] + "…"
                values = (
                    str(row.get("display_title") or row.get("headline") or ""),
                    terminal,
                    status_text,
                    int(metrics.get("views") or 0) if metrics else "—",
                    int(metrics.get("likes") or metrics.get("reactions") or 0) if metrics else "—",
                    int(metrics.get("shares") or metrics.get("reposts") or metrics.get("quotes") or 0) if metrics else "—",
                    int(metrics.get("comments") or metrics.get("replies") or 0) if metrics else "—",
                    short_error or "—",
                )
                pseudo = dict(row)
                pseudo["targets"] = [target]
                pseudo["destination"] = platform
                self.history_rows[target_id] = pseudo
                all_tree = self.history_trees.get("__all__")
                if all_tree is not None:
                    all_tree.insert("", "end", iid=str(target_id), values=values)
                tree = self.history_trees.get(platform)
                if tree is not None:
                    tree.insert("", "end", iid=str(target_id), values=values)
        self.history_summary_var.set(f"Завершених публікацій / спроб за 7 діб: {len(self.history_rows)}")
        self.show_history_details()

    def _selected_history_row(self) -> dict[str, object] | None:
        tree = getattr(self, "history_tree", None)
        selected = tree.selection() if tree is not None else ()
        return self.history_rows.get(int(selected[0])) if selected else None

    def show_history_details(self) -> None:
        if not hasattr(self, "history_details"):
            return
        row = self._selected_history_row()
        lines: list[str] = []
        if row:
            lines.append(str(row.get("display_title") or row.get("headline") or ""))
            lines.extend(["", str(row.get("rewrite_text") or ""), ""])
            target = (row.get("targets") or [{}])[0]  # type: ignore[index]
            if isinstance(target, dict):
                platform = str(target.get("platform") or "")
                lines.append("ПОТІК: " + self._destination_labels().get(platform, platform))
                lines.append("СТАТУС: " + ("Опубліковано" if target.get("status") == "sent" else "Завершено з помилкою"))
                if target.get("remote_id"):
                    lines.append("REMOTE ID: " + str(target.get("remote_id")))
                if target.get("last_error"):
                    lines.append("ПОМИЛКА: " + str(target.get("last_error")))
        self.history_details.configure(state="normal")
        self.history_details.delete("1.0", "end")
        self.history_details.insert("1.0", "\n".join(lines))
        self.history_details.configure(state="disabled")

    # ------------------------------------------------------------------
    # Terminal errors are history, not a retry invitation.
    # ------------------------------------------------------------------
    def _show_worker_result(self, value: object) -> None:
        self.refresh_queue()
        self.refresh_history()
        if not isinstance(value, WorkerResult):
            return
        if value.busy:
            self.msg.showinfo("Черга", "Попередній мережевий запит ще завершується.", parent=self.root)
            return
        if not value.claimed:
            self.msg.showinfo("Черга", "Немає публікації, час якої вже настав.", parent=self.root)
            return
        labels = self._destination_labels()
        lines = [f"Завдання #{value.batch_id} завершено."]
        if value.sent_platforms:
            lines.append("Опубліковано: " + ", ".join(labels.get(key, key) for key in value.sent_platforms))
        if value.failed_platforms:
            lines.append("Завершено з помилкою і перенесено в історію:")
            for key, error in value.failed_platforms.items():
                lines.append(f"• {labels.get(key, key)}: {error}")
            lines.append("Автоматичного повтору не буде.")
        self.msg.showwarning("Результат публікації", "\n\n".join(lines), parent=self.root) if value.failed_platforms else self.msg.showinfo(
            "Результат публікації", "\n\n".join(lines), parent=self.root
        )

    def resume_selected_batch(self) -> None:
        self.msg.showinfo(
            "Черга",
            "У v1.4 помилка публікації є фінальним результатом і переходить в історію. Автоматичні повтори вимкнено.",
            parent=self.root,
        )

    def reschedule_interrupted_batches(self) -> None:
        self.msg.showinfo(
            "Черга",
            "У v1.4 кожен потік має власний розклад. Перервані спроби не перепубліковуються автоматично.",
            parent=self.root,
        )

    def load_group(self, group_id: int) -> None:
        super().load_group(group_id)
        group = self.db.get_group(group_id)
        if group.media_file_id:
            self.media_status_var.set(
                f"{group.media_kind.upper()}: {group.media_name}, {group.media_size / (1024 * 1024):.1f} МБ. "
                "Файл буде видалено з Drive лише після завершення всіх вибраних потоків."
            )

    def _finish_startup_maintenance(self, recovered: list[int], stale: int, archived: int) -> None:
        # In v1.4 recovered in-progress jobs are terminalized as unknown outcomes,
        # not put back into a retry queue.
        super()._finish_startup_maintenance([], stale, archived)
        if recovered:
            self.status_var.set(
                "Перервані попередні спроби перенесено в історію без повтору: "
                + ", ".join(f"#{item}" for item in recovered[:12])
            )
