from __future__ import annotations

import tkinter as tk
import webbrowser
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from typing import Callable, Mapping, Sequence


class KeywordMergeDialog(tk.Toplevel):
    """Show only exact keyword matches and let the editor choose blocks to merge."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        query: str,
        candidates: Sequence[Mapping[str, object]],
        on_merge: Callable[[list[int]], None],
    ) -> None:
        super().__init__(parent)
        self.query = str(query or "").strip()
        self.candidates = {int(row["group_id"]): dict(row) for row in candidates}
        self.on_merge = on_merge
        self.selected_order: list[int] = []

        self.title("Пошук у Вхідних · кандидати на об’єднання")
        self.geometry("1220x760")
        self.minsize(860, 540)
        self.transient(parent.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        header = ttk.Frame(self, padding=(12, 10, 12, 6))
        header.pack(fill="x")
        ttk.Label(header, text=f"Ключові слова: {self.query}", font="TkHeadingFont").pack(anchor="w")
        self.summary_var = tk.StringVar()
        ttk.Label(header, textvariable=self.summary_var, foreground="#555").pack(anchor="w", pady=(4, 0))
        ttk.Label(
            header,
            text=(
                "Показані тільки блоки, де ВСІ введені слова знайдені в назві або тексті. "
                "★ позначає основний блок: його назва, медіа та налаштування залишаться після об’єднання."
            ),
            wraplength=1160,
            foreground="#555",
        ).pack(anchor="w", pady=(3, 0))

        body = ttk.PanedWindow(self, orient="vertical")
        body.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        list_frame = ttk.Frame(body)
        preview_frame = ttk.LabelFrame(body, text="Попередній перегляд", padding=7)
        body.add(list_frame, weight=3)
        body.add(preview_frame, weight=2)

        columns = ("selected", "id", "title", "sources", "published")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", selectmode="browse")
        headings = {
            "selected": "Вибір",
            "id": "Блок",
            "title": "Подія",
            "sources": "Джерел",
            "published": "Остання згадка",
        }
        widths = {"selected": 70, "id": 70, "title": 720, "sources": 80, "published": 180}
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], anchor="w", stretch=column == "title")
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<Button-1>", self._toggle_from_click, add="+")
        self.tree.bind("<space>", self._toggle_focused)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._show_preview())
        self.tree.bind("<Double-1>", lambda _event: self.open_selected())

        for group_id, row in self.candidates.items():
            self.tree.insert(
                "",
                "end",
                iid=str(group_id),
                values=(
                    "☐",
                    group_id,
                    str(row.get("title") or ""),
                    int(row.get("source_count") or 0),
                    str(row.get("published_at") or "—"),
                ),
            )

        self.preview = ScrolledText(preview_frame, wrap="word", height=11)
        self.preview.pack(fill="both", expand=True)
        self.preview.configure(state="disabled")

        actions = ttk.Frame(self, padding=(12, 0, 12, 12))
        actions.pack(fill="x")
        ttk.Button(actions, text="Вибрати всі", command=self.select_all).pack(side="left")
        ttk.Button(actions, text="Зняти вибір", command=self.clear_selection).pack(side="left", padx=6)
        ttk.Button(actions, text="Відкрити матеріал", command=self.open_selected).pack(side="left")
        ttk.Button(actions, text="Скасувати", command=self.destroy).pack(side="right")
        self.merge_button = ttk.Button(actions, text="Об’єднати вибрані", command=self.merge)
        self.merge_button.pack(side="right", padx=(0, 8))

        self._update_summary()
        first = self.tree.get_children()
        if first:
            self.tree.selection_set(first[0])
            self.tree.focus(first[0])
            self._show_preview()
        self.grab_set()
        self.focus_set()

    def _refresh_checks(self) -> None:
        target = self.selected_order[0] if self.selected_order else None
        selected = set(self.selected_order)
        for raw_id in self.tree.get_children(""):
            group_id = int(raw_id)
            values = list(self.tree.item(raw_id, "values"))
            if not values:
                continue
            values[0] = "★" if group_id == target else ("☑" if group_id in selected else "☐")
            self.tree.item(raw_id, values=values)
        self._update_summary()

    def _toggle(self, group_id: int) -> None:
        if group_id in self.selected_order:
            self.selected_order.remove(group_id)
        else:
            self.selected_order.append(group_id)
        self._refresh_checks()

    def _toggle_from_click(self, event: tk.Event) -> None:
        iid = self.tree.identify_row(int(event.y))
        column = self.tree.identify_column(int(event.x))
        if iid and column == "#1":
            self._toggle(int(iid))

    def _toggle_focused(self, _event: object | None = None) -> str:
        iid = self.tree.focus()
        if iid:
            self._toggle(int(iid))
        return "break"

    def _update_summary(self) -> None:
        total = len(self.candidates)
        selected = len(self.selected_order)
        target = f" · основний: #{self.selected_order[0]}" if self.selected_order else ""
        self.summary_var.set(f"Знайдено: {total} · вибрано: {selected}{target}")
        self.merge_button.configure(state="normal" if selected >= 2 else "disabled")

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
        self.selected_order = [int(raw_id) for raw_id in self.tree.get_children("")]
        self._refresh_checks()

    def clear_selection(self) -> None:
        self.selected_order.clear()
        self._refresh_checks()

    def open_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        row = self.candidates.get(int(selection[0]))
        url = str(row.get("url") or "") if row else ""
        if url:
            webbrowser.open(url, new=2)

    def merge(self) -> None:
        if len(self.selected_order) < 2:
            return
        selected = list(self.selected_order)
        self.grab_release()
        self.destroy()
        self.on_merge(selected)


class GroupMembersDialog(tk.Toplevel):
    """Edit the article membership of one already-merged pre-publication block."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        group_id: int,
        group_title: str,
        articles: Sequence[Mapping[str, object]],
        on_detach: Callable[[list[int]], None],
    ) -> None:
        super().__init__(parent)
        self.group_id = int(group_id)
        self.articles = {int(row["article_id"]): dict(row) for row in articles}
        self.on_detach = on_detach
        self.selected_ids: set[int] = set()

        self.title(f"Склад блоку #{self.group_id}")
        self.geometry("1220x760")
        self.minsize(860, 540)
        self.transient(parent.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        header = ttk.Frame(self, padding=(12, 10, 12, 6))
        header.pack(fill="x")
        ttk.Label(header, text=f"#{self.group_id} · {group_title}", font="TkHeadingFont", wraplength=1160).pack(anchor="w")
        ttk.Label(
            header,
            text=(
                "Позначте помилково додані новини. Вони НЕ видаляються з Data: після вилучення кожна "
                "повернеться у «Вхідні» окремим блоком. У початковому блоці має залишитися хоча б одна новина."
            ),
            wraplength=1160,
            foreground="#555",
        ).pack(anchor="w", pady=(4, 0))
        self.summary_var = tk.StringVar()
        ttk.Label(header, textvariable=self.summary_var, foreground="#555").pack(anchor="w", pady=(3, 0))

        body = ttk.PanedWindow(self, orient="vertical")
        body.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        list_frame = ttk.Frame(body)
        preview_frame = ttk.LabelFrame(body, text="Текст новини", padding=7)
        body.add(list_frame, weight=3)
        body.add(preview_frame, weight=2)

        columns = ("selected", "source", "title", "published")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", selectmode="browse")
        headings = {"selected": "Вилучити", "source": "Джерело", "title": "Назва", "published": "Час"}
        widths = {"selected": 85, "source": 190, "title": 700, "published": 180}
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], anchor="w", stretch=column == "title")
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<Button-1>", self._toggle_from_click, add="+")
        self.tree.bind("<space>", self._toggle_focused)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._show_preview())
        self.tree.bind("<Double-1>", lambda _event: self.open_selected())

        for article_id, row in self.articles.items():
            self.tree.insert(
                "",
                "end",
                iid=str(article_id),
                values=(
                    "☐",
                    str(row.get("source") or ""),
                    str(row.get("title") or ""),
                    str(row.get("published_at") or "—"),
                ),
            )

        self.preview = ScrolledText(preview_frame, wrap="word", height=11)
        self.preview.pack(fill="both", expand=True)
        self.preview.configure(state="disabled")

        actions = ttk.Frame(self, padding=(12, 0, 12, 12))
        actions.pack(fill="x")
        ttk.Button(actions, text="Зняти вибір", command=self.clear_selection).pack(side="left")
        ttk.Button(actions, text="Відкрити матеріал", command=self.open_selected).pack(side="left", padx=6)
        ttk.Button(actions, text="Скасувати", command=self.destroy).pack(side="right")
        self.detach_button = ttk.Button(actions, text="Вилучити вибрані з блоку", command=self.detach)
        self.detach_button.pack(side="right", padx=(0, 8))

        self._update_summary()
        first = self.tree.get_children()
        if first:
            self.tree.selection_set(first[0])
            self.tree.focus(first[0])
            self._show_preview()
        self.grab_set()
        self.focus_set()

    def _toggle(self, article_id: int) -> None:
        if article_id in self.selected_ids:
            self.selected_ids.remove(article_id)
        else:
            self.selected_ids.add(article_id)
        values = list(self.tree.item(str(article_id), "values"))
        if values:
            values[0] = "☑" if article_id in self.selected_ids else "☐"
            self.tree.item(str(article_id), values=values)
        self._update_summary()

    def _toggle_from_click(self, event: tk.Event) -> None:
        iid = self.tree.identify_row(int(event.y))
        column = self.tree.identify_column(int(event.x))
        if iid and column == "#1":
            self._toggle(int(iid))

    def _toggle_focused(self, _event: object | None = None) -> str:
        iid = self.tree.focus()
        if iid:
            self._toggle(int(iid))
        return "break"

    def _update_summary(self) -> None:
        selected = len(self.selected_ids)
        total = len(self.articles)
        remaining = total - selected
        self.summary_var.set(f"Новин у блоці: {total} · позначено для вилучення: {selected} · залишиться: {remaining}")
        self.detach_button.configure(state="normal" if 0 < selected < total else "disabled")

    def _show_preview(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        row = self.articles.get(int(selection[0]))
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

    def clear_selection(self) -> None:
        for article_id in tuple(self.selected_ids):
            self.selected_ids.remove(article_id)
            values = list(self.tree.item(str(article_id), "values"))
            if values:
                values[0] = "☐"
                self.tree.item(str(article_id), values=values)
        self._update_summary()

    def open_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        row = self.articles.get(int(selection[0]))
        url = str(row.get("url") or "") if row else ""
        if url:
            webbrowser.open(url, new=2)

    def detach(self) -> None:
        selected = sorted(self.selected_ids)
        if not selected or len(selected) >= len(self.articles):
            return
        self.grab_release()
        self.destroy()
        self.on_detach(selected)
