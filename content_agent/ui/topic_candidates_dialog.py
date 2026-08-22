from __future__ import annotations

import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Callable, Mapping, Sequence

from ..i18n import normalize_language, tr


class TopicCandidatesDialog(tk.Toplevel):
    """Modal list that contains only candidates for one manual merge decision."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        anchor_id: int,
        anchor_title: str,
        candidates: Sequence[Mapping[str, object]],
        language: str,
        on_merge: Callable[[list[int], list[int]], None],
    ) -> None:
        super().__init__(parent)
        self.language = normalize_language(language)
        self.anchor_id = int(anchor_id)
        self.candidates = {int(row["group_id"]): dict(row) for row in candidates}
        self.on_merge = on_merge
        self.selected_ids: set[int] = set(self.candidates)

        self.title(tr("Кандидати на об’єднання", self.language))
        self.geometry("1180x720")
        self.minsize(820, 520)
        self.transient(parent.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        header = ttk.Frame(self, padding=(12, 10, 12, 6))
        header.pack(fill="x")
        ttk.Label(
            header,
            text=f"#{self.anchor_id} · {anchor_title}",
            font="TkHeadingFont",
            wraplength=1100,
        ).pack(anchor="w")
        self.summary_var = tk.StringVar()
        ttk.Label(header, textvariable=self.summary_var, foreground="#555").pack(anchor="w", pady=(4, 0))

        body = ttk.PanedWindow(self, orient="vertical")
        body.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        list_frame = ttk.Frame(body)
        preview_frame = ttk.LabelFrame(body, text=tr("Попередній перегляд", self.language), padding=7)
        body.add(list_frame, weight=3)
        body.add(preview_frame, weight=2)

        columns = ("selected", "score", "title", "sources", "published", "reason")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", selectmode="browse")
        headings = {
            "selected": tr("Вибір", self.language),
            "score": tr("Схожість", self.language),
            "title": tr("Подія", self.language),
            "sources": tr("Джерел", self.language),
            "published": tr("Остання згадка", self.language),
            "reason": tr("Причина", self.language),
        }
        widths = {"selected": 70, "score": 90, "title": 500, "sources": 75, "published": 165, "reason": 310}
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], anchor="w", stretch=column in {"title", "reason"})
        self.tree.tag_configure("strong", background="#e3f3e3")
        self.tree.tag_configure("possible", background="#fff5d6")
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<Button-1>", self._toggle_from_click, add="+")
        self.tree.bind("<space>", self._toggle_focused)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._show_preview())
        self.tree.bind("<Double-1>", lambda _event: self.open_selected())

        for group_id, row in self.candidates.items():
            score = int(row.get("score") or 0)
            self.tree.insert(
                "",
                "end",
                iid=str(group_id),
                values=(
                    "☑",
                    f"{score}%",
                    str(row.get("title") or ""),
                    int(row.get("source_count") or 0),
                    str(row.get("published_at") or "—"),
                    str(row.get("reason") or ""),
                ),
                tags=(("strong",) if score >= 75 else ("possible",)),
            )

        self.preview = ScrolledText(preview_frame, wrap="word", height=10)
        self.preview.pack(fill="both", expand=True)
        self.preview.configure(state="disabled")

        actions = ttk.Frame(self, padding=(12, 0, 12, 12))
        actions.pack(fill="x")
        ttk.Button(actions, text=tr("Вибрати всі", self.language), command=self.select_all).pack(side="left")
        ttk.Button(actions, text=tr("Зняти вибір", self.language), command=self.clear_selection).pack(side="left", padx=6)
        ttk.Button(actions, text=tr("Відкрити матеріал", self.language), command=self.open_selected).pack(side="left")
        ttk.Button(actions, text=tr("Скасувати", self.language), command=self.destroy).pack(side="right")
        self.merge_button = ttk.Button(
            actions,
            text=tr("Об’єднати вибрані", self.language),
            command=self.merge,
            style="Accent.TButton",
        )
        self.merge_button.pack(side="right", padx=(0, 8))

        self._update_summary()
        first = self.tree.get_children()
        if first:
            self.tree.selection_set(first[0])
            self.tree.focus(first[0])
            self._show_preview()
        self.grab_set()
        self.focus_set()

    def _set_checked(self, group_id: int, checked: bool) -> None:
        if checked:
            self.selected_ids.add(group_id)
        else:
            self.selected_ids.discard(group_id)
        values = list(self.tree.item(str(group_id), "values"))
        if values:
            values[0] = "☑" if checked else "☐"
            self.tree.item(str(group_id), values=values)
        self._update_summary()

    def _toggle_from_click(self, event: tk.Event) -> None:
        iid = self.tree.identify_row(int(event.y))
        column = self.tree.identify_column(int(event.x))
        if iid and column == "#1":
            group_id = int(iid)
            self._set_checked(group_id, group_id not in self.selected_ids)

    def _toggle_focused(self, _event: object | None = None) -> str:
        iid = self.tree.focus()
        if iid:
            group_id = int(iid)
            self._set_checked(group_id, group_id not in self.selected_ids)
        return "break"

    def _update_summary(self) -> None:
        total = len(self.candidates)
        selected = len(self.selected_ids)
        if self.language == "en":
            self.summary_var.set(f"Candidates: {total} · selected for merging: {selected}")
        else:
            self.summary_var.set(f"Кандидатів: {total} · вибрано для об’єднання: {selected}")
        self.merge_button.configure(state="normal" if selected else "disabled")

    def _show_preview(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        row = self.candidates.get(int(selection[0]))
        if row is None:
            return
        text = (
            f"{row.get('title', '')}\n\n"
            f"{row.get('text', '')}\n\n"
            f"URL: {row.get('url', '')}"
        ).strip()
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", text)
        self.preview.configure(state="disabled")

    def select_all(self) -> None:
        for group_id in self.candidates:
            self._set_checked(group_id, True)

    def clear_selection(self) -> None:
        for group_id in tuple(self.candidates):
            self._set_checked(group_id, False)

    def open_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        row = self.candidates.get(int(selection[0]))
        url = str(row.get("url") or "") if row else ""
        if url:
            webbrowser.open(url, new=2)
            return
        messagebox.showinfo(
            tr("Відкрити матеріал", self.language),
            tr("Для цього матеріалу немає доступного URL.", self.language),
            parent=self,
        )

    def merge(self) -> None:
        selected = sorted(self.selected_ids)
        if not selected:
            return
        all_candidates = sorted(self.candidates)
        self.grab_release()
        self.destroy()
        self.on_merge(selected, all_candidates)
