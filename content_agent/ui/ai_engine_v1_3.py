from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..ai_router_v1_2_1 import (
    AIProviderSecrets,
    AIRouterError,
    clear_router_cooldowns,
    last_ai_result_label,
    load_provider_secrets,
    router_overview,
    save_provider_secrets,
    test_ai_router,
)
from ..codex_engine_v1_3 import inspect_codex, install_codex, login_chatgpt
from ..codex_news_v1_3 import rewrite_group_with_codex, run_topic_prompt_with_codex
from ..editorial_memory import rank_editorial_examples, rank_topic_candidates
from ..models import RewriteResult
from ..local_ai_runtime_v1_2_2 import LocalAIRuntimeError, LocalAITarget, test_local_runtime
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
        frame = ttk.LabelFrame(parent, text="1. AI Router та редакційна пам’ять", padding=10)
        children = [child for child in parent.winfo_children() if child is not frame]
        pack_options: dict[str, object] = {"fill": "x", "pady": (0, 8)}
        if children:
            pack_options["before"] = children[0]
        frame.pack(**pack_options)
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(3, weight=1)

        self.ai_router_status_var = tk.StringVar(value="AI Router: перевірка не виконувалась")
        self.codex_status_var = tk.StringVar(value="Codex: перевірка не виконувалась")
        self.rowboat_status_var = tk.StringVar(value="Rowboat: перевірка не виконувалась")
        self.memory_graph_status_var = tk.StringVar(value="Редакційна пам’ять: готова до синхронізації")
        self.ai_local_runtime_status_var = tk.StringVar(
            value="Локальний резерв: спочатку використовується вже встановлена Ollama та її моделі; нічого автоматично не завантажується."
        )

        ttk.Label(frame, text="AI Router · автоматичний пріоритет", font="TkHeadingFont").grid(row=0, column=0, sticky="w")
        ttk.Label(frame, textvariable=self.ai_router_status_var, foreground="#555").grid(
            row=0, column=1, columnspan=4, sticky="w", padx=(10, 0)
        )
        ttk.Label(
            frame,
            text=(
                "Будь-яка AI-задача йде через один ланцюг: найякісніша доступна модель → наступна при quota/429/timeout/поганій відповіді. "
                "Недоступні моделі отримують cooldown і перевіряються знову автоматично."
            ),
            wraplength=1120,
            foreground="#555",
        ).grid(row=1, column=0, columnspan=5, sticky="w", pady=(4, 7))

        try:
            secrets = load_provider_secrets()
        except AIRouterError:
            secrets = AIProviderSecrets()
        self.ai_provider_vars = {
            "nvidia_api_key": tk.StringVar(value=secrets.nvidia_api_key),
            "gemini_api_key": tk.StringVar(value=secrets.gemini_api_key),
            "sambanova_api_key": tk.StringVar(value=secrets.sambanova_api_key),
            "cerebras_api_key": tk.StringVar(value=secrets.cerebras_api_key),
            "groq_api_key": tk.StringVar(value=secrets.groq_api_key),
            "openrouter_api_key": tk.StringVar(value=secrets.openrouter_api_key),
            "cloudflare_account_id": tk.StringVar(value=secrets.cloudflare_account_id),
            "cloudflare_api_token": tk.StringVar(value=secrets.cloudflare_api_token),
            "local_base_url": tk.StringVar(value=secrets.local_base_url),
            "local_model": tk.StringVar(value=secrets.local_model),
        }
        self.ai_local_enabled_var = tk.BooleanVar(value=secrets.local_enabled)

        rows = [
            ("NVIDIA NIM API Key", "nvidia_api_key", True),
            ("Google Gemini API Key", "gemini_api_key", True),
            ("SambaNova API Key", "sambanova_api_key", True),
            ("Cerebras API Key", "cerebras_api_key", True),
            ("Groq API Key", "groq_api_key", True),
            ("OpenRouter API Key", "openrouter_api_key", True),
        ]
        for index, (label, key, secret) in enumerate(rows, start=2):
            column = 0 if index < 5 else 2
            row = index if index < 5 else index - 3
            ttk.Label(frame, text=label).grid(row=row, column=column, sticky="w", pady=2)
            ttk.Entry(
                frame,
                textvariable=self.ai_provider_vars[key],
                show="•" if secret else "",
                width=46,
            ).grid(row=row, column=column + 1, sticky="ew", padx=(8, 14), pady=2)

        ttk.Label(frame, text="Cloudflare Account ID").grid(row=5, column=0, sticky="w", pady=2)
        ttk.Entry(frame, textvariable=self.ai_provider_vars["cloudflare_account_id"], width=46).grid(
            row=5, column=1, sticky="ew", padx=(8, 14), pady=2
        )
        ttk.Label(frame, text="Cloudflare API Token").grid(row=5, column=2, sticky="w", pady=2)
        ttk.Entry(frame, textvariable=self.ai_provider_vars["cloudflare_api_token"], show="•", width=46).grid(
            row=5, column=3, sticky="ew", padx=(8, 14), pady=2
        )

        ttk.Checkbutton(frame, text="Локальний аварійний AI · Ollama автоматично", variable=self.ai_local_enabled_var).grid(
            row=6, column=0, sticky="w", pady=(4, 2)
        )
        ttk.Entry(frame, textvariable=self.ai_provider_vars["local_base_url"], width=46).grid(
            row=6, column=1, sticky="ew", padx=(8, 14), pady=2
        )
        ttk.Label(frame, text="Запасна llama.cpp модель").grid(row=6, column=2, sticky="e", pady=2)
        ttk.Entry(frame, textvariable=self.ai_provider_vars["local_model"], width=28).grid(
            row=6, column=3, sticky="ew", padx=(8, 14), pady=2
        )

        ttk.Label(frame, textvariable=self.ai_local_runtime_status_var, foreground="#555", wraplength=1120).grid(
            row=7, column=0, columnspan=5, sticky="w", pady=(2, 4)
        )

        actions = ttk.Frame(frame)
        actions.grid(row=8, column=0, columnspan=5, sticky="w", pady=(7, 4))
        ttk.Button(actions, text="Зберегти AI-провайдери", command=self.save_ai_provider_settings).pack(side="left")
        ttk.Button(actions, text="Тест AI Router", command=self.test_ai_router_ui).pack(side="left", padx=(6, 0))
        ttk.Button(actions, text="Перевірити локальний AI", command=self.test_local_ai_ui).pack(side="left", padx=(6, 0))
        ttk.Button(actions, text="Скинути cooldown", command=self.clear_ai_router_cooldowns_ui).pack(side="left", padx=(6, 0))
        ttk.Button(actions, text="Встановити / відновити Codex", command=self.install_codex_ui).pack(side="left", padx=(16, 0))
        ttk.Button(actions, text="Увійти через ChatGPT", command=self.login_codex_ui).pack(side="left", padx=(6, 0))

        ttk.Label(frame, textvariable=self.codex_status_var, foreground="#555").grid(
            row=9, column=0, columnspan=5, sticky="w", pady=(2, 5)
        )
        ttk.Separator(frame, orient="horizontal").grid(row=10, column=0, columnspan=5, sticky="ew", pady=6)
        ttk.Label(frame, text="Rowboat / локальний граф пам’яті", font="TkHeadingFont").grid(row=11, column=0, sticky="w")
        ttk.Label(frame, textvariable=self.rowboat_status_var, foreground="#555").grid(
            row=11, column=1, columnspan=4, sticky="w", padx=(10, 0)
        )
        rowboat_actions = ttk.Frame(frame)
        rowboat_actions.grid(row=12, column=0, columnspan=5, sticky="w", pady=(5, 2))
        ttk.Button(rowboat_actions, text="Знайти Rowboat", command=self.check_rowboat_ui).pack(side="left")
        ttk.Button(rowboat_actions, text="Встановити Rowboat", command=self.install_rowboat_ui).pack(side="left", padx=(6, 0))
        ttk.Button(rowboat_actions, text="Відкрити Rowboat", command=self.open_rowboat_ui).pack(side="left", padx=(6, 0))
        ttk.Button(rowboat_actions, text="Синхронізувати пам’ять", command=self.sync_memory_ui).pack(side="left", padx=(6, 0))
        ttk.Button(rowboat_actions, text="Відкрити папку пам’яті", command=self.open_memory_ui).pack(side="left", padx=(6, 0))
        ttk.Label(frame, textvariable=self.memory_graph_status_var, foreground="#555").grid(
            row=13, column=0, columnspan=5, sticky="w", pady=(4, 0)
        )

    def _provider_secrets_from_ui(self) -> AIProviderSecrets:
        values = self.ai_provider_vars
        return AIProviderSecrets(
            gemini_api_key=values["gemini_api_key"].get(),
            nvidia_api_key=values["nvidia_api_key"].get(),
            sambanova_api_key=values["sambanova_api_key"].get(),
            cerebras_api_key=values["cerebras_api_key"].get(),
            groq_api_key=values["groq_api_key"].get(),
            openrouter_api_key=values["openrouter_api_key"].get(),
            cloudflare_account_id=values["cloudflare_account_id"].get(),
            cloudflare_api_token=values["cloudflare_api_token"].get(),
            local_enabled=self.ai_local_enabled_var.get(),
            local_base_url=values["local_base_url"].get(),
            local_model=values["local_model"].get(),
        )

    def save_ai_provider_settings(self) -> None:
        try:
            save_provider_secrets(self._provider_secrets_from_ui())
        except Exception as exc:
            self._show_error(exc)  # type: ignore[attr-defined]
            return
        self.refresh_ai_component_status()
        self.set_status("AI-провайдери збережено. Cooldown скинуто.")  # type: ignore[attr-defined]

    def test_local_ai_ui(self) -> None:
        try:
            values = self._provider_secrets_from_ui().normalized()
            save_provider_secrets(values)
        except Exception as exc:
            self._show_error(exc)  # type: ignore[attr-defined]
            return
        if not values.local_enabled:
            self.ai_local_runtime_status_var.set("Локальний резерв вимкнено.")
            self.set_status("Локальний аварійний AI вимкнено.")  # type: ignore[attr-defined]
            return

        def success(result: object) -> None:
            if not isinstance(result, LocalAITarget):
                self.set_status(f"Неправильний результат локальної перевірки: {result}")  # type: ignore[attr-defined]
                return
            clear_router_cooldowns()
            started = " · Ollama була запущена програмою" if result.started_by_app else ""
            self.ai_local_runtime_status_var.set(
                f"Локальний резерв готовий: {result.label}{started}. Нові моделі не встановлювалися і не завантажувалися."
            )
            self.refresh_ai_component_status()
            self.set_status(f"Локальний AI працює: {result.label}")  # type: ignore[attr-defined]

        def action() -> object:
            try:
                return test_local_runtime(
                    preferred_model=values.local_model,
                    manual_base_url=values.local_base_url,
                    manual_model=values.local_model,
                )
            except LocalAIRuntimeError:
                raise

        self.run_async(  # type: ignore[attr-defined]
            action,
            success,
            label="Перевіряю Ollama / локальний резерв",
            done_label="Локальний AI перевірено",
        )

    def clear_ai_router_cooldowns_ui(self) -> None:
        clear_router_cooldowns()
        self.refresh_ai_component_status()
        self.set_status("Cooldown AI Router скинуто.")  # type: ignore[attr-defined]

    def refresh_ai_component_status(self) -> None:
        if not hasattr(self, "ai_router_status_var"):
            return
        codex = inspect_codex()
        if not codex.installed:
            self.codex_status_var.set("Codex: не встановлено")
        elif codex.authenticated:
            suffix = f" · {codex.account_label}" if codex.account_label else ""
            self.codex_status_var.set(f"Codex {codex.version}: готовий{suffix}")
        else:
            self.codex_status_var.set(f"Codex {codex.version}: потрібен вхід через ChatGPT")
        try:
            rows = router_overview()
            configured = [row for row in rows if row["configured"]]
            healthy = [row for row in configured if not row["cooldown_seconds"]]
            cooldown = len(configured) - len(healthy)
            self.ai_router_status_var.set(
                f"AI Router: підключено {len(configured)} слотів · доступно зараз {len(healthy)}"
                + (f" · cooldown {cooldown}" if cooldown else "")
                + f" · останній: {last_ai_result_label()}"
            )
        except Exception as exc:
            self.ai_router_status_var.set(f"AI Router: {exc}")
        rowboat = inspect_rowboat()
        self.rowboat_status_var.set(
            f"Rowboat: знайдено · {rowboat.executable}" if rowboat.installed else "Rowboat: не знайдено"
        )
        self.memory_graph_status_var.set(f"Пам’ять: {rowboat.memory_root}")

    def test_ai_router_ui(self) -> None:
        self.save_ai_provider_settings()

        def success(result: object) -> None:
            self.refresh_ai_component_status()
            self.set_status(str(result))  # type: ignore[attr-defined]

        self.run_async(  # type: ignore[attr-defined]
            test_ai_router,
            success,
            label="AI Router: перевіряю пріоритетний ланцюг",
            done_label="AI Router перевірено",
        )

    def check_codex_ui(self) -> None:
        self.refresh_ai_component_status()
        self.set_status(self.codex_status_var.get())  # type: ignore[attr-defined]

    def install_codex_ui(self) -> None:
        def success(_result: object) -> None:
            clear_router_cooldowns()
            self.refresh_ai_component_status()
            self.set_status("Codex встановлено / відновлено.")  # type: ignore[attr-defined]

        self.run_async(install_codex, success, label="Встановлюю Codex", done_label="Codex встановлено")  # type: ignore[attr-defined]

    def login_codex_ui(self) -> None:
        def success(_result: object) -> None:
            clear_router_cooldowns()
            self.refresh_ai_component_status()
            self.set_status("Вхід через ChatGPT завершено. Codex знову доступний для AI Router.")  # type: ignore[attr-defined]

        self.run_async(login_chatgpt, success, label="Очікую вхід через ChatGPT", done_label="Codex авторизовано")  # type: ignore[attr-defined]

    def test_codex_ui(self) -> None:
        self.test_ai_router_ui()

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
            engine = last_ai_result_label()
            if config.learning_enabled:
                self.db.record_learning_event(  # type: ignore[attr-defined]
                    "rewrite_generated",
                    language=config.ui_language,
                    group_id=group.id,
                    payload={"model": engine, "fallback": engine != "Codex / ChatGPT", "examples": example_count},
                )
            self.refresh_groups()  # type: ignore[attr-defined]
            self.update_text_metrics()  # type: ignore[attr-defined]
            self.refresh_ai_component_status()
            self.set_status(  # type: ignore[attr-defined]
                f"Рерайт створено · AI: {engine} · джерел {rewrite_result.source_count_used} із {rewrite_result.source_count_total}"
                f" · прикладів пам’яті {example_count}"
            )

        self.run_async(  # type: ignore[attr-defined]
            action,
            success,
            label=f"AI Router: рерайт {group.source_count} джерел",
            done_label="AI-рерайт завершено",
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
        self.topic_search_status_var.set(f"AI Router перевіряє {len(shortlisted)} кандидатів…")  # type: ignore[attr-defined]

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
            self.refresh_ai_component_status()
            if not candidate_data:
                self.topic_search_status_var.set(self.t("Схожих матеріалів для об’єднання не знайдено."))  # type: ignore[attr-defined]
                return
            self.topic_search_status_var.set(
                f"Кандидатів на об’єднання: {len(candidate_data)} · AI: {last_ai_result_label()}"
            )  # type: ignore[attr-defined]
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
            label=f"AI Router аналізує схожість: {len(shortlisted)} кандидатів",
            done_label="Пошук схожих завершено",
        )
