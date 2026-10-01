from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from content_agent.i18n import original_text
from content_agent.paths import data_dir
from content_agent.scheduling import KYIV, parse_iso
from content_agent.ui.main_window import GROUP_FILTERS


@dataclass(frozen=True, slots=True)
class InboxFilterState:
    source_id: int | None = None
    topic_id: int | None = None
    search: str = ""


class InboxTabController:
    """Operator-facing Inbox controller: filters, stable sorting and compact rendering."""

    DEFAULT_WIDTHS = {
        "title": 760,
        "topic": 180,
        "sources": 80,
        "published": 78,
    }
    DISPLAY_COLUMNS = ("title", "topic", "sources", "published")

    def __init__(self, host, filter_bar) -> None:
        self.host = host
        self.db = host.db
        self.tree = host.groups_tree
        self.filter_bar = filter_bar
        self._source_label_to_id: dict[str, int] = {}
        self._topic_label_to_id: dict[str, int] = {}
        state_dir = data_dir() / "v2"
        self._column_path = state_dir / "inbox_columns.json"
        self._sort_path = state_dir / "inbox_sort.json"
        self._sort_column = "published"
        self._sort_descending = True
        self._load_sort_state()
        self._configure_columns()
        self.refresh_choices()
        self._load_widths()
        self.tree.bind("<ButtonRelease-1>", self._save_widths, add="+")

    def _configure_columns(self) -> None:
        columns = [str(value) for value in self.tree.cget("columns")]
        if "topic" not in columns:
            columns.append("topic")
        self.tree.configure(columns=tuple(columns))
        headings = {
            "title": "Подія",
            "topic": "Тема",
            "sources": "Джерел",
            "published": "Час",
        }
        for name, label in headings.items():
            if name not in columns:
                continue
            self.tree.heading(name, text=label, command=lambda column=name: self._change_sort(column))
            anchor = "center" if name in {"sources", "published"} else "w"
            self.tree.column(name, width=self.DEFAULT_WIDTHS[name], minwidth=55, anchor=anchor)
        self.tree.configure(displaycolumns=tuple(name for name in self.DISPLAY_COLUMNS if name in columns))

    def _load_sort_state(self) -> None:
        try:
            raw = json.loads(self._sort_path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(raw, dict):
            return
        column = str(raw.get("column") or "")
        if column in self.DISPLAY_COLUMNS:
            self._sort_column = column
            self._sort_descending = bool(raw.get("descending", False))

    def _save_sort_state(self) -> None:
        try:
            self._sort_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"column": self._sort_column, "descending": self._sort_descending}
            tmp = self._sort_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            tmp.replace(self._sort_path)
        except Exception:
            return

    def _sort_key(self, iid: str, column: str):
        value = str(self.tree.set(iid, column) or "")
        if column == "sources":
            try:
                return int(value)
            except (TypeError, ValueError):
                return -1
        if column == "published":
            try:
                hours, minutes = value.split(":", 1)
                return int(hours) * 60 + int(minutes)
            except Exception:
                return -1
        return value.casefold()

    def _apply_sort(self) -> None:
        children = list(self.tree.get_children())
        if not children:
            return
        column = self._sort_column if self._sort_column in self.DISPLAY_COLUMNS else "published"
        children.sort(key=lambda iid: self._sort_key(iid, column), reverse=self._sort_descending)
        for index, iid in enumerate(children):
            self.tree.move(iid, "", index)

    def _change_sort(self, column: str) -> None:
        if column not in self.DISPLAY_COLUMNS:
            return
        if self._sort_column == column:
            self._sort_descending = not self._sort_descending
        else:
            self._sort_column = column
            self._sort_descending = column in {"sources", "published"}
        self._save_sort_state()
        self._apply_sort()

    def _load_widths(self) -> None:
        try:
            raw = json.loads(self._column_path.read_text(encoding="utf-8"))
        except Exception:
            raw = {}
        if not isinstance(raw, dict):
            return
        for name in self.DISPLAY_COLUMNS:
            if name not in raw:
                continue
            try:
                self.tree.column(name, width=max(55, min(1200, int(raw[name]))))
            except Exception:
                continue

    def _save_widths(self, _event=None) -> None:
        try:
            self._column_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {name: int(self.tree.column(name, "width")) for name in self.DISPLAY_COLUMNS}
            tmp = self._column_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            tmp.replace(self._column_path)
        except Exception:
            return

    def refresh_choices(self) -> None:
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
        self._source_label_to_id = source_map
        self._topic_label_to_id = topic_map
        self.host._inbox_source_label_to_id = dict(source_map)
        self.host._inbox_topic_label_to_id = dict(topic_map)
        self.filter_bar.set_choices(
            sources=(self.host.ALL_SOURCES_LABEL, *source_labels),
            topics=(self.host.ALL_TOPICS_LABEL, *topic_labels),
        )
        if self.host.inbox_source_filter_var.get() not in {self.host.ALL_SOURCES_LABEL, *source_labels}:
            self.host.inbox_source_filter_var.set(self.host.ALL_SOURCES_LABEL)
        if self.host.inbox_topic_filter_var.get() not in {self.host.ALL_TOPICS_LABEL, *topic_labels}:
            self.host.inbox_topic_filter_var.set(self.host.ALL_TOPICS_LABEL)

    def state(self) -> InboxFilterState:
        return InboxFilterState(
            source_id=self._source_label_to_id.get(str(self.host.inbox_source_filter_var.get() or "")),
            topic_id=self._topic_label_to_id.get(str(self.host.inbox_topic_filter_var.get() or "")),
            search=" ".join(str(self.host.inbox_search_var.get() or "").split()).strip(),
        )

    @staticmethod
    def _format_time(value: str | None) -> str:
        parsed = parse_iso(str(value or ""))
        if parsed is None:
            return "—"
        return parsed.astimezone(KYIV).strftime("%H:%M")

    @staticmethod
    def _compact_names(values: object) -> str:
        names = [str(value).strip() for value in (values or []) if str(value).strip()]
        if not names:
            return "—"
        if len(names) <= 2:
            return " / ".join(names)
        return " / ".join(names[:2]) + f" +{len(names) - 2}"

    def refresh(self) -> None:
        selected_before = tuple(self.tree.selection())
        focus_before = self.tree.focus()
        old_children = list(self.tree.get_children())
        yview_before = self.tree.yview()
        top_index = 0
        if old_children and yview_before:
            top_index = min(len(old_children) - 1, max(0, int(round(float(yview_before[0]) * len(old_children)))))
        # Keep several concrete rows from the current viewport. After delete/merge the
        # first row may disappear, so the next surviving neighbor becomes the anchor.
        viewport_anchors = old_children[top_index:top_index + 32]

        current = self.state()
        selected_filter = original_text(self.host.group_filter.get())
        status = GROUP_FILTERS.get(selected_filter)
        try:
            groups = self.db.list_inbox_groups(
                status=status,
                source_id=current.source_id,
                topic_id=current.topic_id,
                search=current.search,
                limit=None,
            )
            metadata = self.db.group_manual_topics([group.id for group in groups]) if groups else {}
        except Exception as exc:
            self.host.set_status(f"Вхідні: помилка фільтрації · {exc}")
            return

        self.tree.delete(*self.tree.get_children())
        columns = tuple(str(value) for value in self.tree.cget("columns"))
        decisions: dict[int, object] = {}
        for group in groups:
            info = metadata.get(
                int(group.id),
                {"source_names": [], "topic_names": [], "source_ids": [], "topic_ids": []},
            )
            topic_label = self._compact_names(info.get("topic_names", []))
            values = {
                "title": group.canonical_title,
                "topic": topic_label,
                "sources": group.source_count,
                "published": self._format_time(group.last_published_at),
            }
            self.tree.insert(
                "",
                "end",
                iid=str(group.id),
                values=tuple(values.get(name, "") for name in columns),
                tags=("approved",) if group.status == "approved" else (),
            )
            decisions[int(group.id)] = type("TopicDecision", (), {"topic": topic_label})()
        self.host._topic_decisions = decisions

        # RC57: refresh must never silently revert the operator's chosen order to
        # database recency. Apply the persisted/current Treeview sort first.
        self._apply_sort()

        existing = [iid for iid in selected_before if self.tree.exists(iid)]
        if existing:
            self.tree.selection_set(existing)
        if focus_before and self.tree.exists(focus_before):
            self.tree.focus(focus_before)

        new_children = list(self.tree.get_children())
        anchor = next((iid for iid in viewport_anchors if self.tree.exists(iid)), None)
        if anchor and new_children:
            try:
                self.tree.yview_moveto(new_children.index(anchor) / max(1, len(new_children)))
            except Exception:
                pass
        elif yview_before:
            try:
                self.tree.yview_moveto(float(yview_before[0]))
            except Exception:
                pass

        count = len(groups)
        if count:
            self.host.set_status(f"Вхідні: показано всі {count} блоків за поточними фільтрами.")
        else:
            self.host.set_status("Вхідні: за поточними фільтрами нічого не знайдено.")

    def reset(self) -> None:
        self.host.inbox_source_filter_var.set(self.host.ALL_SOURCES_LABEL)
        self.host.inbox_topic_filter_var.set(self.host.ALL_TOPICS_LABEL)
        self.host.inbox_search_var.set("")
        self.refresh()

    def focus_primary(self) -> None:
        self.filter_bar.focus_search()

    def escape(self) -> str | None:
        if str(self.host.inbox_search_var.get() or ""):
            self.host.inbox_search_var.set("")
            self.refresh()
            return "break"
        try:
            self.tree.focus_set()
        except Exception:
            return None
        return "break"


__all__ = ["InboxFilterState", "InboxTabController"]
