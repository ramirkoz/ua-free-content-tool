from __future__ import annotations

from ..codex_news_v1_3 import rewrite_group_with_codex
from ..editorial_memory import rank_editorial_examples
from ..global_duplicates_v1_3_rc6 import DuplicateCluster, find_global_duplicate_clusters
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
            # Every DB read, memory sync, retrieval pass and Codex startup lives
            # here, not in the Tk event handler. The click must return immediately.
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
            # The user may have opened another group while Codex was working.
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
            if config.learning_enabled:
                self.db.record_learning_event(  # type: ignore[attr-defined]
                    "rewrite_generated",
                    language=config.ui_language,
                    group_id=group.id,
                    payload={"model": "codex-chatgpt", "fallback": False, "examples": example_count},
                )
            self.refresh_groups()  # type: ignore[attr-defined]
            if getattr(self, "current_group_id", None) == group.id:
                self.update_text_metrics()  # type: ignore[attr-defined]
            self.set_status(  # type: ignore[attr-defined]
                f"Рерайт створено через Codex · джерел {rewrite_result.source_count_used} із {rewrite_result.source_count_total}"
                f" · прикладів пам'яті {example_count}"
            )

        self.run_async(  # type: ignore[attr-defined]
            action,
            success,
            label="Готую матеріали й запускаю Codex у фоні",
            done_label="Рерайт Codex завершено",
        )

    def find_all_by_topic(self) -> None:
        # RC6 intentionally ignores the current selection. One click analyses all
        # new editorial blocks, including blocks that already contain 2+ sources.
        self.topic_search_status_var.set("Готую глобальний аналіз усіх нових матеріалів…")  # type: ignore[attr-defined]
        language = self.config.ui_language  # type: ignore[attr-defined]
        learning_enabled = bool(self.config.learning_enabled)  # type: ignore[attr-defined]

        def action() -> object:
            sync_editorial_memory(self.db)  # type: ignore[attr-defined]
            groups = self.db.list_groups(status="new", limit=1000)  # type: ignore[attr-defined]
            if len(groups) < 2:
                return groups, []
            feedback = (
                self.db.list_topic_feedback(language=language)  # type: ignore[attr-defined]
                if learning_enabled
                else []
            )
            graph = memory_context(
                "правила об'єднання дублікатів новин одна подія не пов'язано",
                limit=16,
            )
            clusters = find_global_duplicate_clusters(groups, feedback=feedback, graph_memory=graph)
            return groups, clusters

        def success(result: object) -> None:
            groups, clusters = result  # type: ignore[misc]
            groups = list(groups)
            clusters = list(clusters)
            if len(groups) < 2:
                self.topic_search_status_var.set("Для глобального порівняння потрібно щонайменше 2 нові блоки.")  # type: ignore[attr-defined]
                return
            if not clusters:
                self.topic_search_status_var.set(  # type: ignore[attr-defined]
                    f"Codex порівняв {len(groups)} нових блоків. Дублікатів для об'єднання не запропоновано."
                )
                return
            self.topic_search_status_var.set(  # type: ignore[attr-defined]
                f"Codex порівняв {len(groups)} нових блоків і запропонував {len(clusters)} об'єднань."
            )
            by_id = {group.id: group for group in groups}
            GlobalDuplicatesDialog(
                self.root,  # type: ignore[attr-defined]
                clusters=clusters,
                groups=by_id,
                on_apply=lambda selected: self._merge_global_clusters_rc6(selected, by_id),
            )

        self.run_async(  # type: ignore[attr-defined]
            action,
            success,
            label="Codex: порівнюю всі нові матеріали між собою",
            done_label="Глобальний пошук дублікатів завершено",
        )

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
                # Preserve the richer existing block; on ties preserve the older ID.
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
