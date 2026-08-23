from __future__ import annotations

from datetime import datetime
import logging
import threading
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from ..donation_settings_v1_3_1_rc8 import (
    DonationSettings,
    donation_settings_path,
    load_donation_settings,
    save_donation_settings,
    strip_known_donation_blocks,
    with_inline_donation,
)
from ..editorial_memory import rank_editorial_examples
from ..inbox_layout_v1_3_1_rc8 import inbox_layout_path, load_widths, save_widths
from ..models import NewsGroup, RewriteResult
from ..news_logic import calculate_explosiveness
from ..performance_prediction import predict_historical_performance
from ..publication_text import compose_publication_text as legacy_compose_publication_text
from ..publisher_factory_v1_3_1_rc8 import Rc8PublisherFactory
from ..rewrite_pipeline_v1_3 import (
    last_rewrite_diagnostic,
    last_rewrite_engine_label,
    rewrite_group_v13,
)
from ..rowboat_bridge_v1_3 import memory_context, sync_editorial_memory
from ..scheduling import KYIV
from ..worker_v1_2_rc4 import Rc4PublicationWorker
from ..rc8_topics import central_topic
from . import main_window as legacy_ui
from .source_health_v1_3 import SourceHealthV13Mixin
from .v1_2_2_rc1_window import MainWindow as StableV122Window


logger = logging.getLogger("content_agent.ui.rc8")


class MainWindow(SourceHealthV13Mixin, StableV122Window):
    """UA FREE Content Tool v1.3.1-rc8 stabilization layer."""

    VERSION_LABEL = "1.3.1-rc8"

    def __init__(self, *args: object, **kwargs: object) -> None:
        self._rewrite_attempt_serial = 0
        self._inbox_layout_save_after_id: str | None = None
        self._inbox_layout_path = inbox_layout_path()
        self._donation_settings_path = donation_settings_path()
        self._donation_settings = load_donation_settings(self._donation_settings_path)
        self.donation_vars: dict[str, tk.BooleanVar] = {}
        self.donation_checks: dict[str, ttk.Checkbutton] = {}
        super().__init__(*args, **kwargs)

        # The inherited RC8 target-preset layer installs the historical composer
        # after the base window is built. RC8 must win after the full MRO is done.
        legacy_ui.compose_publication_text = self._compose_publication_text_rc8

        self._install_rc8_inbox()
        self._install_donation_editor_ui()
        self._install_rc8_publication_runtime()
        self._update_donation_legacy_label()
        self._apply_v13_labels()
        self.refresh_groups()
        self.update_text_metrics()

    # ------------------------------------------------------------------
    # Version labels.
    # ------------------------------------------------------------------
    def _apply_v13_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v1.3.1-rc8")
        button = getattr(self, "rewrite_button", None)
        if button is not None:
            if getattr(self.config, "ui_language", "uk") == "en":
                button.configure(text="Rewrite via AI Router + Fact Guard")
            else:
                button.configure(text="Рерайт через AI Router + Fact Guard")

    def _apply_language(self, refresh: bool = True) -> None:
        super()._apply_language(refresh=refresh)
        self._apply_v13_labels()
        self._update_donation_legacy_label()
        if hasattr(self, "groups_tree") and "topic" in tuple(self.groups_tree.cget("columns")):
            self.groups_tree.heading("topic", text="Topic" if self.config.ui_language == "en" else "Тема")

    # ------------------------------------------------------------------
    # Inbox: compact default geometry + one central topic + persistence.
    # ------------------------------------------------------------------
    def _inbox_headings(self) -> dict[str, str]:
        labels = dict(super()._inbox_headings())
        tree = getattr(self, "groups_tree", None)
        if tree is not None and "topic" in tuple(tree.cget("columns")):
            labels["topic"] = "Topic" if self.config.ui_language == "en" else "Тема"
        return labels

    def _install_rc8_inbox(self) -> None:
        tree = getattr(self, "groups_tree", None)
        if tree is None:
            return
        columns = [str(item) for item in tuple(tree.cget("columns"))]
        if "topic" not in columns:
            tree.configure(columns=tuple([*columns, "topic"]))
        tree.heading("topic", text="Topic" if self.config.ui_language == "en" else "Тема")
        tree.configure(
            displaycolumns=("id", "status", "title", "topic", "sources", "published", "score", "history")
        )
        widths = load_widths(self._inbox_layout_path)
        for column, width in widths.items():
            if column in tuple(tree.cget("columns")):
                tree.column(
                    column,
                    width=width,
                    minwidth=38 if column != "title" else 260,
                    stretch=(column == "title"),
                    anchor="w",
                )
        tree.bind("<ButtonRelease-1>", self._schedule_inbox_layout_save, add="+")
        installer = getattr(self, "_install_tree_sorting", None)
        if callable(installer):
            installer(reset_labels=True)

    def _schedule_inbox_layout_save(self, _event: object | None = None) -> None:
        if self._inbox_layout_save_after_id is not None:
            try:
                self.root.after_cancel(self._inbox_layout_save_after_id)
            except tk.TclError:
                pass
        self._inbox_layout_save_after_id = self.root.after(350, self._save_inbox_layout)

    def _save_inbox_layout(self) -> None:
        self._inbox_layout_save_after_id = None
        tree = getattr(self, "groups_tree", None)
        if tree is None:
            return
        try:
            widths = {
                column: int(tree.column(column, "width"))
                for column in ("id", "status", "title", "topic", "sources", "published", "score", "history")
            }
            save_widths(widths, self._inbox_layout_path)
        except (OSError, tk.TclError, TypeError, ValueError):
            logger.debug("Could not persist RC8 Inbox layout.", exc_info=True)

    def refresh_groups(self) -> None:
        super().refresh_groups()
        tree = getattr(self, "groups_tree", None)
        if tree is None or "topic" not in tuple(tree.cget("columns")):
            return
        for item_id in tree.get_children(""):
            tree.set(item_id, "topic", central_topic(tree.set(item_id, "title")))
        reapply = getattr(self, "_reapply_tree_sort", None)
        if callable(reapply):
            reapply(tree)

    # ------------------------------------------------------------------
    # Donation block: editable once, enabled independently per target.
    # ------------------------------------------------------------------
    def _compose_publication_text_rc8(
        self,
        core_text: str,
        platform: str,
        *,
        include_source_link: bool,
        source_url: str,
    ) -> str:
        # Start from the established source-link formatting, then remove the
        # legacy mandatory footer. Facebook/Threads use a separate comment/reply;
        # LinkedIn/Telegram/Instagram keep the optional donation inline.
        legacy = legacy_compose_publication_text(
            core_text,
            platform,
            include_source_link=include_source_link,
            source_url=source_url,
        )
        clean = strip_known_donation_blocks(legacy)
        if platform in {"facebook", "threads"}:
            return clean
        target = platform
        enabled = self._donation_settings.enabled_for(target)
        return with_inline_donation(clean, self._donation_settings.text, enabled)

    def _update_donation_legacy_label(self) -> None:
        tab = getattr(self, "publication_tab", None)
        if tab is None:
            return
        for widget in self._walk_widgets(tab):
            if not isinstance(widget, ttk.Label):
                continue
            try:
                text = str(widget.cget("text"))
            except tk.TclError:
                continue
            if text.startswith("Абзац про збір UA FREE додається завжди"):
                widget.configure(text="Донатний блок вмикається окремо для кожного профілю.")

    @staticmethod
    def _walk_widgets(parent: tk.Misc):
        for child in parent.winfo_children():
            yield child
            yield from MainWindow._walk_widgets(child)

    def _install_donation_editor_ui(self) -> None:
        tab = getattr(self, "publication_tab", None)
        if tab is None:
            return
        self.donation_status_var = tk.StringVar()
        bar = ttk.Frame(tab)
        bar.grid(row=5, column=0, sticky="ew", pady=(2, 0))
        ttk.Button(bar, text="Редагувати донатний блок", command=self.open_donation_editor).pack(side="left")
        ttk.Label(bar, textvariable=self.donation_status_var, foreground="#555").pack(side="left", padx=(10, 0))
        self._refresh_donation_status()

    def _refresh_donation_status(self) -> None:
        variable = getattr(self, "donation_status_var", None)
        if variable is None:
            return
        enabled = [key for key in self._donation_settings.targets if key in getattr(self, "target_vars", {})]
        text_state = "текст порожній" if not self._donation_settings.text.strip() else "текст збережено"
        variable.set(f"{text_state} · увімкнено профілів: {len(enabled)}")

    def open_donation_editor(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("Донатний блок")
        window.transient(self.root)
        window.geometry("760x360")
        window.minsize(560, 280)
        frame = ttk.Frame(window, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame,
            text="Текст донатного блоку. Він не зашитий у програму й може змінюватися в будь-який момент.",
        ).pack(anchor="w", pady=(0, 6))
        editor = ScrolledText(frame, wrap="word", height=12)
        editor.pack(fill="both", expand=True)
        editor.insert("1.0", self._donation_settings.text)
        ttk.Label(
            frame,
            text="Для Threads один донатний reply має бути не довшим за 500 символів.",
            foreground="#666",
        ).pack(anchor="w", pady=(5, 0))
        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(10, 0))

        def save() -> None:
            text = editor.get("1.0", "end-1c").strip()
            if self._donation_settings.enabled_for("threads") and len(text) > 500:
                self.msg.showwarning(
                    "Донатний блок",
                    "Для Threads текст донатної відповіді має бути до 500 символів. Скоротіть текст або вимкніть донатний блок для Threads.",
                    parent=window,
                )
                return
            self._donation_settings = save_donation_settings(
                DonationSettings(text=text, targets=list(self._donation_settings.targets)),
                self._donation_settings_path,
            )
            factory = getattr(self, "publisher_factory", None)
            if isinstance(factory, Rc8PublisherFactory):
                factory.update_donation_settings(self._donation_settings)
            self._refresh_donation_status()
            self.update_text_metrics()
            self.set_status("Текст донатного блоку збережено.")
            window.destroy()

        ttk.Button(actions, text="Скасувати", command=window.destroy).pack(side="right")
        ttk.Button(actions, text="Зберегти", command=save).pack(side="right", padx=(0, 6))
        editor.focus_set()

    def _rebuild_target_controls(self) -> None:
        # This override is invoked during ancestor initialization, so the state is
        # prepared before super().__init__ runs.
        super()._rebuild_target_controls()
        if not hasattr(self, "targets_row"):
            return
        for check in list(getattr(self, "donation_checks", {}).values()):
            try:
                check.destroy()
            except tk.TclError:
                pass
        self.donation_vars = {}
        self.donation_checks = {}
        enabled_targets = set(self._donation_settings.targets)
        for platform in self.target_vars:
            variable = tk.BooleanVar(value=platform in enabled_targets)
            ready = self.config.platform_ready(platform)
            check = ttk.Checkbutton(
                self.targets_row,
                text="Донатний блок",
                variable=variable,
                state="normal" if ready else "disabled",
                command=lambda key=platform: self._donation_target_toggled(key),
            )
            self.donation_vars[platform] = variable
            self.donation_checks[platform] = check
        self._layout_target_controls()
        self._refresh_donation_status()

    def _layout_target_controls(self) -> None:
        columns = max(1, getattr(self, "target_column_count", 3))
        donations = getattr(self, "donation_checks", {})
        for index, platform in enumerate(getattr(self, "target_vars", {})):
            target_check = self.target_checks[platform]
            target_check.grid_forget()
            row = (index // columns) * 2
            column = index % columns
            target_check.grid(row=row, column=column, sticky="w", padx=(0, 18), pady=(2, 0))
            donation_check = donations.get(platform)
            if donation_check is not None:
                donation_check.grid_forget()
                donation_check.grid(row=row + 1, column=column, sticky="w", padx=(18, 18), pady=(0, 4))
        row_count = max(1, (len(getattr(self, "target_vars", {})) + columns - 1) // columns)
        for column in range(max(4, columns)):
            self.targets_row.columnconfigure(column, weight=1 if column < columns else 0)
        if hasattr(self, "targets_canvas"):
            self.targets_canvas.configure(height=min(210, max(90, row_count * 58)))

    def _donation_target_toggled(self, platform: str) -> None:
        variable = self.donation_vars.get(platform)
        if variable is None:
            return
        if platform == "threads" and variable.get() and len(self._donation_settings.text) > 500:
            variable.set(False)
            self.msg.showwarning(
                "Донатний блок",
                "Поточний донатний текст довший за 500 символів. Скоротіть його перед увімкненням для Threads.",
                parent=self.root,
            )
            return
        targets = [key for key, item in self.donation_vars.items() if item.get()]
        self._donation_settings = save_donation_settings(
            DonationSettings(text=self._donation_settings.text, targets=targets),
            self._donation_settings_path,
        )
        factory = getattr(self, "publisher_factory", None)
        if isinstance(factory, Rc8PublisherFactory):
            factory.update_donation_settings(self._donation_settings)
        self._refresh_donation_status()
        self.update_text_metrics()
        self.set_status(f"Донатний блок для {platform}: {'увімкнено' if variable.get() else 'вимкнено'}.")

    def _install_rc8_publication_runtime(self) -> None:
        self.publisher_factory = Rc8PublisherFactory(self.config, self._donation_settings)
        self.worker = Rc4PublicationWorker(
            self.db,
            self.publisher_factory,
            inter_target_delay_seconds=5.0,
            max_automatic_attempts=3,
            progress_callback=self._publication_progress_from_worker,
            result_callback=self._publication_result_from_worker,
            managed_media_registry=self.managed_media_registry,
            image_store=self.multi_image_store,
        )
        self.worker_thread = threading.Thread(
            target=self.worker.run_loop,
            args=(self.stop_event,),
            name="publication-worker",
            daemon=True,
        )

    def show_history_details(self) -> None:
        super().show_history_details()
        row = self._selected_history_row() if hasattr(self, "_selected_history_row") else None
        if not row or not hasattr(self, "history_details"):
            return
        targets = row.get("targets")
        donation_lines: list[str] = []
        for target in targets if isinstance(targets, list) else []:
            progress = target.get("progress") if isinstance(target, dict) and isinstance(target.get("progress"), dict) else {}
            status = str(progress.get("donation_status") or "").strip()
            if not status:
                continue
            labels = {
                "sent": "опубліковано",
                "inline": "у складі основного поста",
                "disabled": "вимкнено",
                "failed": "помилка після успішного основного поста",
                "not_attempted_after_reconcile": "не надсилався після звірки основного поста",
            }
            detail = labels.get(status, status)
            error = str(progress.get("donation_error") or "").strip()
            if error:
                detail += f" · {error}"
            donation_lines.append(f" • {target.get('platform')}: {detail}")
        if not donation_lines:
            return
        self.history_details.configure(state="normal")
        self.history_details.insert("end", "\n\nДОНАТНИЙ БЛОК:\n" + "\n".join(donation_lines))
        self.history_details.configure(state="disabled")

    # ------------------------------------------------------------------
    # Rewrite: never silently disappear.
    # ------------------------------------------------------------------
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
        cancel_event = threading.Event()
        self._rewrite_cancel_event = cancel_event
        self._rewrite_attempt_serial += 1
        attempt_id = self._rewrite_attempt_serial
        logger.info("RC8 rewrite attempt=%s group=%s started", attempt_id, group.id)

        def action() -> object:
            try:
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
                    cancel_event=cancel_event,
                )
                return result, len(examples)
            except Exception:
                logger.exception("RC8 rewrite attempt=%s group=%s failed", attempt_id, group.id)
                raise

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
                        "attempt_id": attempt_id,
                    },
                )
            self.refresh_groups()
            self.update_text_metrics()
            self.refresh_ai_component_status()
            logger.info(
                "RC8 rewrite attempt=%s group=%s success engine=%s diagnostic=%s",
                attempt_id,
                group.id,
                engine,
                diagnostic,
            )
            self.set_status(
                f"Рерайт #{attempt_id} створено · AI: {engine} · джерел {rewrite_result.source_count_used} із {rewrite_result.source_count_total}"
                f" · пам'ять {example_count} · {diagnostic}"
            )

        def timed_out(message: str) -> None:
            cancel_event.set()
            logger.error("RC8 rewrite attempt=%s group=%s timeout: %s", attempt_id, group.id, message)

        self.run_async(
            action,
            success,
            label=f"Рерайт #{attempt_id}: AI Router + Fact Guard · {group.source_count} джерел",
            done_label=f"AI-рерайт #{attempt_id} завершено",
            timeout_seconds=105,
            timeout_message=(
                f"Рерайт #{attempt_id} не завершився за 105 секунд. Поточний текст не змінено; "
                "фонові AI-виклики отримали команду завершення."
            ),
            on_timeout=timed_out,
            modal_errors=True,
            modal_timeout=True,
            timeout_is_error=True,
        )

    # ------------------------------------------------------------------
    # Potential: local editorial signal + own publication history.
    # Threads keyword-search zeros are no longer treated as data.
    # ------------------------------------------------------------------
    def analyze_current(self) -> None:
        if self.current_group_id is None:
            return
        group = self.db.get_group(self.current_group_id)
        now = datetime.now(KYIV)

        def action() -> object:
            score, confidence, details, recommendations = calculate_explosiveness(group, None)
            details = dict(details)
            details.pop("threads_posts", None)
            details.pop("threads_queries", None)
            details.pop("threads_error", None)
            details["live_threads_disabled"] = True
            prediction = predict_historical_performance(
                group,
                self.db.list_publication_history(limit=2000),
                now=now,
            )
            details["history_prediction"] = prediction.to_dict()
            return score, confidence, details, recommendations

        def success(result: object) -> None:
            score, confidence, details, recommendations = result  # type: ignore[misc]
            self.db.set_group_analysis(
                group.id,
                score=score,
                confidence=confidence,
                details=details,
                recommendations=recommendations,
            )
            updated = self.db.get_group(group.id)
            self._display_analysis(updated)
            self.apply_recommendations(updated.recommended_platforms)
            self.refresh_groups()
            self.operation_detail_var.set("Оцінка готова: локальний потенціал + власна історія публікацій.")

        self.run_async(
            action,
            success,
            label="Оцінка потенціалу: джерела + власна історія",
            done_label="Оцінку потенціалу завершено",
        )

    def _display_analysis(self, group: NewsGroup) -> None:
        details = group.explosiveness_details if isinstance(group.explosiveness_details, dict) else {}
        english = self.config.ui_language == "en"
        if not group.explosiveness_score and not details:
            self.analysis_var.set("Potential has not been evaluated" if english else "Потенціал не розраховано")
            self.analysis_detail_var.set("Click Evaluate potential." if english else "Натисніть «Оцінити потенціал».")
            return
        prediction = details.get("history_prediction")
        prediction_data = prediction if isinstance(prediction, dict) else {}
        recommended = ", ".join(group.recommended_platforms) or ("none" if english else "без автоматичної рекомендації")
        if bool(prediction_data.get("available")):
            history = (
                f"history {int(prediction_data.get('score') or 0)}/100 · confidence {int(prediction_data.get('confidence') or 0)}%"
                if english
                else f"історія {int(prediction_data.get('score') or 0)}/100 · довіра {int(prediction_data.get('confidence') or 0)}%"
            )
        else:
            history = "history: insufficient data" if english else "історія: недостатньо даних"
        if english:
            self.analysis_var.set(
                f"Current potential: {group.explosiveness_score}/100 · confidence: {group.explosiveness_confidence}% · "
                f"sources: {group.source_count} · {history} · recommended: {recommended}"
            )
            self.analysis_detail_var.set(
                "The live Threads keyword counter is excluded because an unavailable signal must not be displayed as zero. "
                "Current potential uses the story itself and source structure; the second score uses your own publication history."
            )
        else:
            self.analysis_var.set(
                f"Поточний потенціал: {group.explosiveness_score}/100 · надійність: {group.explosiveness_confidence}% · "
                f"джерел: {group.source_count} · {history} · рекомендовано: {recommended}"
            )
            note = str(prediction_data.get("note") or "").strip()
            self.analysis_detail_var.set(
                "Live-пошук Threads виключено з оцінки: відсутність доступних даних більше не показується як нуль. "
                "Поточний потенціал рахується за самим матеріалом і джерелами; окремий прогноз базується на власній історії."
                + (f"\n{note}" if note else "")
            )

    def close(self) -> None:
        self._save_inbox_layout()
        event = getattr(self, "_rewrite_cancel_event", None)
        if event is not None:
            try:
                event.set()
            except Exception:
                pass
        super().close()
