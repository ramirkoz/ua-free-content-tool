from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
import tkinter as tk
from tkinter import simpledialog, ttk

from ...source_management_v1_4_rc9 import SOURCE_KIND_CHOICES, detect_source_kind, resolve_source_kind
from .window import MainWindow as BaseMainWindow


UNASSIGNED_TOPIC = "— не задано —"
ALL_SOURCES = "Усі джерела"
ALL_TOPICS = "Усі теми"


@dataclass(slots=True)
class _ManualTopicDecision:
    topic: str


class _ManualSourceTopicStore:
    """Compatibility adapter that retires automatic topic classification in V2.

    RC4 still calls a topic store while refreshing its inherited Inbox. Returning a
    neutral placeholder here prevents the old classifier from making decisions. The
    RC43 window then paints the authoritative topic directly from source metadata.
    """

    def resolve(self, _group_id: int, _context: object):
        return _ManualTopicDecision(UNASSIGNED_TOPIC), False

    def save(self) -> None:
        return None

    def set_manual(self, _group_id: int, _topic: str) -> None:
        return None

    def clear_manual(self, _group_id: int) -> None:
        return None


class TopicManagerDialog(tk.Toplevel):
    def __init__(self, owner: "MainWindow") -> None:
        super().__init__(owner.root)
        self.owner = owner
        self.title("Теми джерел")
        self.geometry("560x460")
        self.minsize(460, 360)
        self.transient(owner.root)

        frame = ttk.Frame(self, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame,
            text=(
                "Це ручний список тем. Тема закріплюється за джерелом і не визначається автоматично "
                "за текстом окремої новини."
            ),
            wraplength=520,
            foreground="#555",
        ).pack(fill="x", pady=(0, 8))

        self.tree = ttk.Treeview(frame, columns=("id", "name"), show="headings", selectmode="browse")
        self.tree.heading("id", text="ID")
        self.tree.heading("name", text="Тема")
        self.tree.column("id", width=70, stretch=False, anchor="center")
        self.tree.column("name", width=390, stretch=True, anchor="w")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda _event: self.rename_topic())
        self.tree.bind("<Delete>", lambda _event: self.delete_topic())

        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(10, 0))
        ttk.Button(actions, text="Додати", command=self.add_topic).pack(side="left")
        ttk.Button(actions, text="Перейменувати", command=self.rename_topic).pack(side="left", padx=6)
        ttk.Button(actions, text="Видалити", command=self.delete_topic).pack(side="left")
        ttk.Button(actions, text="Закрити", command=self.destroy).pack(side="right")

        self.refresh()
        self.grab_set()
        self.focus_set()

    def _selected_id(self) -> int | None:
        selection = self.tree.selection()
        if not selection:
            return None
        try:
            return int(selection[0])
        except (TypeError, ValueError):
            return None

    def refresh(self) -> None:
        selected = self._selected_id()
        self.tree.delete(*self.tree.get_children(""))
        for row in self.owner.db.list_manual_topics():
            topic_id = int(row["id"])
            self.tree.insert("", "end", iid=str(topic_id), values=(topic_id, str(row["name"])))
        if selected is not None and self.tree.exists(str(selected)):
            self.tree.selection_set(str(selected))
            self.tree.focus(str(selected))

    def add_topic(self) -> None:
        value = simpledialog.askstring("Нова тема", "Назва теми:", parent=self)
        if value is None:
            return
        try:
            topic_id = self.owner.db.create_manual_topic(value)
        except Exception as exc:
            self.owner.msg.showerror("Теми", str(exc), parent=self)
            return
        self.refresh()
        if self.tree.exists(str(topic_id)):
            self.tree.selection_set(str(topic_id))
            self.tree.focus(str(topic_id))
            self.tree.see(str(topic_id))
        self.owner._manual_topics_changed()

    def rename_topic(self) -> None:
        topic_id = self._selected_id()
        if topic_id is None:
            return
        current = str(self.tree.set(str(topic_id), "name") or "")
        value = simpledialog.askstring("Перейменувати тему", "Нова назва:", initialvalue=current, parent=self)
        if value is None:
            return
        try:
            self.owner.db.rename_manual_topic(topic_id, value)
        except Exception as exc:
            self.owner.msg.showerror("Теми", str(exc), parent=self)
            return
        self.refresh()
        self.owner._manual_topics_changed()

    def delete_topic(self) -> None:
        topic_id = self._selected_id()
        if topic_id is None:
            return
        name = str(self.tree.set(str(topic_id), "name") or "")
        try:
            source_rows = [row for row in self.owner.db.source_topic_rows() if int(row.get("topic_id") or 0) == topic_id]
        except Exception:
            source_rows = []
        detail = ""
        if source_rows:
            detail = f"\n\nПісля видалення тема буде знята з джерел: {len(source_rows)}."
        if not self.owner.msg.askyesno(
            "Видалити тему",
            f"Видалити тему «{name}»?{detail}",
            parent=self,
        ):
            return
        try:
            self.owner.db.delete_manual_topic(topic_id)
        except Exception as exc:
            self.owner.msg.showerror("Теми", str(exc), parent=self)
            return
        self.refresh()
        self.owner._manual_topics_changed()


class MainWindow(BaseMainWindow):
    """RC43 V2 UI: operator-owned topics fixed at source level."""

    def __init__(self, root, database, config) -> None:
        self._manual_topic_store = _ManualSourceTopicStore()
        self._source_topic_label_to_id: dict[str, int] = {}
        self._inbox_source_label_to_id: dict[str, int] = {}
        self._inbox_topic_label_to_id: dict[str, int] = {}
        super().__init__(root, database, config)
        self._install_manual_topic_inbox_filters()
        self._refresh_topic_choices()
        self.refresh_sources()
        self.refresh_groups()

    # ------------------------------------------------------------------
    # Source management: topic belongs to source, not to an AI classifier.
    # ------------------------------------------------------------------
    def _build_sources_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Джерела")
        self.sources_tab = tab

        form = ttk.Frame(tab)
        form.pack(fill="x")
        self.source_kind = tk.StringVar(value="auto")
        self.source_name = tk.StringVar()
        self.source_url = tk.StringVar()
        self.source_topic = tk.StringVar(value=UNASSIGNED_TOPIC)

        ttk.Label(form, text="Тип").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            form, textvariable=self.source_kind, values=SOURCE_KIND_CHOICES,
            state="readonly", width=12,
        ).grid(row=1, column=0, padx=(0, 8), sticky="ew")
        ttk.Label(form, text="Назва").grid(row=0, column=1, sticky="w")
        ttk.Entry(form, textvariable=self.source_name, width=26).grid(row=1, column=1, padx=(0, 8), sticky="ew")
        ttk.Label(form, text="URL або @telegram_channel").grid(row=0, column=2, sticky="w")
        ttk.Entry(form, textvariable=self.source_url).grid(row=1, column=2, padx=(0, 8), sticky="ew")
        ttk.Label(form, text="Тема").grid(row=0, column=3, sticky="w")
        self.source_topic_box = ttk.Combobox(
            form, textvariable=self.source_topic, values=(UNASSIGNED_TOPIC,),
            state="readonly", width=24,
        )
        self.source_topic_box.grid(row=1, column=3, padx=(0, 8), sticky="ew")
        ttk.Button(form, text="Додати", command=self.add_source).grid(row=1, column=4, padx=4)
        form.columnconfigure(2, weight=1)

        buttons = ttk.Frame(tab)
        buttons.pack(fill="x", pady=(10, 4))
        ttk.Button(buttons, text="Оновити список", command=self.refresh_sources).pack(side="left")
        ttk.Button(buttons, text="Редагувати", command=self.edit_source).pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="Видалити", command=self.delete_source).pack(side="left", padx=6)
        ttk.Button(buttons, text="Теми…", command=self.manage_topics).pack(side="left", padx=(10, 0))
        self.auto_collect_status_var = tk.StringVar(value="Автоматичне оновлення: після запуску і кожні 5 хвилин")
        ttk.Label(buttons, textvariable=self.auto_collect_status_var, foreground="#555").pack(side="right")

        ttk.Label(
            tab,
            text=(
                "Тема задається вручну для джерела. Усі новини цього джерела використовують тільки цю тему; "
                "автоматична класифікація теми не застосовується. Подвійний клік — редагування."
            ),
            foreground="#555",
            wraplength=1350,
        ).pack(fill="x", pady=(0, 5))

        columns = ("id", "kind", "name", "topic", "url", "checked")
        self.sources_tree = ttk.Treeview(tab, columns=columns, show="headings", selectmode="extended")
        widths = {"id": 60, "kind": 90, "name": 220, "topic": 190, "url": 520, "checked": 170}
        labels = {
            "id": "ID", "kind": "Тип", "name": "Назва", "topic": "Тема",
            "url": "Адреса", "checked": "Остання перевірка",
        }
        for column in columns:
            self.sources_tree.heading(column, text=labels[column])
            self.sources_tree.column(column, width=widths[column], anchor="w", stretch=column == "url")
        self.sources_tree.pack(fill="both", expand=True)
        self.sources_tree.bind("<Double-1>", self._edit_source_from_event)
        self.sources_tree.bind("<Delete>", self._delete_sources_from_event)
        self.sources_tree.bind("<Control-a>", self._select_all_sources)
        self.sources_tree.bind("<Control-A>", self._select_all_sources)

    def _refresh_topic_choices(self) -> None:
        rows = self.db.list_manual_topics()
        labels = [str(row["name"]) for row in rows]
        self._source_topic_label_to_id = {str(row["name"]): int(row["id"]) for row in rows}
        if hasattr(self, "source_topic_box"):
            self.source_topic_box.configure(values=(UNASSIGNED_TOPIC, *labels))
            current = str(self.source_topic.get() or UNASSIGNED_TOPIC)
            if current not in {UNASSIGNED_TOPIC, *labels}:
                self.source_topic.set(UNASSIGNED_TOPIC)
        self._refresh_inbox_filter_choices()

    def _selected_topic_id(self, label: str) -> int | None:
        return self._source_topic_label_to_id.get(str(label or ""))

    def manage_topics(self) -> None:
        TopicManagerDialog(self)

    def _manual_topics_changed(self) -> None:
        self._refresh_topic_choices()
        self.refresh_sources()
        self.refresh_groups()

    def add_source(self) -> None:
        name = self.source_name.get().strip()
        url = self.source_url.get().strip()
        topic_id = self._selected_topic_id(self.source_topic.get())
        if not name or not url:
            self.msg.showwarning("Джерело", "Вкажіть назву та адресу.", parent=self.root)
            return
        if topic_id is None:
            self.msg.showwarning(
                "Джерело",
                "Оберіть тему. Якщо потрібної теми немає, спочатку додайте її кнопкою «Теми…».",
                parent=self.root,
            )
            return
        requested = self.source_kind.get().strip().casefold() or "auto"
        kind = resolve_source_kind(url, requested)
        try:
            source_id = int(self.db.add_source(kind, name, url))
            self.db.set_source_topic(source_id, topic_id)
        except Exception as exc:
            self._show_error(exc)
            return
        self.source_kind.set("auto")
        self.source_name.set("")
        self.source_url.set("")
        self.source_topic.set(UNASSIGNED_TOPIC)
        self.refresh_sources()
        self.refresh_groups()
        self.set_status(f"Джерело додано. Тип: {kind}; тема зафіксована.")

    def refresh_sources(self) -> None:
        tree = getattr(self, "sources_tree", None)
        if tree is None:
            return
        selected = tuple(tree.selection())
        tree.delete(*tree.get_children())
        for row in self.db.source_topic_rows():
            source_id = int(row["id"])
            tree.insert(
                "", "end", iid=str(source_id),
                values=(
                    source_id,
                    str(row["kind"]),
                    str(row["name"]),
                    str(row["topic_name"] or UNASSIGNED_TOPIC),
                    str(row["url"]),
                    str(row["last_checked_at"] or "—"),
                ),
            )
        restored = [iid for iid in selected if tree.exists(iid)]
        if restored:
            tree.selection_set(restored)
        self._refresh_inbox_filter_choices()

    def edit_source(self) -> None:
        ids = self._selected_source_ids()
        if not ids:
            self.msg.showinfo("Джерело", "Оберіть джерело для редагування.", parent=self.root)
            return
        if len(ids) != 1:
            self.msg.showinfo("Джерело", "Для редагування оберіть один рядок.", parent=self.root)
            return
        source_id = int(ids[0])
        row = next((item for item in self.db.source_topic_rows() if int(item["id"]) == source_id), None)
        if row is None:
            self.refresh_sources()
            return

        dialog = tk.Toplevel(self.root)
        dialog.title(f"Редагування джерела #{source_id}")
        dialog.transient(self.root)
        dialog.resizable(True, False)
        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        kind_var = tk.StringVar(value=str(row["kind"] or "url"))
        name_var = tk.StringVar(value=str(row["name"] or ""))
        url_var = tk.StringVar(value=str(row["url"] or ""))
        topic_var = tk.StringVar(value=str(row["topic_name"] or UNASSIGNED_TOPIC))
        detected_var = tk.StringVar(value=f"Автовизначення типу джерела: {detect_source_kind(url_var.get())}")

        ttk.Label(frame, text="Тип").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=3)
        ttk.Combobox(frame, textvariable=kind_var, values=SOURCE_KIND_CHOICES, state="readonly", width=18).grid(
            row=0, column=1, sticky="w", pady=3
        )
        ttk.Label(frame, text="Назва").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=3)
        ttk.Entry(frame, textvariable=name_var, width=60).grid(row=1, column=1, sticky="ew", pady=3)
        ttk.Label(frame, text="Адреса").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=3)
        url_entry = ttk.Entry(frame, textvariable=url_var, width=76)
        url_entry.grid(row=2, column=1, sticky="ew", pady=3)
        ttk.Label(frame, text="Тема").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=3)
        ttk.Combobox(
            frame,
            textvariable=topic_var,
            values=(UNASSIGNED_TOPIC, *self._source_topic_label_to_id.keys()),
            state="readonly",
            width=30,
        ).grid(row=3, column=1, sticky="w", pady=3)
        ttk.Label(frame, textvariable=detected_var, foreground="#555").grid(
            row=4, column=1, sticky="w", pady=(0, 6)
        )
        url_var.trace_add(
            "write",
            lambda *_args: detected_var.set(f"Автовизначення типу джерела: {detect_source_kind(url_var.get())}"),
        )

        actions = ttk.Frame(frame)
        actions.grid(row=5, column=0, columnspan=2, sticky="e", pady=(7, 0))

        def save() -> None:
            name = name_var.get().strip()
            url = url_var.get().strip()
            topic_id = self._selected_topic_id(topic_var.get())
            if not name or not url:
                self.msg.showwarning("Джерело", "Вкажіть назву та адресу.", parent=dialog)
                return
            if topic_id is None:
                self.msg.showwarning("Джерело", "Оберіть тему для цього джерела.", parent=dialog)
                return
            kind = resolve_source_kind(url, kind_var.get())
            try:
                self.db.update_source(source_id, kind=kind, name=name, url=url)
                self.db.set_source_topic(source_id, topic_id)
            except Exception as exc:
                self.msg.showerror("UA FREE Content Tool", str(exc), parent=dialog)
                return
            dialog.destroy()
            self.refresh_sources()
            self.refresh_groups()
            self.set_status(f"Джерело #{source_id} оновлено. Тема зафіксована: {topic_var.get()}.")

        ttk.Button(actions, text="Скасувати", command=dialog.destroy).pack(side="right")
        ttk.Button(actions, text="Зберегти", command=save).pack(side="right", padx=(0, 6))
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.bind("<Control-s>", lambda _event: save())
        dialog.bind("<Control-S>", lambda _event: save())
        dialog.grab_set()
        url_entry.focus_set()

    # ------------------------------------------------------------------
    # Inbox: source/topic filters and source-owned topic labels.
    # ------------------------------------------------------------------
    def _install_manual_topic_inbox_filters(self) -> None:
        bar = getattr(self, "_rc14_inbox_tools_frame", None)
        if bar is None or hasattr(self, "inbox_source_filter_box"):
            return
        self.inbox_source_filter_var = tk.StringVar(value=ALL_SOURCES)
        self.inbox_topic_filter_var = tk.StringVar(value=ALL_TOPICS)

        ttk.Label(bar, text="Джерело:").pack(side="left", padx=(12, 4))
        self.inbox_source_filter_box = ttk.Combobox(
            bar, textvariable=self.inbox_source_filter_var, state="readonly", width=24,
        )
        self.inbox_source_filter_box.pack(side="left", padx=(0, 6))
        self.inbox_source_filter_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh_groups())

        ttk.Label(bar, text="Тема:").pack(side="left", padx=(4, 4))
        self.inbox_topic_filter_box = ttk.Combobox(
            bar, textvariable=self.inbox_topic_filter_var, state="readonly", width=20,
        )
        self.inbox_topic_filter_box.pack(side="left", padx=(0, 6))
        self.inbox_topic_filter_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh_groups())
        ttk.Button(bar, text="Скинути фільтри", command=self.reset_manual_topic_filters).pack(side="left", padx=(0, 6))
        self._refresh_inbox_filter_choices()

    def _refresh_inbox_filter_choices(self) -> None:
        if not hasattr(self, "inbox_source_filter_box"):
            return
        source_rows = self.db.source_topic_rows()
        source_labels: list[str] = []
        source_map: dict[str, int] = {}
        for row in source_rows:
            label = f"{str(row['name'])} [#{int(row['id'])}]"
            source_labels.append(label)
            source_map[label] = int(row["id"])
        topic_rows = self.db.list_manual_topics()
        topic_labels = [str(row["name"]) for row in topic_rows]
        topic_map = {str(row["name"]): int(row["id"]) for row in topic_rows}
        self._inbox_source_label_to_id = source_map
        self._inbox_topic_label_to_id = topic_map
        self.inbox_source_filter_box.configure(values=(ALL_SOURCES, *source_labels))
        self.inbox_topic_filter_box.configure(values=(ALL_TOPICS, *topic_labels))
        if self.inbox_source_filter_var.get() not in {ALL_SOURCES, *source_labels}:
            self.inbox_source_filter_var.set(ALL_SOURCES)
        if self.inbox_topic_filter_var.get() not in {ALL_TOPICS, *topic_labels}:
            self.inbox_topic_filter_var.set(ALL_TOPICS)

    def reset_manual_topic_filters(self) -> None:
        if hasattr(self, "inbox_source_filter_var"):
            self.inbox_source_filter_var.set(ALL_SOURCES)
        if hasattr(self, "inbox_topic_filter_var"):
            self.inbox_topic_filter_var.set(ALL_TOPICS)
        self.refresh_groups()

    def _active_inbox_source_id(self) -> int | None:
        if not hasattr(self, "inbox_source_filter_var"):
            return None
        return self._inbox_source_label_to_id.get(str(self.inbox_source_filter_var.get() or ""))

    def _active_inbox_topic_id(self) -> int | None:
        if not hasattr(self, "inbox_topic_filter_var"):
            return None
        return self._inbox_topic_label_to_id.get(str(self.inbox_topic_filter_var.get() or ""))

    def refresh_groups(self) -> None:
        # Neutralize the historical per-group automatic classifier for the whole
        # inherited refresh chain. Manual source assignments become authoritative.
        self._topic_store = self._manual_topic_store
        super().refresh_groups()

        tree = getattr(self, "groups_tree", None)
        if tree is None:
            return
        group_ids: list[int] = []
        for iid in tree.get_children(""):
            try:
                group_ids.append(int(iid))
            except (TypeError, ValueError):
                continue
        if not group_ids:
            return
        topic_rows = self.db.group_manual_topics(group_ids)
        source_filter = self._active_inbox_source_id()
        topic_filter = self._active_inbox_topic_id()
        topic_column = "topic" in tuple(str(value) for value in tree.cget("columns"))
        decisions: dict[int, object] = {}

        for group_id in group_ids:
            info = topic_rows.get(
                group_id,
                {"source_ids": [], "source_names": [], "topic_ids": [], "topic_names": []},
            )
            source_ids = {int(value) for value in info.get("source_ids", [])}
            topic_ids = {int(value) for value in info.get("topic_ids", [])}
            topic_names = [str(value) for value in info.get("topic_names", []) if str(value).strip()]
            label = " / ".join(topic_names) if topic_names else UNASSIGNED_TOPIC
            iid = str(group_id)
            if topic_column and tree.exists(iid):
                tree.set(iid, "topic", label)
            decisions[group_id] = SimpleNamespace(topic=label)
            if source_filter is not None and source_filter not in source_ids:
                if tree.exists(iid):
                    tree.delete(iid)
                continue
            if topic_filter is not None and topic_filter not in topic_ids:
                if tree.exists(iid):
                    tree.delete(iid)

        self._topic_decisions = decisions

    def _rc4_topic_double_click(self, event: tk.Event) -> str | None:
        tree = getattr(self, "groups_tree", None)
        if tree is None:
            return None
        try:
            if tree.identify_region(event.x, event.y) != "cell":
                return None
            token = tree.identify_column(event.x)
            display = tuple(str(value) for value in tree.cget("displaycolumns"))
            if display == ("#all",):
                display = tuple(str(value) for value in tree.cget("columns"))
            index = int(str(token).lstrip("#")) - 1
            if index < 0 or index >= len(display) or display[index] != "topic":
                return None
        except (tk.TclError, TypeError, ValueError):
            return None
        self.msg.showinfo(
            "Тема матеріалу",
            "Тема більше не визначається для окремої новини автоматично. Вона закріплюється за джерелом у вкладці «Джерела».",
            parent=self.root,
        )
        try:
            self.notebook.select(self.sources_tab)
        except Exception:
            pass
        return "break"


__all__ = ["MainWindow", "TopicManagerDialog", "UNASSIGNED_TOPIC", "ALL_SOURCES", "ALL_TOPICS"]
