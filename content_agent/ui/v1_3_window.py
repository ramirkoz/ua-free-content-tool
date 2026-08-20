from __future__ import annotations

from ..editorial_memory import rank_editorial_examples
from ..models import RewriteResult
from ..rewrite_pipeline_v1_3 import (
    last_rewrite_diagnostic,
    last_rewrite_engine_label,
    rewrite_group_v13,
)
from ..rowboat_bridge_v1_3 import memory_context, sync_editorial_memory
from .queue_safety_v1_3_1_rc1 import QueueSafetyRC1Mixin
from .source_health_v1_3 import SourceHealthV13Mixin
from .v1_2_2_rc1_window import MainWindow as StableV122Window


class MainWindow(QueueSafetyRC1Mixin, SourceHealthV13Mixin, StableV122Window):
    """Content Tool 1.3.1 RC1 queue-safety hotfix on the live-accepted 1.3.0 behavior."""

    VERSION_LABEL = "1.3.1 RC1"

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._apply_v13_labels()

    def _apply_v13_labels(self) -> None:
        self.root.title(
            "UA FREE Content Tool — v1.3.1 RC1 · Queue Safety Hotfix"
        )
        button = getattr(self, "rewrite_button", None)
        if button is not None:
            if getattr(self.config, "ui_language", "uk") == "en":
                button.configure(text="Rewrite via AI Router + Fact Guard")
            else:
                button.configure(text="Рерайт через AI Router + Fact Guard")

    def _apply_language(self, refresh: bool = True) -> None:
        super()._apply_language(refresh=refresh)
        self._apply_v13_labels()

    def rewrite_current(self) -> None:
        if self.current_group_id is None:
            self.msg.showinfo("Редактор", "Спочатку прийміть блок у роботу.", parent=self.root)
            return

        self.db.set_group_options(
            self.current_group_id,
            include_source_link=self.include_source_var.get(),
        )
        group = self.db.get_group(self.current_group_id)
        config = self.config

        def action() -> object:
            sync_editorial_memory(self.db)
            examples = rank_editorial_examples(
                group.combined_text,
                self.db.list_editorial_examples(language=config.ui_language),
                limit=config.learning_examples_limit if config.learning_enabled else 0,
            )
            graph = memory_context(group.combined_text, limit=6)
            result = rewrite_group_v13(
                group,
                examples,
                graph_memory=graph,
                language=config.ui_language,
            )
            return result, len(examples)

        def success(result: object) -> None:
            rewrite_result, example_count = result  # type: ignore[misc]
            assert isinstance(rewrite_result, RewriteResult)
            self.same_text_var.set(True)
            self.headline_var.set(rewrite_result.headline)
            self._set_text(self.fact_card_text, rewrite_result.fact_card)
            self._set_text(self.text_widgets["rewrite"], rewrite_result.rewrite)
            self.db.set_group_ai_draft(group.id, rewrite_result.rewrite)
            self.db.save_group_rewrite(
                group.id,
                headline=rewrite_result.headline,
                fact_card=rewrite_result.fact_card,
                rewrite_text=rewrite_result.rewrite,
                platform_texts=rewrite_result.platform_texts,
            )
            engine = last_rewrite_engine_label() or "AI Router"
            diagnostic = last_rewrite_diagnostic()
            if config.learning_enabled:
                self.db.record_learning_event(
                    "rewrite_generated",
                    language=config.ui_language,
                    group_id=group.id,
                    payload={
                        "model": engine,
                        "pipeline": "v1.3-evidence-fact-guard",
                        "examples": example_count,
                        "diagnostic": diagnostic,
                    },
                )
            self.refresh_groups()
            self.update_text_metrics()
            self.refresh_ai_component_status()
            self.set_status(
                f"Рерайт створено · AI: {engine} · джерел {rewrite_result.source_count_used} із {rewrite_result.source_count_total}"
                f" · пам'ять {example_count} · {diagnostic}"
            )

        self.run_async(
            action,
            success,
            label=f"AI Router + Fact Guard: рерайт {group.source_count} джерел",
            done_label="AI-рерайт 1.3 завершено",
            timeout_seconds=180,
            timeout_message="Рерайт 1.3 не завершився за 180 секунд. Поточний текст не змінено.",
        )
