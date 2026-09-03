from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

from ..destinations_v1_4 import make_display_title
from ..google_drive import GoogleDriveError
from ..publication_text import TextLimitError, validate_editorial_text, validate_media_message
from ..worker_v1_4_rc10 import Rc10PublicationWorker
from . import main_window as legacy_ui
from .v1_4_rc9_window import MainWindow as Rc9MainWindow


class MainWindow(Rc9MainWindow):
    """v1.4.0-rc10: explicit publish-now path isolated from the schedule queue."""

    VERSION_LABEL = "1.4.0-rc10"

    def __init__(self, root: tk.Tk, database, config) -> None:
        super().__init__(root, database, config)

        # v1.4 builds the worker only after the inherited window exists. RC10
        # swaps the not-yet-started worker for one that can prioritize explicit
        # publish-now batches without changing the normal destination scheduler.
        self.worker = Rc10PublicationWorker(
            self.db,
            self.publisher_factory,
            inter_target_delay_seconds=5.0,
            progress_callback=self._publication_progress_from_worker,
            result_callback=self._publication_result_from_worker,
            managed_media_registry=self.managed_media_registry,
            image_store=self.multi_image_store,
        )
        self.worker_thread = threading.Thread(
            target=self.worker.run_loop,
            args=(self.stop_event,),
            name="publication-worker-v14-rc10",
            daemon=True,
        )
        self.publish_now_button: ttk.Button | None = None
        self._install_publish_now_button()
        self._apply_v14_labels()

    def _apply_v14_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v1.4.0-rc10")

    # ------------------------------------------------------------------
    # UI installation.
    # ------------------------------------------------------------------
    @staticmethod
    def _walk(parent: tk.Misc):
        for child in parent.winfo_children():
            yield child
            yield from MainWindow._walk(child)

    def _install_publish_now_button(self) -> None:
        tab = getattr(self, "publication_tab", None)
        if tab is None:
            return
        approve: ttk.Button | None = None
        for widget in self._walk(tab):
            if not isinstance(widget, ttk.Button):
                continue
            try:
                text = str(widget.cget("text")).upper()
            except tk.TclError:
                continue
            if "СХВАЛИТИ" in text and "ЧЕРГ" in text:
                approve = widget
                break
        if approve is None:
            return

        parent = approve.master
        button = ttk.Button(parent, text="ОПУБЛІКУВАТИ ЗАРАЗ", command=self.publish_now_current)
        manager = approve.winfo_manager()
        if manager == "pack":
            button.pack(side="right", padx=(0, 8), before=approve)
        elif manager == "grid":
            info = approve.grid_info()
            row = int(info.get("row", 0))
            column = int(info.get("column", 0))
            approve.grid_configure(column=column + 1)
            button.grid(row=row, column=column, sticky="e", padx=(0, 8), pady=info.get("pady", 0))
        else:
            button.pack(side="right", padx=(0, 8))
        self.publish_now_button = button

    # ------------------------------------------------------------------
    # Immediate publication.
    # ------------------------------------------------------------------
    def _prepare_publish_now(self):
        if self.current_group_id is None:
            self.msg.showwarning("Публікація", "Спочатку відкрийте матеріал у редакторі.", parent=self.root)
            return None
        if not self.save_current():
            return None

        selected = [key for key, variable in self.target_vars.items() if variable.get()]
        if not selected:
            self.msg.showwarning("Публікація", "Оберіть хоча б один профіль, сторінку або канал.", parent=self.root)
            return None
        if hasattr(self, "_remember_last_target_selection"):
            try:
                self._remember_last_target_selection(selected)
            except Exception:
                pass

        group = self.db.get_group(self.current_group_id)
        headline, _fact_card, rewrite, _platform_texts = self._editor_values()
        targets: dict[str, str] = {}
        try:
            validate_editorial_text(rewrite)
            for target in selected:
                logical = (
                    "facebook" if target.startswith("facebook:")
                    else "instagram" if target.startswith("instagram:")
                    else target
                )
                final = legacy_ui.compose_publication_text(
                    rewrite,
                    logical,
                    include_source_link=group.include_source_link,
                    source_url=group.primary_url,
                )
                validate_media_message(final, logical, has_media=bool(group.media_file_id))
                targets[target] = final
        except (TextLimitError, ValueError) as exc:
            self._show_error(exc)
            return None

        if group.media_file_id and not self.config.platform_ready("google_drive"):
            self._show_error(GoogleDriveError("Google Drive не підключено, медіа неможливо завантажити."))
            return None

        return group, headline, rewrite, targets, make_display_title(headline, rewrite)

    def publish_now_current(self) -> None:
        prepared = self._prepare_publish_now()
        if prepared is None:
            return
        group, headline, rewrite, targets, display_title = prepared
        labels = self._destination_labels()
        target_names = [labels.get(key, key) for key in targets]
        preview = "\n".join(f"• {name}" for name in target_names[:12])
        if len(target_names) > 12:
            preview += f"\n• …і ще {len(target_names) - 12}"
        if not self.msg.askyesno(
            "Опублікувати зараз",
            "Опублікувати матеріал ЗАРАЗ без постановки у звичайну чергу?\n\n"
            + preview
            + "\n\nПоточні слоти й порядок черги не зміняться.",
            parent=self.root,
        ):
            return

        try:
            result = self.db.create_immediate_targets(
                self.db.lead_article_id(group.id),
                targets,
                display_title=display_title,
            )
        except Exception as exc:
            self._show_error(exc)
            return

        if result.created:
            learned = self.db.record_editorial_example(
                group.id,
                final_text=rewrite,
                headline=headline,
                language=self.config.ui_language,
            )
            if self.config.learning_enabled:
                self.db.record_learning_event(
                    "publication_now_requested",
                    language=self.config.ui_language,
                    group_id=group.id,
                    payload={
                        "batch_ids": result.batch_ids,
                        "targets": sorted(result.created),
                        "requested_at": result.requested_at,
                        "example_added": learned,
                        "display_title": display_title,
                    },
                )
            self.worker.wake()

        self.refresh_groups()
        self.refresh_queue()

        lines: list[str] = []
        if result.created:
            lines.append("Публікація запущена негайно:")
            lines.extend(f"• {labels.get(key, key)}" for key in result.created)
        if result.blocked_active:
            lines.append("\nНе дублюю: цей матеріал уже стоїть у черзі для:")
            lines.extend(f"• {labels.get(key, key)}" for key in result.blocked_active)
        if result.already_final:
            lines.append("\nНе дублюю: для цих профілів матеріал уже має результат у історії:")
            lines.extend(f"• {labels.get(key, key)}" for key in result.already_final)
        if not lines:
            lines.append("Нових публікацій не створено.")

        if result.created:
            self.set_status(
                f"Опублікувати зараз: запущено профілів {len(result.created)}. Звичайна черга не змінена."
            )
        self.msg.showinfo("Опублікувати зараз", "\n".join(lines), parent=self.root)

    def _publication_result_from_worker(self, result) -> None:
        # Correct the artificial priority timestamp before History reads the row.
        if result.batch_id is not None:
            try:
                self.db.finalize_immediate_timestamp(int(result.batch_id))
            except Exception:
                pass
        super()._publication_result_from_worker(result)
