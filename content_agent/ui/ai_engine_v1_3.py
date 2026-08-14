from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..codex_engine_v1_3 import (
    CodexEngineError,
    inspect_codex,
    install_codex,
    login_chatgpt,
    test_codex,
)
from ..codex_news_v1_3 import rewrite_group_with_codex, run_topic_prompt_with_codex
from ..editorial_memory import rank_editorial_examples, rank_topic_candidates
from ..models import RewriteResult
from ..rowboat_bridge_v1_3 import (
    inspect_rowboat,
    install_rowboat,
    memory_context,
    open_memory_folder,
    open_rowboat,
    sync_editorial_memory,
)
from ..topic_search import build_topic_prompt, merge_local_and_ollama
from .topic_candidates_dialog import TopicCandidatesDialog


class AIEngineV13Mixin:
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[misc]
        self._replace_ollama_settings_panel()
        self.root.after(500, self.refresh_ai_component_status)  # type: ignore[attr-defined]

    def _prewarm_ollama_model_async(self, model: str | None = None) -> None:
        del model
        return

    def _replace_ollama_settings_panel(self) -> None:
        target = None
        stack = list(self.notebook.winfo_children())  # type: ignore[attr-defined]
        while stack:
            widget = stack.pop()
            if isinstance(widget, ttk.LabelFrame):
                try:
                    label = str(widget.cget("text"))
                except tk.TclError:
                    label = ""
                if label.startswith("1. Ollama"):
                    target = widget
                    break
            stack.extend(widget.winfo_children())
        if target is None:
            return
        parent = target.master
        target.destroy()
        frame = ttk.LabelFrame(parent, text="1. AI та редакційна пам’ять", padding=10)
        children = [child for child in parent.winfo_children() if child is not frame]
        pack_options: dict[str, object] = {"fill": "x", "pady": (0, 8)}
        if children:
            pack_options["before"] = children[0]
        frame.pack(**pack_options)
        frame.columnconfigure(1, weight=1)

        self.codex_status_var = tk.StringVar(value="Codex: перевірка не виконувалась")
        self.rowboat_status_var = tk.StringVar(value="Rowboat: перевірка не виконувалась")
        self.memory_graph_status_var = tk.StringVar(value="Редакційна пам’ять: готова до синхронізації")

        ttk.Label(frame, text="Codex / ChatGPT", font="TkHeadingFont").grid(row=0, column=0, sticky="w")
        ttk.Label(frame, textvariable=self.codex_status_var, foreground="#555").grid(row=0, column=1, columnspan=4, sticky="w", padx=(10, 0))
        ttk.Button(frame, text="Перевірити Codex", command=self.check_codex_ui).grid(row=1, column=0, padx=(0, 6), pady=(6, 4), sticky="w")
        ttk.Button(frame, text="Встановити / відновити Codex", command=self.install_codex_ui).grid(row=1, column=1, padx=6, pady=(6, 4), sticky="w")
        ttk.Button(frame, text="Увійти через ChatGPT", command=self.login_codex_ui).grid(row=1, column=2, padx=6, pady=(6, 4), sticky="w")
        ttk.Button(frame, text="Тест AI", command=self.test_codex_ui).grid(row=1, column=3, padx=6, pady=(6, 4), sticky="w")

        ttk.Separator(frame, orient="horizontal").grid(row=2, column=0, columnspan=5, sticky="ew", pady=8)
        ttk.Label(frame, text="Rowboat / локальний граф пам’яті", font="TkHeadingFont").grid(row=3, column=0, sticky="w")
        ttk.Label(frame, textvariable=self.rowboat_status_var, foreground="#555").grid(row=3, column=1, columnspan=4, sticky="w", padx=(10, 0))
        ttk.Button(frame, text="Знайти Rowboat", command=self.check_rowboat_ui).grid(row=4, column=0, padx=(0, 6), pady=(6, 4), sticky="w")
        ttk.Button(frame, text="Встановити Rowboat", command=self.install_rowboat_ui).grid(row=4, column=1, padx=6, pady=(6, 4), sticky="w")
        ttk.Button(frame, text="Відкрити Rowboat", command=self.open_rowboat_ui).grid(row=4, column=2, padx=6, pady=(6, 4), sticky="w")
        ttk.Button(frame, text="Синхронізувати пам’ять", command=self.sync_memory_ui).grid(row=4, column=3, padx=6, pady=(6, 4), sticky="w")
        ttk.Button(frame, text="Відкрити папку пам’яті", command=self.open_memory_ui).grid(row=4, column=4, padx=(6, 0), pady=(6, 4), sticky="w")
        ttk.Label(frame, textvariable=self.memory_graph_status_var, foreground="#555").grid(row=5, column=0, columnspan=5, sticky="w", pady=(4, 0))
        ttk.Label(
            frame,
            text=(
                "Ollama більше не використовується. Codex виконує рерайт і семантичний аналіз; "
                "редакційна пам’ять зберігається локально у Markdown-графі."
            ),
            wraplength=1050,
            foreground="#555",
        ).grid(row=6, column=0, columnspan=5, sticky="w", pady=(8, 0))

    def refresh_ai_component_status(self) -> None:
        if not hasattr(self, "codex_status_var"):
            return
        codex = inspect_codex()
        if not codex.installed:
            self.codex_status_var.set("Codex: не встановлено")
        elif codex.authenticated:
            suffix = f" · {codex.account_label}" if codex.account_label else ""
            self.codex_status_var.set(f"Codex {codex.version}: готовий{suffix}")
        else:
            self.codex_status_var.set(f"Codex {codex.version}: потрібен вхід через ChatGPT")
        rowboat = inspect_rowboat()
        self.rowboat_status_var.set(
            f"Rowboat: знайдено · {rowboat.executable}" if rowboat.installed else "Rowboat: не знайдено"
        )
        self.memory_graph_status_var.set(f"Пам’ять: {rowboat.memory_root}")

    def check_codex_ui(self) -> None:
        self.refresh_ai_component_status()
        self.set_status(self.codex_status_var.get())  # type: ignore[attr-defined]

    def install_codex_ui(self) -> None:
        def success(_result: object) -> None:
            self.refresh_ai_component_status()
            self.set_status("Codex встановлено / відновлено.")  # type: ignore[attr-defined]
        self.run_async(install_codex, success, label="Встановлюю Codex", done_label="Codex встановлено")  # type: ignore[attr-defined]

    def login_codex_ui(self) -> None:
        def success(_result: object) -> None:
            self.refresh_ai_component_status()
            self.set_status("Вхід через ChatGPT завершено. Codex готовий.")  # type: ignore[attr-defined]
        self.run_async(login_chatgpt, success, label="Очікую вхід через ChatGPT", done_label="Codex авторизовано")  # type: ignore[attr-defined]

    def test_codex_ui(self) -> None:
        def success(result: object) -> None:
            self.refresh_ai_component_status()
            self.set_status(str(result))  # type: ignore[attr-defined]
        self.run_async(test_codex, success, label="Перевіряю Codex", done_label="Codex відповідає")  # type: ignore[attr-defined]

    def check_rowboat_ui(self) -> None:
        self.refresh_ai_component_status()
        status = inspect_rowboat()
        if not status.installed:
            self.msg.showinfo(  # type: ignore[attr-defined]
                "Rowboat",
                "Rowboat не знайдено. Натисніть «Встановити Rowboat». Локальний Markdown-граф пам’яті вже створено.",
                parent=self.root,  # type: ignore[attr-defined]
            )

    def install_rowboat_ui(self) -> None:
        def success(result: object) -> None:
            self.refresh_ai_component_status()
            self.set_status(f"Rowboat встановлено: {result}")  # type: ignore[attr-defined]
        self.run_async(install_rowboat, success, label="Завантажую та встановлюю Rowboat", done_label="Rowboat встановлено")  # type: ignore[attr-defined]

    def open_rowboat_ui(self) -> None:
        try:
            open_rowboat()
        except Exception as exc:
            self._show_error(exc)  # type: ignore[attr-defined]

    def sync_memory_ui(self) -> None:
        def action() -> object:
            return sync_editorial_memory(self.db)  # type: ignore[attr-defined]
        def success(result: object) -> None:
            values = dict(result) if isinstance(result, dict) else {}
            self.memory_graph_status_var.set(
                f"Пам’ять синхронізовано: прикладів {values.get('examples', 0)}, рішень {values.get('decisions', 0)}."
            )
        self.run_async(action, success, label="Синхронізую редакційну пам’ять", done_label="Пам’ять синхронізовано")  # type: ignore[attr-defined]

    def open_memory_ui(self) -> None:
        try:
            open_memory_folder()
        except Exception as exc:
            self._show_error(exc)  # type: ignore[attr-defined]

    def rewrite_current(self) -> None:
        if self.current_group_id is None:  # type: ignore[attr-defined]
            self.msg.showinfo("Редактор", "Спочатку прийміть блок у роботу.", parent=self.root)  # type: ignore[attr-defined]
            return
        self.db.set_group_options(self.current_group_id, include_source_link=self.include_source_var.get())  # type: ignore[attr-defined]
        group = self.db.get_group(self.current_group_id)  # type: ignore[attr-defined]
        config = self.config  # type: ignore[attr-defined]

        def action() -> object:
            sync_editorial_memory(self.db)  # type: ignore[attr-defined]
            examples = rank_editorial_examples(
                group.combined_text,
                self.db.list_editorial_examples(language=config.ui_language),  # type: ignore[attr-defined]
                limit=config.learning_examples_limit if config.learning_enabled else 0,
            )
            graph = memory_context(group.combined_text, limit=6)
            result = rewrite_group_with_codex(group, examples, graph_memory=graph)
            return result, len(examples)

        def success(result: object) -> None:
            rewrite_result, example_count = result  # type: ignore[misc]
            assert isinstance(rewrite_result, RewriteResult)
            self.same_text_var.set(True)  # type: ignore[attr-defined]
            self.headline_var.set(rewrite_result.headline)  # type: ignore[attr-defined]
            self._set_text(self.fact_card_text, rewrite_result.fact_card)  # type: ignore[attr-defined]
            self._set_text(self.text_widgets["rewrite"], rewrite_result.rewrite)  # type: ignore[attr-defined]
            self.db.set_group_ai_draft(group.id, rewrite_result.rewrite)  # type: ignore[attr-defined]
            self.db.save_group_rewrite(  # type: ignore[attr-defined]
                group.id,
                headline=rewrite_result.headline,
                fact_card=rewrite_result.fact_card,
                rewrite_text=rewrite_result.rewrite,
                platform_texts=rewrite_result.platform_texts,
            )
            if config.learning_enabled:
                self.db.record_learning_event(  # type: ignore[attr-defined]
                    "rewrite_generated",
                    language=config.ui_language,
                    group_id=group.id,
                    payload={"model": "codex-chatgpt", "fallback": False, "examples": example_count},
                )
            self.refresh_groups()  # type: ignore[attr-defined]
            self.update_text_metrics()  # type: ignore[attr-defined]
            self.set_status(  # type: ignore[attr-defined]
                f"Рерайт створено через Codex / ChatGPT · джерел {rewrite_result.source_count_used} із {rewrite_result.source_count_total}"
                f" · прикладів пам’яті {example_count}"
            )

        self.run_async(  # type: ignore[attr-defined]
            action,
            success,
            label=f"Рерайт через Codex: {group.source_count} джерел",
            done_label="Рерайт Codex завершено",
        )

    def find_all_by_topic(self) -> None:
        anchor_id = self._require_single_group_id("Пошук схожих за темою матеріалів")  # type: ignore[attr-defined]
        if anchor_id is None:
            return
        try:
            anchor = self.db.get_group(anchor_id)  # type: ignore[attr-defined]
        except Exception as exc:
            self._show_error(exc)  # type: ignore[attr-defined]
            return
        candidate_rows = self.db.topic_candidate_rows(anchor_id)  # type: ignore[attr-defined]
        topic_feedback = self.db.list_topic_feedback(language=self.config.ui_language) if self.config.learning_enabled else []  # type: ignore[attr-defined]
        local_candidates = rank_topic_candidates(
            anchor.combined_text or anchor.canonical_title,
            candidate_rows,
            feedback=topic_feedback,
            limit=24,
            language=self.config.ui_language,  # type: ignore[attr-defined]
        )
        if not local_candidates:
            self.topic_search_status_var.set(self.t("Схожих матеріалів для об’єднання не знайдено."))  # type: ignore[attr-defined]
            return
        rows_by_id = {int(row["group_id"]): row for row in candidate_rows}
        shortlisted = [rows_by_id[item.group_id] for item in local_candidates if item.group_id in rows_by_id]
        self.topic_search_status_var.set(f"Codex перевіряє {len(shortlisted)} кандидатів…")  # type: ignore[attr-defined]

        def action() -> object:
            sync_editorial_memory(self.db)  # type: ignore[attr-defined]
            prompt = build_topic_prompt(
                anchor.canonical_title,
                anchor.combined_text,
                shortlisted,
                feedback=topic_feedback,
                language=self.config.ui_language,  # type: ignore[attr-defined]
            )
            graph = memory_context(anchor.combined_text or anchor.canonical_title, limit=8)
            model_matches = run_topic_prompt_with_codex(prompt, graph_memory=graph)
            return merge_local_and_ollama(local_candidates, model_matches, minimum_score=45)

        def success(result: object) -> None:
            matches = list(result) if isinstance(result, list) else []
            candidate_data: list[dict[str, object]] = []
            for match in matches:
                row = rows_by_id.get(match.group_id)
                if row is not None:
                    candidate_data.append({**row, "score": match.score, "reason": match.reason})
            if not candidate_data:
                self.topic_search_status_var.set(self.t("Схожих матеріалів для об’єднання не знайдено."))  # type: ignore[attr-defined]
                return
            self.topic_search_status_var.set(f"Кандидатів на об’єднання: {len(candidate_data)}")  # type: ignore[attr-defined]
            TopicCandidatesDialog(
                self.root,  # type: ignore[attr-defined]
                anchor_id=anchor_id,
                anchor_title=anchor.canonical_title,
                candidates=candidate_data,
                language=self.config.ui_language,  # type: ignore[attr-defined]
                on_merge=lambda selected, all_ids: self._merge_topic_candidates(anchor_id, selected, all_ids),  # type: ignore[attr-defined]
            )

        self.run_async(  # type: ignore[attr-defined]
            action,
            success,
            label=f"Codex аналізує схожість: {len(shortlisted)} кандидатів",
            done_label="Пошук схожих завершено",
        )
