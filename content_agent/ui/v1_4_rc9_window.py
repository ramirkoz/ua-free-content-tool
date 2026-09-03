from __future__ import annotations

import logging
import tkinter as tk
from datetime import datetime
from tkinter import ttk

from ..scheduling import KYIV, next_publish_slot, parse_iso
from ..source_management_v1_4_rc9 import SOURCE_KIND_CHOICES, detect_source_kind, resolve_source_kind
from .v1_4_rc8_window import MainWindow as Rc8MainWindow


logger = logging.getLogger("content_agent.ui.v14_rc9")


class MainWindow(Rc8MainWindow):
    """v1.4.0-rc9: editable sources and authoritative per-destination schedules."""

    VERSION_LABEL = "1.4.0-rc9"

    def __init__(self, root: tk.Tk, database, config) -> None:
        super().__init__(root, database, config)
        self._materialize_destination_schedules()
        self._rebuild_destination_schedule_rows()
        self._apply_v14_labels()

    def _apply_v14_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v1.4.0-rc9")

    # ------------------------------------------------------------------
    # Source management.
    # ------------------------------------------------------------------
    def _build_sources_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Джерела")

        form = ttk.Frame(tab)
        form.pack(fill="x")
        self.source_kind = tk.StringVar(value="auto")
        self.source_name = tk.StringVar()
        self.source_url = tk.StringVar()
        ttk.Label(form, text="Тип").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            form,
            textvariable=self.source_kind,
            values=SOURCE_KIND_CHOICES,
            state="readonly",
            width=12,
        ).grid(row=1, column=0, padx=(0, 8), sticky="ew")
        ttk.Label(form, text="Назва").grid(row=0, column=1, sticky="w")
        ttk.Entry(form, textvariable=self.source_name, width=28).grid(row=1, column=1, padx=(0, 8), sticky="ew")
        ttk.Label(form, text="URL або @telegram_channel").grid(row=0, column=2, sticky="w")
        ttk.Entry(form, textvariable=self.source_url).grid(row=1, column=2, padx=(0, 8), sticky="ew")
        ttk.Button(form, text="Додати", command=self.add_source).grid(row=1, column=3, padx=4)
        form.columnconfigure(2, weight=1)

        buttons = ttk.Frame(tab)
        buttons.pack(fill="x", pady=(10, 4))
        ttk.Button(buttons, text="Оновити список", command=self.refresh_sources).pack(side="left")
        ttk.Button(buttons, text="Редагувати", command=self.edit_source).pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="Видалити", command=self.delete_source).pack(side="left", padx=6)
        self.auto_collect_status_var = tk.StringVar(
            value="Автоматичне оновлення: після запуску і кожні 5 хвилин"
        )
        ttk.Label(buttons, textvariable=self.auto_collect_status_var, foreground="#555").pack(side="right")

        ttk.Label(
            tab,
            text=(
                "Тип «auto» визначає Telegram/RSS/URL за адресою. "
                "Вибір: Shift — діапазон, Ctrl — окремі рядки, Ctrl+A — усі, Delete — видалення. "
                "Подвійний клік — редагування."
            ),
            foreground="#555",
        ).pack(fill="x", pady=(0, 5))

        columns = ("id", "kind", "name", "url", "checked")
        self.sources_tree = ttk.Treeview(tab, columns=columns, show="headings", selectmode="extended")
        widths = {"id": 60, "kind": 100, "name": 240, "url": 560, "checked": 180}
        labels = {"id": "ID", "kind": "Тип", "name": "Назва", "url": "Адреса", "checked": "Остання перевірка"}
        for column in columns:
            self.sources_tree.heading(column, text=labels[column])
            self.sources_tree.column(column, width=widths[column], anchor="w")
        self.sources_tree.pack(fill="both", expand=True)
        self.sources_tree.bind("<Double-1>", self._edit_source_from_event)
        self.sources_tree.bind("<Delete>", self._delete_sources_from_event)
        self.sources_tree.bind("<Control-a>", self._select_all_sources)
        self.sources_tree.bind("<Control-A>", self._select_all_sources)

    def add_source(self) -> None:
        name = self.source_name.get().strip()
        url = self.source_url.get().strip()
        if not name or not url:
            self.msg.showwarning("Джерело", "Вкажіть назву та адресу.", parent=self.root)
            return
        requested = self.source_kind.get().strip().casefold() or "auto"
        kind = resolve_source_kind(url, requested)
        try:
            self.db.add_source(kind, name, url)
        except Exception as exc:
            self._show_error(exc)
            return
        self.source_kind.set("auto")
        self.source_name.set("")
        self.source_url.set("")
        self.refresh_sources()
        self.set_status(f"Джерело додано. Визначений тип: {kind}.")

    def _select_all_sources(self, _event=None) -> str:
        rows = self.sources_tree.get_children("")
        if rows:
            self.sources_tree.selection_set(rows)
            self.sources_tree.focus(rows[0])
        return "break"

    def _edit_source_from_event(self, event: tk.Event) -> str:
        row = self.sources_tree.identify_row(int(getattr(event, "y", 0)))
        if row:
            self.sources_tree.selection_set(row)
            self.sources_tree.focus(row)
            self.edit_source()
        return "break"

    def _delete_sources_from_event(self, _event=None) -> str:
        self.delete_source()
        return "break"

    def _source_by_id(self, source_id: int):
        return next((item for item in self.db.list_sources() if int(item.id or 0) == int(source_id)), None)

    def edit_source(self) -> None:
        ids = self._selected_source_ids()
        if not ids:
            self.msg.showinfo("Джерело", "Оберіть джерело для редагування.", parent=self.root)
            return
        if len(ids) != 1:
            self.msg.showinfo(
                "Джерело",
                "Для редагування оберіть один рядок. Масове видалення працює для всіх вибраних.",
                parent=self.root,
            )
            return
        source = self._source_by_id(ids[0])
        if source is None:
            self.refresh_sources()
            return

        dialog = tk.Toplevel(self.root)
        dialog.title(f"Редагування джерела #{int(source.id or 0)}")
        dialog.transient(self.root)
        dialog.resizable(True, False)
        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        kind_var = tk.StringVar(value=str(source.kind or "url"))
        name_var = tk.StringVar(value=str(source.name or ""))
        url_var = tk.StringVar(value=str(source.url or ""))
        detected_var = tk.StringVar(value=f"Автовизначення: {detect_source_kind(url_var.get())}")

        ttk.Label(frame, text="Тип").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=3)
        ttk.Combobox(
            frame,
            textvariable=kind_var,
            values=SOURCE_KIND_CHOICES,
            state="readonly",
            width=14,
        ).grid(row=0, column=1, sticky="w", pady=3)
        ttk.Label(frame, text="Назва").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=3)
        ttk.Entry(frame, textvariable=name_var, width=54).grid(row=1, column=1, sticky="ew", pady=3)
        ttk.Label(frame, text="Адреса").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=3)
        url_entry = ttk.Entry(frame, textvariable=url_var, width=72)
        url_entry.grid(row=2, column=1, sticky="ew", pady=3)
        ttk.Label(frame, textvariable=detected_var, foreground="#555").grid(
            row=3, column=1, sticky="w", pady=(0, 6)
        )

        def update_detected(*_args: object) -> None:
            detected_var.set(f"Автовизначення: {detect_source_kind(url_var.get())}")

        url_var.trace_add("write", update_detected)

        actions = ttk.Frame(frame)
        actions.grid(row=4, column=0, columnspan=2, sticky="e", pady=(7, 0))

        def save() -> None:
            name = name_var.get().strip()
            url = url_var.get().strip()
            if not name or not url:
                self.msg.showwarning("Джерело", "Вкажіть назву та адресу.", parent=dialog)
                return
            kind = resolve_source_kind(url, kind_var.get())
            try:
                self.db.update_source(int(source.id or 0), kind=kind, name=name, url=url)
            except Exception as exc:
                self.msg.showerror("UA FREE Content Tool", str(exc), parent=dialog)
                return
            dialog.destroy()
            self.refresh_sources()
            self.refresh_groups()
            self.set_status(f"Джерело #{int(source.id or 0)} оновлено. Тип: {kind}.")

        ttk.Button(actions, text="Скасувати", command=dialog.destroy).pack(side="right")
        ttk.Button(actions, text="Зберегти", command=save).pack(side="right", padx=(0, 6))
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.bind("<Control-s>", lambda _event: save())
        dialog.bind("<Control-S>", lambda _event: save())
        dialog.grab_set()
        url_entry.focus_set()

    def delete_source(self) -> None:
        ids = self._selected_source_ids()
        if not ids:
            return
        count = len(ids)
        question = (
            "Видалити вибране джерело і його матеріали?"
            if count == 1
            else f"Видалити {count} вибраних джерел і всі їхні матеріали?"
        )
        if not self.msg.askyesno("Видалення", question, parent=self.root):
            return
        try:
            deleted = self.db.delete_sources(ids)
        except Exception as exc:
            self._show_error(exc)
            return
        self.refresh_sources()
        self.refresh_groups()
        self.set_status(f"Видалено джерел: {deleted}.")

    # ------------------------------------------------------------------
    # Schedule ownership.
    # ------------------------------------------------------------------
    def _build_settings_tab(self) -> None:
        super()._build_settings_tab()
        self._remove_legacy_global_schedule_frame()

    def _remove_legacy_global_schedule_frame(self) -> None:
        """Remove the obsolete global schedule controls from the v1.4 settings UI.

        The backing legacy variables remain alive because encrypted config loading
        and validation still know about them. They are no longer presented as a
        second scheduler competing with per-destination schedules.
        """

        def walk(widget: tk.Misc) -> None:
            for child in list(widget.winfo_children()):
                try:
                    text = str(child.cget("text"))
                except (tk.TclError, AttributeError):
                    text = ""
                if isinstance(child, ttk.LabelFrame) and text == "5. Розклад":
                    child.destroy()
                    continue
                walk(child)

        walk(self.root)

    def _materialize_destination_schedules(self) -> None:
        """Turn the legacy global fallback into a one-time migration only."""

        store = getattr(self, "_destination_schedule_store", None)
        if store is None:
            return
        rows = getattr(store, "_rows", None)
        if not isinstance(rows, dict):
            return
        changed = False
        for spec in self._destination_specs():
            if spec.key in rows:
                continue
            store.set(spec.key, store.get(spec.key))
            changed = True
        if changed:
            store.save()
            logger.info("RC9 materialized per-destination schedules for all configured destinations")

    def _rebuild_destination_schedule_rows(self) -> None:
        self._materialize_destination_schedules()
        super()._rebuild_destination_schedule_rows()

    @staticmethod
    def _pending_platforms(batch) -> list[str]:
        result: list[str] = []
        for target in getattr(batch, "targets", []) or []:
            platform = str(getattr(target, "platform", "") or "").strip()
            status = str(getattr(target, "status", "") or "").strip()
            if platform and status != "sent" and platform not in result:
                result.append(platform)
        return result

    def reschedule_interrupted_batches(self) -> None:
        """Reschedule every v1.4 batch using its own destination schedule."""

        now = datetime.now(KYIV)
        recoverable = []
        for batch in self.db.list_batches(limit=5000, statuses={"paused", "pending"}):
            parsed = parse_iso(batch.scheduled_at)
            if batch.status == "paused" or (
                batch.status == "pending"
                and parsed is not None
                and parsed.astimezone(KYIV) <= now
            ):
                recoverable.append(batch)
        recoverable.sort(
            key=lambda batch: ((parse_iso(batch.scheduled_at) or datetime.min.replace(tzinfo=KYIV)), batch.id)
        )
        if not recoverable:
            self.msg.showinfo(
                "Черга",
                "Призупинених або прострочених невідправлених пакетів немає.",
                parent=self.root,
            )
            return

        paused_count = sum(batch.status == "paused" for batch in recoverable)
        overdue_count = len(recoverable) - paused_count
        if not self.msg.askyesno(
            "Відновлення розкладу",
            f"Перепланувати {len(recoverable)} пакетів за окремими розкладами їхніх профілів?\n\n"
            f"Призупинено: {paused_count}. Прострочено: {overdue_count}.\n\n"
            "Кожен профіль, сторінка і канал використовує тільки власні години та інтервал.",
            parent=self.root,
        ):
            return

        recovery_ids = {batch.id for batch in recoverable}
        latest_by_target: dict[str, datetime] = {}
        for batch in self.db.list_batches(limit=5000, statuses={"pending", "in_progress"}):
            if batch.id in recovery_ids:
                continue
            parsed = parse_iso(batch.scheduled_at)
            if parsed is None:
                continue
            when = parsed.astimezone(KYIV)
            if when <= now:
                continue
            for platform in self._pending_platforms(batch):
                previous = latest_by_target.get(platform)
                if previous is None or when > previous:
                    latest_by_target[platform] = when

        schedules: dict[int, str] = {}
        skipped_legacy: list[int] = []
        for batch in recoverable:
            platforms = self._pending_platforms(batch)
            if len(platforms) != 1:
                # v1.4 creates one batch per destination. A pre-v1.4 multi-target
                # batch cannot honestly satisfy several independent clocks at once.
                skipped_legacy.append(int(batch.id))
                continue
            platform = platforms[0]
            rule = self._destination_schedule_store.get(platform)
            slot = next_publish_slot(
                now=now,
                latest_scheduled=latest_by_target.get(platform),
                start_hour=rule.start_hour,
                end_hour=rule.end_hour,
                interval_minutes=rule.interval_minutes,
            )
            schedules[int(batch.id)] = slot.isoformat(timespec="seconds")
            latest_by_target[platform] = slot
            logger.info(
                "RC9 reschedule batch=%s target=%s slot=%s rule=%02d-%02d/%dmin",
                batch.id,
                platform,
                slot.isoformat(timespec="seconds"),
                rule.start_hour,
                rule.end_hour,
                rule.interval_minutes,
            )

        if not schedules:
            self.msg.showwarning(
                "Відновлення розкладу",
                "Немає пакетів v1.4, які можна безпечно перепланувати по окремих профілях.",
                parent=self.root,
            )
            return
        try:
            resumed = self.db.reschedule_recoverable_batches(schedules)
            if hasattr(self, "worker"):
                self.worker.wake()
        except Exception as exc:
            self._show_error(exc)
            return
        self.refresh_queue()
        message = f"Переплановано за окремими профільними розкладами: {resumed}."
        if skipped_legacy:
            message += " Старі багатопрофільні пакети не чіпав: " + ", ".join(
                f"#{batch_id}" for batch_id in skipped_legacy[:20]
            )
        self.set_status(message)
        self.msg.showinfo("Відновлення розкладу", message, parent=self.root)
