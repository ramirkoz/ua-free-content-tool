from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import tkinter as tk
from tkinter import simpledialog, ttk
from tkinter.scrolledtext import ScrolledText

from ..destinations_v1_4 import DestinationSpec, destination_ready, normalize_legacy_target_keys
from ..paths import data_dir
from ..scheduling import KYIV, parse_iso
from ..topic_classifier_v1_4_rc4 import TOPIC_CATEGORIES, TopicAssignmentStore
from . import main_window as legacy_ui
from .v1_4_rc3_window import MainWindow as Rc3MainWindow


_PLATFORM_NAMES = {
    "facebook": "Facebook",
    "instagram": "Instagram",
    "threads": "Threads",
    "linkedin": "LinkedIn",
    "telegram": "Telegram",
}


def _logical_platform(key: str) -> str:
    value = str(key or "")
    if value.startswith("facebook:"):
        return "facebook"
    if value.startswith("instagram:"):
        return "instagram"
    return value


def _decorate_destination_label(label: str, platform: str) -> str:
    clean = str(label or "").strip()
    logical = _logical_platform(platform)
    network = _PLATFORM_NAMES.get(logical, logical or "Профіль")
    suffix = f" ({network})"
    if clean.endswith(suffix):
        return clean
    return (clean or network) + suffix


def _display_period(values: list[str]) -> str:
    parsed = [parse_iso(value) for value in values if value]
    moments = [value.astimezone(KYIV) for value in parsed if value is not None]
    if not moments:
        return "—"
    first = min(moments)
    last = max(moments)
    if first == last:
        return first.strftime("%d.%m.%Y %H:%M")
    if first.date() == last.date():
        return first.strftime("%d.%m.%Y %H:%M") + "–" + last.strftime("%H:%M")
    return first.strftime("%d.%m %H:%M") + " – " + last.strftime("%d.%m %H:%M")


class MainWindow(Rc3MainWindow):
    """v1.4.0-rc4: editorial-first UI over independent destination queues."""

    VERSION_LABEL = "1.4.0-rc4"

    def __init__(self, root, database, config) -> None:
        self._topic_store = TopicAssignmentStore(data_dir() / "topic_assignments_v1_4_rc4.json")
        self._topic_decisions: dict[int, object] = {}
        self._last_targets_save_after_id: str | None = None
        self._queue_group_details: dict[int, list[dict[str, object]]] = {}
        self._history_group_details: dict[int, list[dict[str, object]]] = {}
        super().__init__(root, database, config)
        self._install_rc4_inbox()
        self._restore_last_target_selection()
        self._apply_v14_labels()
        self.refresh_groups()
        self.refresh_queue()
        self.refresh_history()

    def _apply_v14_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v1.4.0-rc4")

    # ------------------------------------------------------------------
    # Destination labels and last-used target set.
    # ------------------------------------------------------------------
    def _destination_specs(self):
        result: list[DestinationSpec] = []
        for spec in super()._destination_specs():
            result.append(
                DestinationSpec(
                    key=spec.key,
                    label=_decorate_destination_label(spec.label, spec.platform),
                    platform=spec.platform,
                )
            )
        return result

    def _destination_labels(self) -> dict[str, str]:
        return {spec.key: spec.label for spec in self._destination_specs()}

    def _restore_last_target_selection(self) -> None:
        state = getattr(self, "_target_preset_state", None)
        if state is None:
            return
        keys = list(getattr(state, "last_targets", []) or [])
        if not keys:
            return
        self._apply_target_keys(normalize_legacy_target_keys(self.config, keys))
        if hasattr(self, "_refresh_target_preset_controls"):
            try:
                self._refresh_target_preset_controls(self._matching_current_target_preset_label())
            except Exception:
                pass

    def _update_selected_targets_summary(self) -> None:
        super()._update_selected_targets_summary()
        if getattr(self, "_target_preset_syncing", True):
            return
        if not hasattr(self, "root"):
            return
        if self._last_targets_save_after_id is not None:
            try:
                self.root.after_cancel(self._last_targets_save_after_id)
            except tk.TclError:
                pass
        self._last_targets_save_after_id = self.root.after(350, self._persist_live_target_selection)

    def _persist_live_target_selection(self) -> None:
        self._last_targets_save_after_id = None
        selected = [key for key, variable in getattr(self, "target_vars", {}).items() if variable.get()]
        if not selected or not hasattr(self, "_remember_last_target_selection"):
            return
        try:
            self._remember_last_target_selection(selected)
        except Exception:
            pass

    def _update_target_preset_status(self, intended: list[str] | None = None) -> None:
        status = getattr(self, "target_preset_status_var", None)
        if status is None:
            return
        keys = intended
        if keys is None:
            choice = self.target_preset_var.get().strip()
            if choice == "Останній вибір":
                keys = list(getattr(self._target_preset_state, "last_targets", []) or [])
            elif choice in getattr(self._target_preset_state, "presets", {}):
                keys = list(self._target_preset_state.presets[choice])
            else:
                keys = [key for key, variable in self.target_vars.items() if variable.get()]
        normalized = normalize_legacy_target_keys(self.config, keys or [])
        unavailable = [key for key in normalized if key not in self.target_vars or not destination_ready(self.config, key)]
        if unavailable:
            names = ", ".join(self._destination_labels().get(key, key) for key in unavailable)
            status.set(f"У наборі зараз недоступні: {names}")
        elif normalized:
            status.set(f"У наборі мереж: {len(normalized)}")
        else:
            status.set("Набір ще не сформований")

    # ------------------------------------------------------------------
    # Inbox: no internal group numbers; topic is a stable event classification.
    # ------------------------------------------------------------------
    def _install_rc4_inbox(self) -> None:
        tree = getattr(self, "groups_tree", None)
        if tree is None:
            return
        columns = tuple(str(value) for value in tree.cget("columns"))
        wanted = tuple(
            column
            for column in ("status", "title", "topic", "sources", "published", "score", "history")
            if column in columns
        )
        if wanted:
            tree.configure(displaycolumns=wanted)
        tree.bind("<Double-1>", self._rc4_topic_double_click, add="+")

    def refresh_groups(self) -> None:
        super().refresh_groups()
        tree = getattr(self, "groups_tree", None)
        if tree is None or "topic" not in tuple(tree.cget("columns")):
            return
        group_ids: list[int] = []
        for item_id in tree.get_children(""):
            try:
                group_ids.append(int(item_id))
            except (TypeError, ValueError):
                continue
        if not group_ids or not hasattr(self.db, "topic_contexts"):
            return
        try:
            contexts = self.db.topic_contexts(group_ids)
        except Exception:
            return
        changed = False
        for group_id in group_ids:
            context = contexts.get(group_id)
            if not context:
                continue
            decision, row_changed = self._topic_store.resolve(group_id, context)
            changed = changed or row_changed
            self._topic_decisions[group_id] = decision
            if tree.exists(str(group_id)):
                tree.set(str(group_id), "topic", decision.topic)
        if changed:
            try:
                self._topic_store.save()
            except OSError:
                pass
        if hasattr(self, "_apply_inbox_sort"):
            try:
                self._apply_inbox_sort()
            except Exception:
                pass

    def _rc4_topic_double_click(self, event: tk.Event) -> str | None:
        tree = getattr(self, "groups_tree", None)
        if tree is None:
            return None
        try:
            if tree.identify_region(event.x, event.y) != "cell":
                return None
            iid = tree.identify_row(event.y)
            token = tree.identify_column(event.x)
            display = tuple(str(value) for value in tree.cget("displaycolumns"))
            if display == ("#all",):
                display = tuple(str(value) for value in tree.cget("columns"))
            index = int(str(token).lstrip("#")) - 1
            if not iid or index < 0 or index >= len(display) or display[index] != "topic":
                return None
            group_id = int(iid)
        except (tk.TclError, TypeError, ValueError):
            return None

        current = tree.set(iid, "topic") or "Інше"
        options = ", ".join(TOPIC_CATEGORIES)
        value = simpledialog.askstring(
            "Тема матеріалу",
            "Вкажіть основну тему.\n\n" + options + "\n\nНапишіть «Авто», щоб повернути автоматичну класифікацію.",
            initialvalue=current,
            parent=self.root,
        )
        if value is None:
            return "break"
        value = value.strip()
        if value.casefold() == "авто":
            self._topic_store.clear_manual(group_id)
            self.refresh_groups()
            return "break"
        match = next((topic for topic in TOPIC_CATEGORIES if topic.casefold() == value.casefold()), None)
        if match is None:
            self.msg.showwarning("Тема матеріалу", "Оберіть одну зі стандартних тем: " + options, parent=self.root)
            return "break"
        self._topic_store.set_manual(group_id, match)
        self.refresh_groups()
        return "break"

    # ------------------------------------------------------------------
    # Queue: one story in the overview, independent destination tasks below.
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

        pane = ttk.Panedwindow(self.queue_tab, orient="vertical")
        pane.pack(fill="both", expand=True, pady=(5, 0))
        top = ttk.Frame(pane)
        bottom = ttk.Frame(pane)
        pane.add(top, weight=3)
        pane.add(bottom, weight=2)

        self.queue_overview_tree = ttk.Treeview(
            top,
            columns=("title", "next", "state"),
            show="headings",
            selectmode="browse",
        )
        for column, title, width in (
            ("title", "Матеріал", 850),
            ("next", "Наступна публікація", 190),
            ("state", "Стан", 260),
        ):
            self.queue_overview_tree.heading(column, text=title)
            self.queue_overview_tree.column(column, width=width, anchor="w", stretch=(column == "title"))
        self.queue_overview_tree.pack(fill="both", expand=True)
        self.queue_overview_tree.bind("<<TreeviewSelect>>", self._queue_overview_selected)

        ttk.Label(bottom, text="Публікації цього матеріалу", font="TkHeadingFont").pack(anchor="w", pady=(6, 3))
        self.queue_detail_tree = ttk.Treeview(
            bottom,
            columns=("profile", "network", "schedule", "status", "error"),
            show="headings",
            selectmode="extended",
        )
        for column, title, width in (
            ("profile", "Профіль / сторінка", 320),
            ("network", "Мережа", 110),
            ("schedule", "Час", 175),
            ("status", "Статус", 150),
            ("error", "Помилка", 500),
        ):
            self.queue_detail_tree.heading(column, text=title)
            self.queue_detail_tree.column(column, width=width, anchor="w", stretch=(column in {"profile", "error"}))
        self.queue_detail_tree.pack(fill="both", expand=True)
        self.queue_detail_tree.bind("<Double-1>", lambda _event: self.open_selected_batch())
        self.queue_detail_tree.bind("<Delete>", self._delete_selected_queue_rows)
        # Legacy queue actions expect the selected tree to contain batch ids.
        self.queue_tree = self.queue_detail_tree

    def refresh_queue(self) -> None:
        overview = getattr(self, "queue_overview_tree", None)
        detail = getattr(self, "queue_detail_tree", None)
        if overview is None or detail is None:
            return
        selected_group = self._selected_overview_group(overview)
        overview.delete(*overview.get_children())
        detail.delete(*detail.get_children())
        self._queue_group_details = {}

        batches = self.db.list_batches(limit=5000, statuses={"pending", "in_progress", "paused"})
        titles = self.db.group_labels_for_batches(batch.id for batch in batches)
        group_map = self.db.group_ids_for_batches(batch.id for batch in batches) if hasattr(self.db, "group_ids_for_batches") else {}
        grouped: dict[int, list[dict[str, object]]] = defaultdict(list)
        for batch in batches:
            group_id = int(group_map.get(batch.id) or 0)
            if group_id <= 0:
                continue
            for target in batch.targets:
                grouped[group_id].append(
                    {
                        "batch_id": int(batch.id),
                        "title": titles.get(batch.id, "Матеріал без редакційного заголовка"),
                        "platform": str(target.platform),
                        "scheduled_at": str(batch.scheduled_at),
                        "batch_status": str(batch.status),
                        "target_status": str(target.status),
                        "error": " ".join(str(target.last_error or "").split()),
                    }
                )

        ordered = sorted(
            grouped.items(),
            key=lambda item: min(
                (parse_iso(str(row.get("scheduled_at") or "")) or datetime.max.replace(tzinfo=KYIV) for row in item[1]),
                default=datetime.max.replace(tzinfo=KYIV),
            ),
        )
        for group_id, rows in ordered:
            self._queue_group_details[group_id] = rows
            title = str(rows[0].get("title") or "Матеріал без редакційного заголовка")
            moments = [parse_iso(str(row.get("scheduled_at") or "")) for row in rows]
            valid = [moment.astimezone(KYIV) for moment in moments if moment is not None]
            next_text = min(valid).strftime("%d.%m.%Y %H:%M") if valid else "—"
            pending = sum(str(row.get("batch_status")) == "pending" for row in rows)
            publishing = sum(str(row.get("batch_status")) == "in_progress" for row in rows)
            paused = sum(str(row.get("batch_status")) == "paused" for row in rows)
            parts = []
            if pending:
                parts.append(f"{pending} очікує")
            if publishing:
                parts.append(f"{publishing} публікується")
            if paused:
                parts.append(f"{paused} призупинено")
            overview.insert("", "end", iid=f"group:{group_id}", values=(title, next_text, " · ".join(parts) or "—"))

        attempts = sum(len(rows) for rows in grouped.values())
        self.queue_summary_var.set(f"Матеріалів у черзі: {len(grouped)} · окремих публікацій: {attempts}")
        children = overview.get_children()
        wanted = f"group:{selected_group}" if selected_group and overview.exists(f"group:{selected_group}") else (children[0] if children else "")
        if wanted:
            overview.selection_set(wanted)
            overview.focus(wanted)
            overview.see(wanted)
        self._populate_queue_details()

    @staticmethod
    def _selected_overview_group(tree: ttk.Treeview) -> int | None:
        selected = tree.selection()
        if not selected:
            return None
        value = str(selected[0])
        if not value.startswith("group:"):
            return None
        try:
            return int(value.split(":", 1)[1])
        except ValueError:
            return None

    def _queue_overview_selected(self, _event: object | None = None) -> None:
        self._populate_queue_details()

    def _populate_queue_details(self) -> None:
        overview = getattr(self, "queue_overview_tree", None)
        detail = getattr(self, "queue_detail_tree", None)
        if overview is None or detail is None:
            return
        detail.delete(*detail.get_children())
        group_id = self._selected_overview_group(overview)
        if group_id is None:
            return
        labels = self._destination_labels()
        for row in self._queue_group_details.get(group_id, []):
            batch_id = int(row.get("batch_id") or 0)
            platform = str(row.get("platform") or "")
            label = labels.get(platform, platform)
            profile, network = self._split_destination(label, platform)
            when, _ = legacy_ui._format_kyiv_schedule(str(row.get("scheduled_at") or ""))
            status = legacy_ui.BATCH_STATUS_LABELS.get(str(row.get("batch_status") or ""), str(row.get("batch_status") or ""))
            error = str(row.get("error") or "")
            if len(error) > 360:
                error = error[:359] + "…"
            detail.insert("", "end", iid=str(batch_id), values=(profile, network, when + " (Київ)", status, error or "—"))
        children = detail.get_children()
        if children:
            detail.selection_set(children[0])
            detail.focus(children[0])

    def _update_queue_summary(self) -> None:
        # refresh_queue owns the grouped summary in RC4.
        return

    # ------------------------------------------------------------------
    # History: one story in the overview, destination results and metrics below.
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
        pane.add(bottom, weight=3)

        self.history_overview_tree = ttk.Treeview(
            top,
            columns=("title", "period", "result"),
            show="headings",
            selectmode="browse",
        )
        for column, title, width in (
            ("title", "Матеріал", 900),
            ("period", "Публікації", 230),
            ("result", "Результат", 240),
        ):
            self.history_overview_tree.heading(column, text=title)
            self.history_overview_tree.column(column, width=width, anchor="w", stretch=(column == "title"))
        self.history_overview_tree.pack(fill="both", expand=True)
        self.history_overview_tree.bind("<<TreeviewSelect>>", self._history_overview_selected)

        ttk.Label(bottom, text="Розкладка по мережах", font="TkHeadingFont").pack(anchor="w", pady=(6, 3))
        self.history_detail_tree = ttk.Treeview(
            bottom,
            columns=("profile", "network", "published", "status", "views", "likes", "shares", "comments", "error"),
            show="headings",
            selectmode="browse",
            height=7,
        )
        definitions = (
            ("profile", "Профіль / сторінка", 280),
            ("network", "Мережа", 100),
            ("published", "Час", 160),
            ("status", "Статус", 160),
            ("views", "Перегляди", 85),
            ("likes", "Реакції", 80),
            ("shares", "Репости", 80),
            ("comments", "Коментарі", 90),
            ("error", "Помилка", 360),
        )
        for column, title, width in definitions:
            self.history_detail_tree.heading(column, text=title)
            self.history_detail_tree.column(column, width=width, anchor="w", stretch=(column in {"profile", "error"}))
        self.history_detail_tree.pack(fill="both", expand=True)
        self.history_detail_tree.bind("<<TreeviewSelect>>", lambda _event: self.show_history_details())
        self.history_detail_tree.bind("<Double-1>", lambda _event: self.open_history_post())
        self.history_tree = self.history_detail_tree

        ttk.Label(bottom, text="Текст і результат вибраної публікації").pack(anchor="w", pady=(6, 2))
        self.history_details = ScrolledText(bottom, wrap="word", height=7)
        self.history_details.pack(fill="both", expand=True)
        self.history_details.configure(state="disabled")

    def refresh_history(self) -> None:
        overview = getattr(self, "history_overview_tree", None)
        detail = getattr(self, "history_detail_tree", None)
        if overview is None or detail is None:
            return
        selected_group = self._selected_overview_group(overview)
        overview.delete(*overview.get_children())
        detail.delete(*detail.get_children())
        self.history_rows = {}
        self._history_group_details = {}

        rows = self.db.list_publication_history(limit=5000)
        grouped: dict[int, list[dict[str, object]]] = defaultdict(list)
        for row in rows:
            group_id = int(row.get("group_id") or 0)
            targets = row.get("targets") if isinstance(row.get("targets"), list) else []
            for target in targets:
                if not isinstance(target, dict):
                    continue
                target_id = int(target.get("id") or 0)
                if group_id <= 0 or target_id <= 0:
                    continue
                pseudo = dict(row)
                pseudo["targets"] = [target]
                pseudo["destination"] = str(target.get("platform") or "")
                self.history_rows[target_id] = pseudo
                grouped[group_id].append(pseudo)

        for group_id, items in grouped.items():
            self._history_group_details[group_id] = items
            title = str(items[0].get("display_title") or items[0].get("headline") or "Матеріал без редакційного заголовка")
            terminal_values: list[str] = []
            sent = 0
            failed = 0
            for item in items:
                target = (item.get("targets") or [{}])[0]  # type: ignore[index]
                if not isinstance(target, dict):
                    continue
                terminal_values.append(str(target.get("updated_at") or item.get("published_at") or item.get("scheduled_at") or ""))
                if target.get("status") == "sent":
                    sent += 1
                elif target.get("status") == "failed":
                    failed += 1
            total = sent + failed
            result = f"{sent}/{total} опубліковано" if total else "—"
            if failed:
                result += f" · {failed} помилка" + ("и" if failed != 1 else "")
            overview.insert("", "end", iid=f"group:{group_id}", values=(title, _display_period(terminal_values), result))

        attempts = len(self.history_rows)
        self.history_summary_var.set(f"Матеріалів за 7 діб: {len(grouped)} · публікацій / спроб: {attempts}")
        children = overview.get_children()
        wanted = f"group:{selected_group}" if selected_group and overview.exists(f"group:{selected_group}") else (children[0] if children else "")
        if wanted:
            overview.selection_set(wanted)
            overview.focus(wanted)
            overview.see(wanted)
        self._populate_history_details()

    def _history_overview_selected(self, _event: object | None = None) -> None:
        self._populate_history_details()

    def _populate_history_details(self) -> None:
        overview = getattr(self, "history_overview_tree", None)
        detail = getattr(self, "history_detail_tree", None)
        if overview is None or detail is None:
            return
        detail.delete(*detail.get_children())
        group_id = self._selected_overview_group(overview)
        if group_id is None:
            self.show_history_details()
            return
        labels = self._destination_labels()
        for item in self._history_group_details.get(group_id, []):
            target = (item.get("targets") or [{}])[0]  # type: ignore[index]
            if not isinstance(target, dict):
                continue
            target_id = int(target.get("id") or 0)
            platform = str(target.get("platform") or "")
            label = labels.get(platform, platform)
            profile, network = self._split_destination(label, platform)
            progress = target.get("progress") if isinstance(target.get("progress"), dict) else {}
            metrics = progress.get("metrics") if isinstance(progress.get("metrics"), dict) else {}
            terminal_raw = str(target.get("updated_at") or item.get("published_at") or item.get("scheduled_at") or "")
            terminal, _ = legacy_ui._format_kyiv_schedule(terminal_raw)
            status = "Опубліковано" if target.get("status") == "sent" else "Завершено з помилкою"
            error = " ".join(str(target.get("last_error") or "").split())
            if len(error) > 280:
                error = error[:279] + "…"
            detail.insert(
                "",
                "end",
                iid=str(target_id),
                values=(
                    profile,
                    network,
                    terminal,
                    status,
                    int(metrics.get("views") or 0) if metrics else "—",
                    int(metrics.get("likes") or metrics.get("reactions") or 0) if metrics else "—",
                    int(metrics.get("shares") or metrics.get("reposts") or metrics.get("quotes") or 0) if metrics else "—",
                    int(metrics.get("comments") or metrics.get("replies") or 0) if metrics else "—",
                    error or "—",
                ),
            )
        children = detail.get_children()
        if children:
            detail.selection_set(children[0])
            detail.focus(children[0])
        self.show_history_details()

    @staticmethod
    def _split_destination(label: str, key: str) -> tuple[str, str]:
        logical = _logical_platform(key)
        network = _PLATFORM_NAMES.get(logical, logical or "—")
        suffix = f" ({network})"
        profile = str(label or key)
        if profile.endswith(suffix):
            profile = profile[: -len(suffix)]
        return profile, network

    def close(self) -> None:
        if self._last_targets_save_after_id is not None:
            try:
                self.root.after_cancel(self._last_targets_save_after_id)
            except tk.TclError:
                pass
            self._last_targets_save_after_id = None
            self._persist_live_target_selection()
        super().close()
