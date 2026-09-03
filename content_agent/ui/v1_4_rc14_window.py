from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

from .inbox_management_v1_4_rc14 import GroupMembersDialog, KeywordMergeDialog
from .v1_4_rc13_window import MainWindow as Rc13MainWindow


class MainWindow(Rc13MainWindow):
    """v1.4.0-rc14: deterministic Inbox keyword merge and safe unmerge editing."""

    VERSION_LABEL = "1.4.0-rc14"

    def __init__(self, root: tk.Tk, database, config) -> None:
        self._rc14_inbox_tools_frame: ttk.Frame | None = None
        self._rc14_keyword_entry: ttk.Entry | None = None
        self._rc14_keyword_search_button: ttk.Button | None = None
        self._rc14_members_button: ttk.Button | None = None
        self._rc14_keyword_serial = 0
        super().__init__(root, database, config)
        self._install_rc14_inbox_tools()
        self._apply_v14_labels()

    def _apply_v14_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v1.4.0-rc14")

    def _apply_language(self, refresh: bool = True) -> None:
        super()._apply_language(refresh=refresh)
        self._apply_v14_labels()

    def _install_rc14_inbox_tools(self) -> None:
        if self._rc14_inbox_tools_frame is not None:
            return
        tree = getattr(self, "groups_tree", None)
        if tree is None:
            return
        tree_frame = tree.master
        tab = tree_frame.master
        bar = ttk.Frame(tab)
        # Insert immediately above the Inbox table without rebuilding the legacy
        # toolbar or disturbing RC11's authoritative Treeview ordering.
        bar.pack(fill="x", pady=(0, 6), before=tree_frame)
        self._rc14_inbox_tools_frame = bar

        ttk.Label(bar, text="Пошук у Вхідних:").pack(side="left")
        self.keyword_search_var = tk.StringVar()
        entry = ttk.Entry(bar, textvariable=self.keyword_search_var, width=42)
        entry.pack(side="left", padx=(6, 5), fill="x", expand=True)
        entry.bind("<Return>", lambda _event: self.search_inbox_keywords())
        self._rc14_keyword_entry = entry

        search_button = ttk.Button(bar, text="Знайти за ключовими словами", command=self.search_inbox_keywords)
        search_button.pack(side="left", padx=(0, 6))
        self._rc14_keyword_search_button = search_button

        members_button = ttk.Button(bar, text="Редагувати склад блоку", command=self.edit_selected_group_members)
        members_button.pack(side="left")
        self._rc14_members_button = members_button

    def search_inbox_keywords(self) -> None:
        query = str(getattr(self, "keyword_search_var", tk.StringVar()).get() or "").strip()
        if not query:
            self.msg.showinfo(
                "Пошук у Вхідних",
                "Введіть одне або кілька ключових слів. Пошук іде одночасно по назвах і повному тексту новин.",
                parent=self.root,
            )
            return
        self._rc14_keyword_serial += 1
        serial = self._rc14_keyword_serial
        self.topic_search_status_var.set(f"Шукаю у всіх нових/чернеткових блоках: {query}…")
        if self._rc14_keyword_search_button is not None:
            self._rc14_keyword_search_button.configure(state="disabled")

        def runner() -> None:
            try:
                groups = self.db.search_inbox_groups(query, limit=1000)
            except Exception as exc:
                self._post_ui(lambda error=exc, value=serial: self._keyword_search_failed(value, error))
                return
            self._post_ui(lambda result=groups, value=serial: self._keyword_search_done(value, query, result))

        threading.Thread(target=runner, name="inbox-keyword-search", daemon=True).start()

    def _keyword_search_failed(self, serial: int, error: Exception) -> None:
        if serial != self._rc14_keyword_serial:
            return
        if self._rc14_keyword_search_button is not None:
            self._rc14_keyword_search_button.configure(state="normal")
        self.topic_search_status_var.set(f"Пошук за ключовими словами не завершено: {error}")
        self._show_error(error)

    def _keyword_search_done(self, serial: int, query: str, groups) -> None:
        if serial != self._rc14_keyword_serial or getattr(self, "_closing", False):
            return
        if self._rc14_keyword_search_button is not None:
            self._rc14_keyword_search_button.configure(state="normal")
        candidate_data: list[dict[str, object]] = []
        for group in groups:
            candidate_data.append(
                {
                    "group_id": group.id,
                    "title": group.canonical_title,
                    "source_count": group.source_count,
                    "published_at": group.last_published_at or "—",
                    "text": group.combined_text[:14000],
                    "url": group.primary_url,
                }
            )
        self.topic_search_status_var.set(
            f"Пошук «{query}»: знайдено блоків {len(candidate_data)}. "
            "У вікні нижче можна вибрати потрібні й об’єднати."
        )
        if not candidate_data:
            self.msg.showinfo(
                "Пошук у Вхідних",
                f"За запитом «{query}» не знайдено блоків, де присутні всі введені ключові слова.",
                parent=self.root,
            )
            return
        KeywordMergeDialog(
            self.root,
            query=query,
            candidates=candidate_data,
            on_merge=self._merge_keyword_groups,
        )

    def _merge_keyword_groups(self, group_ids: list[int]) -> None:
        ordered: list[int] = []
        for raw in group_ids:
            group_id = int(raw)
            if group_id not in ordered:
                ordered.append(group_id)
        if len(ordered) < 2:
            return
        try:
            groups = [self.db.get_group(group_id) for group_id in ordered]
        except Exception as exc:
            self._show_error(exc)
            return
        target = groups[0]
        details = "\n".join(f"• #{group.id}: {group.canonical_title[:120]}" for group in groups[:12])
        if len(groups) > 12:
            details += f"\n• …ще {len(groups) - 12}"
        if not self.msg.askyesno(
            "Об’єднати знайдені новини",
            f"Об’єднати {len(groups)} блоки?\n\nОсновним залишиться #{target.id}: {target.canonical_title}\n\n{details}",
            parent=self.root,
        ):
            return
        try:
            moved_articles = self.db.merge_groups(target.id, ordered)
            learned_pairs = 0
            if self.config.learning_enabled:
                for source_group in groups[1:]:
                    if self.db.record_topic_feedback(
                        target.combined_text or target.canonical_title,
                        source_group.combined_text or source_group.canonical_title,
                        decision="merged",
                        language=self.config.ui_language,
                    ):
                        learned_pairs += 1
                self.db.record_learning_event(
                    "manual_keyword_groups_merged",
                    language=self.config.ui_language,
                    group_id=target.id,
                    anchor_group_id=target.id,
                    payload={
                        "merged_group_ids": ordered[1:],
                        "moved_articles": moved_articles,
                        "query": str(getattr(self, "keyword_search_var", tk.StringVar()).get() or "").strip(),
                    },
                )
        except Exception as exc:
            self._show_error(exc)
            return

        self.refresh_groups()
        target_iid = str(target.id)
        if self.groups_tree.exists(target_iid):
            self.groups_tree.selection_set(target_iid)
            self.groups_tree.focus(target_iid)
            self.groups_tree.see(target_iid)
        if self.current_group_id in set(ordered):
            self.load_group(target.id)
        merged = self.db.get_group(target.id)
        self.set_status(
            f"Пошук/об’єднання: створено блок #{target.id} із {merged.source_count} новин; "
            f"перенесено {moved_articles}; навчальних пар: {learned_pairs}."
        )

    def edit_selected_group_members(self) -> None:
        group_ids = self._selected_group_ids()
        if len(group_ids) != 1:
            self.msg.showinfo(
                "Склад блоку",
                "Оберіть рівно один уже об’єднаний блок у «Вхідних».",
                parent=self.root,
            )
            return
        group_id = int(group_ids[0])
        try:
            group = self.db.get_group(group_id)
        except Exception as exc:
            self._show_error(exc)
            return
        if group.source_count < 2 or len(group.articles) < 2:
            self.msg.showinfo("Склад блоку", "У цьому блоці лише одна новина.", parent=self.root)
            return
        rows = [
            {
                "article_id": article.id,
                "source": article.source_name,
                "title": article.title,
                "published_at": article.published_at or "—",
                "text": article.raw_text,
                "url": article.url,
            }
            for article in group.articles
        ]
        GroupMembersDialog(
            self.root,
            group_id=group.id,
            group_title=group.canonical_title,
            articles=rows,
            on_detach=lambda selected, value=group.id: self._detach_group_articles(value, selected),
        )

    def _detach_group_articles(self, group_id: int, article_ids: list[int]) -> None:
        try:
            before = self.db.get_group(int(group_id))
        except Exception as exc:
            self._show_error(exc)
            return
        article_by_id = {article.id: article for article in before.articles}
        selected = [int(article_id) for article_id in article_ids if int(article_id) in article_by_id]
        if not selected:
            return
        names = "\n".join(f"• {article_by_id[item].title[:130]}" for item in selected[:12])
        if len(selected) > 12:
            names += f"\n• …ще {len(selected) - 12}"
        if not self.msg.askyesno(
            "Вилучити новини з блоку",
            f"Вилучити з блоку #{group_id} новин: {len(selected)}?\n\n{names}\n\n"
            "Вони не видаляються. Кожна повернеться у «Вхідні» окремим блоком. "
            "Поточний рерайт блоку буде скинуто, бо змінився набір джерел.",
            parent=self.root,
        ):
            return
        try:
            created = self.db.detach_articles_from_group(group_id, selected)
            remaining = self.db.get_group(group_id)
            learned_pairs = 0
            if self.config.learning_enabled:
                anchor_text = remaining.combined_text or remaining.canonical_title
                for article_id in selected:
                    article = article_by_id[article_id]
                    candidate_text = f"{article.title}\n{article.raw_text}".strip()
                    if self.db.record_topic_feedback(
                        anchor_text,
                        candidate_text,
                        decision="not_related",
                        language=self.config.ui_language,
                    ):
                        learned_pairs += 1
                self.db.record_learning_event(
                    "manual_articles_detached",
                    language=self.config.ui_language,
                    group_id=group_id,
                    anchor_group_id=group_id,
                    payload={"article_ids": selected, "created_group_ids": created},
                )
        except Exception as exc:
            self._show_error(exc)
            return

        self.refresh_groups()
        iid = str(group_id)
        if self.groups_tree.exists(iid):
            self.groups_tree.selection_set(iid)
            self.groups_tree.focus(iid)
            self.groups_tree.see(iid)
        if self.current_group_id == group_id:
            self.load_group(group_id)
        self.set_status(
            f"Із блоку #{group_id} вилучено {len(selected)} новин. "
            f"Створено окремих блоків: {len(created)}; у початковому лишилося: {remaining.source_count}. "
            f"Позначено як не пов’язані для навчання: {learned_pairs}."
        )
