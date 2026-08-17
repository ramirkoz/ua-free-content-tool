from __future__ import annotations

import threading

from ..ai_router_v1_2_1 import last_ai_result_label
from ..codex_news_v1_3 import rewrite_group_with_codex
from ..editorial_memory import rank_editorial_examples
from ..global_duplicates_v1_2_2_rc7 import (
    DuplicateCluster,
    DuplicateSearchCancelled,
    find_global_duplicate_clusters,
    last_duplicate_search_label,
)
from ..models import NewsGroup, RewriteResult
from ..rowboat_bridge_v1_3 import memory_context, sync_editorial_memory
from .global_duplicates_dialog_v1_3_rc6 import GlobalDuplicatesDialog


class AIWorkflowRC6Mixin:
    def rewrite_current(self) -> None:
        group_id = getattr(self, "current_group_id", None)
        if group_id is None:
            self.msg.showinfo("Редактор", "Спочатку прийміть блок у роботу.", parent=self.root)  # type: ignore[attr-defined]
            return
        include_source_link = bool(self.include_source_var.get())  # type: ignore[attr-defined]
        config = self.config  # type: ignore[attr-defined]

        def action() -> object:
            self.db.set_group_options(group_id, include_source_link=include_source_link)  # type: ignore[attr-defined]
            group = self.db.get_group(group_id)  # type: ignore[attr-defined]
            sync_editorial_memory(self.db)  # type: ignore[attr-defined]
            examples = rank_editorial_examples(
                group.combined_text,
                self.db.list_editorial_examples(language=config.ui_language),  # type: ignore[attr-defined]
                limit=config.learning_examples_limit if config.learning_enabled else 0,
            )
            graph = memory_context(group.combined_text, limit=6)
            rewrite = rewrite_group_with_codex(group, examples, graph_memory=graph)
            return group, rewrite, len(examples)

        def success(result: object) -> None:
            group, rewrite_result, example_count = result  # type: ignore[misc]
            assert isinstance(group, NewsGroup)
            assert isinstance(rewrite_result, RewriteResult)
            if getattr(self, "current_group_id", None) != group.id:
                self.set_status(  # type: ignore[attr-defined]
                    f"Рерайт блока #{group.id} готовий і збережений; зараз відкрито інший блок."
                )
            else:
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
            if getattr(self, "current_group_id", None) == group.id:
                self.update_text_metrics()  # type: ignore[attr-defined]
            self.set_status(  # type: ignore[attr-defined]
                f"Рерайт створено · AI: {engine} · джерел {rewrite_result.source_count_used} із {rewrite_result.source_count_total}"
                f" · прикладів пам'яті {example_count}"
            )

        self.run_async(  # type: ignore[attr-defined]
            action,
            success,
            label="Готую матеріали й запускаю AI Router у фоні",
            done_label="AI-рерайт завершено",
        )

    def _duplicate_search_button_rc6(self):
        stack = list(self.root.winfo_children())  # type: ignore[attr-defined]
        while stack:
            widget = stack.pop()
            try:
                text = str(widget.cget("text"))
            except Exception:
                text = ""
            if text in {"Пошук схожих за темою матеріалів", "Скасувати пошук", "Скасовую…"}:
                return widget
            try:
                stack.extend(widget.winfo_children())
            except Exception:
                pass
        return None

    def find_all_by_topic(self) -> None:
        self.topic_search_status_var.set("Швидкий пошук кандидатів на об'єднання…")  # type: ignore[attr-defined]
        cancel_event = threading.Event()
        self._duplicate_search_cancel_event = cancel_event  # type: ignore[attr-defined]
        button = self._duplicate_search_button_rc6()
        original_text = "Пошук схожих за темою матеріалів"
        if button is not None:
            try:
                original_text = str(button.cget("text")) or original_text
            except Exception:
                pass
            if button in self.operation_buttons:  # type: ignore[attr-defined]
                self.operation_buttons.remove(button)  # type: ignore[attr-defined]

        def restore_button() -> None:
            if getattr(self, "_duplicate_search_cancel_event", None) is cancel_event:
                self._duplicate_search_cancel_event = None  # type: ignore[attr-defined]
            if button is not None:
                try:
                    button.configure(text=original_text, command=self.find_all_by_topic, state="normal")
                except Exception:
                    pass
                if button not in self.operation_buttons:  # type: ignore[attr-defined]
                    self.operation_buttons.append(button)  # type: ignore[attr-defined]

        def progress(message: str) -> None:
            def apply() -> None:
                if getattr(self, "_duplicate_search_cancel_event", None) is cancel_event:
                    self.operation_detail_var.set(message)  # type: ignore[attr-defined]
                    self.topic_search_status_var.set(message)  # type: ignore[attr-defined]
            try:
                self.root.after(0, apply)  # type: ignore[attr-defined]
            except Exception:
                pass

        def cancel_search() -> None:
            cancel_event.set()
            self.topic_search_status_var.set("Скасовую пошук…")  # type: ignore[attr-defined]
            if button is not None:
                try:
                    button.configure(text="Скасовую…", state="disabled")
                except Exception:
                    pass

        def action() -> object:
            try:
                groups = self.db.list_groups(status="new", limit=1000)  # type: ignore[attr-defined]
                if len(groups) < 2:
                    return "ok", groups, []
                clusters = find_global_duplicate_clusters(
                    groups,
                    cancel_event=cancel_event,
                    progress=progress,
                    deadline_seconds=45,
                )
                return "ok", groups, clusters
            except DuplicateSearchCancelled as exc:
                return "cancelled", [], str(exc)
            except Exception as exc:
                return "error", [], exc

        def success(result: object) -> None:
            restore_button()
            status, groups, payload = result  # type: ignore[misc]
            if status == "cancelled":
                self.topic_search_status_var.set(str(payload))  # type: ignore[attr-defined]
                self.set_status("Пошук об'єднань скасовано.")  # type: ignore[attr-defined]
                return
            if status == "error":
                self._show_error(payload)  # type: ignore[attr-defined]
                return
            groups = list(groups)
            clusters = list(payload)
            if len(groups) < 2:
                self.topic_search_status_var.set("Для глобального порівняння потрібно щонайменше 2 нові блоки.")  # type: ignore[attr-defined]
                return
            engine = last_duplicate_search_label()
            if not clusters:
                self.topic_search_status_var.set(  # type: ignore[attr-defined]
                    f"{engine}: перевірено {len(groups)} нових блоків. Дублікатів для об'єднання не запропоновано."
                )
                return
            self.topic_search_status_var.set(  # type: ignore[attr-defined]
                f"{engine}: перевірено {len(groups)} нових блоків і запропоновано {len(clusters)} об'єднань."
            )
            by_id = {group.id: group for group in groups}
            GlobalDuplicatesDialog(
                self.root,  # type: ignore[attr-defined]
                clusters=clusters,
                groups=by_id,
                on_apply=lambda selected: self._merge_global_clusters_rc6(selected, by_id),
            )

        def timeout(_message: str) -> None:
            cancel_event.set()
            restore_button()
            self.topic_search_status_var.set(
                "Пошук зупинено за 55 секунд. Наступний запуск почнеться з чистого стану."
            )  # type: ignore[attr-defined]

        self.run_async(  # type: ignore[attr-defined]
            action,
            success,
            label="Швидкий пошук об'єднань у фоні",
            done_label="Глобальний пошук дублікатів завершено",
            timeout_seconds=55,
            timeout_message="Пошук об'єднань перевищив 55 секунд і був зупинений.",
            on_timeout=timeout,
        )
        if button is not None and getattr(self, "operation_running", False):
            try:
                button.configure(text="Скасувати пошук", command=cancel_search, state="normal")
            except Exception:
                pass

    def _merge_global_clusters_rc6(
        self,
        clusters: list[DuplicateCluster],
        groups: dict[int, NewsGroup],
    ) -> None:
        if not clusters:
            return

        def action() -> object:
            merged_clusters = 0
            merged_groups = 0
            for cluster in clusters:
                members = [groups[group_id] for group_id in cluster.group_ids if group_id in groups]
                if len(members) < 2:
                    continue
                target = max(members, key=lambda item: (item.source_count, -item.id))
                others = [item for item in members if item.id != target.id]
                for item in others:
                    self.db.record_topic_feedback(  # type: ignore[attr-defined]
                        target.combined_text or target.canonical_title,
                        item.combined_text or item.canonical_title,
                        decision="merged",
                        language=self.config.ui_language,  # type: ignore[attr-defined]
                    )
                self.db.merge_groups(target.id, [item.id for item in others])  # type: ignore[attr-defined]
                merged_clusters += 1
                merged_groups += len(others)
            sync_editorial_memory(self.db)  # type: ignore[attr-defined]
            return merged_clusters, merged_groups

        def success(result: object) -> None:
            merged_clusters, merged_groups = result  # type: ignore[misc]
            self.refresh_groups()  # type: ignore[attr-defined]
            self.topic_search_status_var.set(  # type: ignore[attr-defined]
                f"Об'єднано пропозицій: {merged_clusters}; приєднано блоків: {merged_groups}."
            )
            self.set_status("Глобальне об'єднання дублікатів завершено.")  # type: ignore[attr-defined]

        self.run_async(  # type: ignore[attr-defined]
            action,
            success,
            label=f"Об'єдную запропоновані блоки: {len(clusters)}",
            done_label="Об'єднання завершено",
        )
