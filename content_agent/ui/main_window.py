from __future__ import annotations

import threading
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime, timedelta
import webbrowser
from dataclasses import asdict
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Callable

from ..backup import create_backup, import_backup
from ..collectors import collect_source
from ..config import AppConfig, ConfigError, load_config, save_config
from ..connection_diagnostics import (
    STATUS_ATTENTION,
    STATUS_NOT_CONFIGURED,
    STATUS_OK,
    STATUS_REPLACE,
    STATUS_TEMPORARY,
    ConnectionDiagnostic,
    ConnectionDiagnosticsReport,
    diagnose_connections,
)
from ..database import Database
from ..editorial_memory import rank_editorial_examples, rank_topic_candidates
from ..i18n import (
    LANGUAGE_LABELS,
    language_from_label,
    language_label,
    LocalizedFileDialog,
    LocalizedMessageBox,
    localize_widget_tree,
    normalize_language,
    original_text,
    tr,
)
from ..google_drive import (
    GoogleDriveClient,
    GoogleDriveError,
    authorize_google_drive,
    extract_drive_file_id,
)
from ..models import Article, NewsGroup, RewriteResult
from ..news_logic import calculate_explosiveness, extract_trend_queries
from ..ollama_client import OllamaClient, OllamaError
from ..paths import data_dir, portable_mode
from ..platform_setup import (
    MetaPage,
    PlatformSetupError,
    exchange_facebook_long_lived_token,
    exchange_threads_long_lived_token,
    refresh_threads_long_lived_token,
    inspect_linkedin_token,
    inspect_telegram_bot,
    inspect_threads_token,
    load_meta_pages,
)
from ..queue_migration import QUEUE_900_MIGRATION_KEY, scan_queue_for_900_migration
from ..publication_text import (
    EDITORIAL_TEXT_LIMIT,
    TELEGRAM_MEDIA_CAPTION_LIMIT,
    TextLimitError,
    compose_publication_text,
    metrics_for,
    validate_editorial_text,
    validate_media_message,
)
from ..publishers import PublisherFactory
from ..publication_metrics import collect_publication_metrics
from ..rewriter import platform_texts_from_base, rewrite_article_with_fallback
from ..scheduling import KYIV, next_publish_slot, parse_iso
from ..topic_search import build_topic_prompt, merge_local_and_ollama, parse_topic_matches
from ..trends import ThreadsTrendSample, check_threads_keyword_access, threads_keyword_sample
from ..worker import PublicationWorker, WorkerResult
from .editing import install_edit_support
from .exclusions_dialog import ContentExclusionsDialog
from .queue_migration_dialog import QueueMigrationDialog
from .topic_candidates_dialog import TopicCandidatesDialog


AUTO_COLLECT_INTERVAL_MS = 5 * 60 * 1000
TOKEN_DIAGNOSTIC_INTERVAL_MS = 6 * 60 * 60 * 1000

DIAGNOSTIC_STATUS_LABELS = {
    STATUS_OK: "актуальний",
    STATUS_REPLACE: "замінити токен",
    STATUS_ATTENTION: "перевірити права",
    STATUS_TEMPORARY: "тимчасово не перевірено",
    STATUS_NOT_CONFIGURED: "не налаштовано",
}

GROUP_FILTERS: dict[str, str | None] = {
    "Активні": None,
    "Нові": "new",
    "Схвалені": "approved",
    "Відхилені": "rejected",
    "Архів": "archived",
}
GROUP_STATUS_LABELS = {
    "new": "нова",
    "draft": "",
    "approved": "схвалено",
    "rejected": "відхилено",
    "archived": "архів",
}
QUEUE_FILTERS: dict[str, set[str] | None] = {
    "Активні": {"pending", "in_progress", "paused"},
    "Призупинені": {"paused"},
    "Усі": None,
    "Завершені": {"completed"},
    "Скасовані": {"cancelled"},
}
BATCH_STATUS_LABELS = {
    "pending": "очікує",
    "in_progress": "публікується",
    "paused": "призупинено",
    "completed": "завершено",
    "cancelled": "скасовано",
}
TARGET_STATUS_LABELS = {
    "pending": "очікує",
    "sent": "опубліковано",
    "failed": "помилка",
}


def _format_kyiv_schedule(value: str) -> tuple[str, datetime | None]:
    parsed = parse_iso(value)
    if parsed is None:
        return value, None
    local = parsed.astimezone(KYIV)
    return local.strftime("%d.%m.%Y %H:%M"), local


def _expiry_from_seconds(seconds: int) -> str:
    if int(seconds or 0) <= 0:
        return ""
    return (datetime.now(KYIV) + timedelta(seconds=int(seconds))).isoformat(timespec="seconds")


def _expiry_label(value: str) -> str:
    parsed = parse_iso(value)
    if parsed is None:
        return "строк дії не визначено"
    local = parsed.astimezone(KYIV)
    return "чинний до " + local.strftime("%d.%m.%Y %H:%M за Києвом")


def _format_overdue(delta: timedelta) -> str:
    total_minutes = max(0, int(delta.total_seconds() // 60))
    days, remaining = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(remaining, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days} дн")
    if hours:
        parts.append(f"{hours} год")
    if minutes or not parts:
        parts.append(f"{minutes} хв")
    return " ".join(parts)


def facebook_target_key(page_id: str) -> str:
    return f"facebook:{str(page_id).strip()}"


def configured_facebook_pages(config: AppConfig) -> list[dict[str, str]]:
    pages: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in config.facebook_pages:
        if not isinstance(row, dict):
            continue
        page_id = str(row.get("id", "")).strip()
        token = str(row.get("access_token", "")).strip()
        if not page_id or not token or page_id in seen:
            continue
        seen.add(page_id)
        pages.append(
            {
                "id": page_id,
                "name": str(row.get("name", "") or page_id),
                "access_token": token,
            }
        )
    return pages


def target_labels(config: AppConfig) -> dict[str, str]:
    labels = {
        "telegram": f"{config.telegram_chat_id or 'Telegram'} (Telegram)",
        "threads": f"{config.threads_profile_name or 'Threads'} (Threads)",
        "linkedin": f"{config.linkedin_profile_name or 'LinkedIn'} (LinkedIn)",
    }
    for page in configured_facebook_pages(config):
        labels[facebook_target_key(page["id"])] = f"{page['name']} (Facebook)"
    # Старі ключі лишаються тільки для вже створених пакетів у черзі.
    labels.setdefault("facebook:1", f"{config.facebook_page_1_name or 'Facebook Page 1'} (Facebook)")
    labels.setdefault("facebook:2", f"{config.facebook_page_2_name or 'Facebook Page 2'} (Facebook)")
    return labels


def publication_target_keys(config: AppConfig) -> list[str]:
    return [
        "telegram",
        *(facebook_target_key(page["id"]) for page in configured_facebook_pages(config)),
        "threads",
        "linkedin",
    ]


class MainWindow:
    def __getattr__(self, name: str):
        # Older regression tests construct MainWindow with __new__ and do not
        # run __init__. Fall back to the module dialogs in that narrow case.
        if name == 'msg':
            return messagebox
        if name == 'files':
            return filedialog
        raise AttributeError(name)

    def __init__(self, root: tk.Tk, database: Database, config: AppConfig):
        self.root = root
        self.db = database
        self.config = config
        self.msg = LocalizedMessageBox(lambda: self.config.ui_language)
        self.files = LocalizedFileDialog(lambda: self.config.ui_language)
        self._settings_loading = True
        self.settings_dirty = False
        self.current_group_id: int | None = None
        self._groups_selection_anchor: str | None = None
        self._queue_selection_anchor: str | None = None
        self.current_group_articles: list[Article] = []
        self.auto_collect_after_id: str | None = None
        self.queue_refresh_after_id: str | None = None
        self.connection_diagnostics_after_id: str | None = None
        self.connection_diagnostics_running = False
        self.threads_token_maintenance_after_id: str | None = None
        self.last_connection_warning_signature: tuple[tuple[str, str, str], ...] = ()
        self.ollama_prewarm_model = ""
        self.ollama_prewarm_event: threading.Event | None = None
        self.ollama_prewarm_serial = 0
        self.auto_collect_running = False
        self.stop_event = threading.Event()
        self.background_services_started = False
        self.queue_migration_dialog: QueueMigrationDialog | None = None
        self.publisher_factory = PublisherFactory(config)
        self.worker = PublicationWorker(
            database,
            self.publisher_factory,
            inter_target_delay_seconds=5.0,
            max_automatic_attempts=3,
            progress_callback=self._publication_progress_from_worker,
            result_callback=self._publication_result_from_worker,
        )
        self.worker_thread = threading.Thread(
            target=self.worker.run_loop,
            args=(self.stop_event,),
            name="publication-worker",
            daemon=True,
        )

        root.title("UA FREE Content Tool — v1.1.1")
        self._apply_ui_font_size(config.ui_font_size)
        root.geometry("1440x920")
        root.minsize(900, 650)
        install_edit_support(root)

        self.status_var = tk.StringVar(value="Готово")
        self.operation_var = tk.StringVar(value="Поточна операція: немає")
        self.operation_detail_var = tk.StringVar(value="Програма готова до роботи")
        self.operation_running = False
        self.background_publication_active = False
        self.operation_started_at: datetime | None = None
        self.operation_tick_after_id: str | None = None
        self.operation_timeout_after_id: str | None = None
        self.operation_serial = 0
        self.active_operation_id: int | None = None
        self.operation_buttons: list[ttk.Button] = []

        activity = ttk.Frame(root, padding=(10, 7))
        activity.pack(fill="x")
        activity.columnconfigure(0, weight=1)
        ttk.Label(activity, textvariable=self.operation_var, font="TkHeadingFont").grid(row=0, column=0, sticky="w")
        self.operation_progress = ttk.Progressbar(activity, mode="indeterminate", length=220)
        self.operation_progress.grid(row=0, column=1, sticky="e", padx=(12, 0))
        ttk.Label(activity, textvariable=self.operation_detail_var, foreground="#555").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(2, 0)
        )

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=(0, 2))

        self._build_sources_tab()
        self._build_inbox_tab()
        self._build_editor_tab()
        self._build_queue_tab()
        self._build_history_tab()
        self._build_settings_tab()
        self._apply_language(refresh=False)

        ttk.Label(root, textvariable=self.status_var, anchor="w").pack(fill="x", padx=10, pady=(2, 8))
        self.db.archive_stale_groups()
        self.refresh_sources()
        self.refresh_groups()
        self.refresh_queue()
        self.refresh_history()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        # FIX28 fails closed: the publication worker is not started until the
        # one-time 900-character migration has either completed or proved unnecessary.
        self.root.after(250, self._startup_queue_migration_gate)

    def _start_background_services(self) -> None:
        if self.background_services_started or self.stop_event.is_set():
            return
        self.background_services_started = True
        self.worker_thread.start()
        self._schedule_queue_refresh()
        self.root.after(900, self._auto_collect)
        self.root.after(2200, lambda: self.run_connection_diagnostics(automatic=True))
        self.threads_token_maintenance_after_id = self.root.after(4200, self._maybe_refresh_threads_token_async)
        self.set_status("Готово. Планувальник публікацій увімкнено.")

    def _startup_queue_migration_gate(self) -> None:
        if self.stop_event.is_set():
            return
        try:
            if self.db.queue_text_migration_completed(QUEUE_900_MIGRATION_KEY):
                self._start_background_services()
                return
            scan = scan_queue_for_900_migration(self.db)
        except Exception as exc:
            self.status_var.set("Публікацію не запущено: не вдалося перевірити чергу.")
            self.msg.showerror(
                "Перевірка черги не завершена",
                f"Планувальник залишився вимкненим. Помилка: {exc}",
                parent=self.root,
            )
            return
        if scan.blockers:
            self.status_var.set("Публікацію не запущено: у черзі є активний або прострочений пакет.")
            self.msg.showerror(
                "Спочатку завершіть чинну публікацію",
                "FIX28 не змінює чергу, поки пакет публікується або вже прострочений.\n\n"
                + "\n".join(f"• {item}" for item in scan.blockers)
                + "\n\nЗакрийте FIX28 без змін. У робочій FIX26 дочекайтеся завершення останнього пакета, "
                  "зробіть повну копію папки й лише тоді запускайте оновлену копію.",
                parent=self.root,
            )
            return
        if not scan.candidates:
            self.db.record_empty_queue_text_migration(QUEUE_900_MIGRATION_KEY)
            self._start_background_services()
            return
        self.status_var.set(
            f"Публікацію призупинено: {len(scan.candidates)} майбутніх пакетів потребують разового скорочення."
        )
        self.queue_migration_dialog = QueueMigrationDialog(
            self.root,
            self.db,
            self.config,
            scan.candidates,
            on_complete=self._queue_migration_completed,
            on_abort=self._queue_migration_aborted,
        )

    def _queue_migration_completed(self) -> None:
        self.queue_migration_dialog = None
        self.refresh_groups()
        self.refresh_queue()
        self._start_background_services()

    def _queue_migration_aborted(self) -> None:
        self.queue_migration_dialog = None
        self.settings_dirty = False
        self.stop_event.set()
        self.root.destroy()

    def close(self) -> None:
        if self.settings_dirty:
            answer = self.msg.askyesnocancel(
                "Незбережені налаштування",
                "У налаштуваннях є незбережені зміни. Зберегти їх перед закриттям?",
                parent=self.root,
            )
            if answer is None:
                return
            if answer and not self.save_settings(show_confirmation=False):
                return
        self.stop_event.set()
        if self.background_services_started:
            self.worker.wake()
        if self.auto_collect_after_id is not None:
            try:
                self.root.after_cancel(self.auto_collect_after_id)
            except tk.TclError:
                pass
            self.auto_collect_after_id = None
        if self.queue_refresh_after_id is not None:
            try:
                self.root.after_cancel(self.queue_refresh_after_id)
            except tk.TclError:
                pass
            self.queue_refresh_after_id = None
        if self.connection_diagnostics_after_id is not None:
            try:
                self.root.after_cancel(self.connection_diagnostics_after_id)
            except tk.TclError:
                pass
            self.connection_diagnostics_after_id = None
        if self.threads_token_maintenance_after_id is not None:
            try:
                self.root.after_cancel(self.threads_token_maintenance_after_id)
            except tk.TclError:
                pass
            self.threads_token_maintenance_after_id = None
        if self.operation_tick_after_id is not None:
            try:
                self.root.after_cancel(self.operation_tick_after_id)
            except tk.TclError:
                pass
            self.operation_tick_after_id = None
        self.root.destroy()

    def set_status(self, text: str) -> None:
        self.status_var.set(self.t(text))

    def _publication_progress_from_worker(self, text: str) -> None:
        """Show background publication progress without touching Tk off-thread."""
        def apply() -> None:
            display = str(text)
            for key, label in sorted(target_labels(self.config).items(), key=lambda item: len(item[0]), reverse=True):
                display = display.replace(key, label)
            self.status_var.set(display)
            self.operation_detail_var.set(display)
            if not self.operation_running:
                self.background_publication_active = True
                self.operation_var.set("Поточна операція: фонове публікування")
                self.operation_progress.start(12)

        try:
            self.root.after(0, apply)
        except tk.TclError:
            pass

    def _publication_result_from_worker(self, result: WorkerResult) -> None:
        """Refresh queue and show a persistent non-modal background result."""
        def apply() -> None:
            self.refresh_queue()
            self.refresh_history()
            if self.background_publication_active and not self.operation_running:
                self.background_publication_active = False
                self.operation_progress.stop()
                self.operation_var.set(
                    "Поточна операція: помилка" if result.failed_platforms else "Поточна операція: завершено"
                )
            labels = target_labels(self.config)
            if result.failed_platforms:
                failed = ", ".join(labels.get(key, key) for key in result.failed_platforms)
                state = (
                    f"Пакет #{result.batch_id}: не опубліковано {failed}. "
                    + (
                        "Пакет призупинено; відкрийте вкладку «Черга», оновіть токени й переплануйте призупинені пакети."
                        if result.paused
                        else "Невідправлені цілі лишилися в черзі для контрольованої спроби."
                    )
                )
                self.status_var.set(state)
                self.operation_detail_var.set(state)
                if hasattr(self, "queue_alert_var"):
                    self.queue_alert_var.set(state)
            elif result.sent_platforms:
                sent = ", ".join(labels.get(key, key) for key in result.sent_platforms)
                state = f"Пакет #{result.batch_id}: опубліковано {sent}."
                self.status_var.set(state)
                self.operation_detail_var.set(state)
                if hasattr(self, "queue_alert_var"):
                    self.queue_alert_var.set(state)

        try:
            self.root.after(0, apply)
        except tk.TclError:
            pass

    def _apply_ui_font_size(self, size: int) -> None:
        value = max(9, min(24, int(size)))
        for name in (
            "TkDefaultFont",
            "TkTextFont",
            "TkMenuFont",
            "TkCaptionFont",
            "TkSmallCaptionFont",
            "TkIconFont",
            "TkTooltipFont",
            "TkFixedFont",
        ):
            try:
                tkfont.nametofont(name).configure(size=value)
            except tk.TclError:
                pass
        try:
            heading = tkfont.nametofont("TkHeadingFont")
            heading.configure(size=value + 1, weight="bold")
        except tk.TclError:
            pass
        style = ttk.Style(self.root)
        style.configure("Treeview", rowheight=max(26, int(value * 2.25)))
        style.configure("TNotebook.Tab", padding=(10, max(5, value // 2)))
        self.config.ui_font_size = value

    def preview_font_size(self, *_args: object) -> None:
        try:
            value = int(self.ui_font_size_var.get())
        except (AttributeError, ValueError):
            return
        self._apply_ui_font_size(value)
        self._mark_settings_dirty()

    def change_font_size(self, delta: int) -> None:
        current = int(self.ui_font_size_var.get()) if hasattr(self, "ui_font_size_var") else self.config.ui_font_size
        self.ui_font_size_var.set(str(max(9, min(24, current + delta))))
        self.preview_font_size()

    def _mark_settings_dirty(self, *_args: object) -> None:
        if self._settings_loading:
            return
        self.settings_dirty = True
        if hasattr(self, "settings_dirty_var"):
            self.settings_dirty_var.set("Є незбережені зміни")
        if hasattr(self, "settings_save_button"):
            self.settings_save_button.configure(state="normal")

    def _mark_settings_saved(self, text: str = "Усі зміни збережено") -> None:
        self.settings_dirty = False
        if hasattr(self, "settings_dirty_var"):
            self.settings_dirty_var.set(text)
        if hasattr(self, "settings_save_button"):
            self.settings_save_button.configure(state="disabled")

    def _install_settings_change_tracking(self) -> None:
        variables: list[tk.Variable] = [
            *self.settings_vars.values(),
            self.ollama_model_var,
            self.ollama_fallback_var,
            self.threads_trend_var,
            self.publish_start_var,
            self.publish_end_var,
            self.publish_interval_var,
            self.ui_font_size_var,
            self.ui_language_var,
            self.learning_enabled_var,
            self.learning_examples_limit_var,
        ]
        for variable in variables:
            variable.trace_add("write", self._mark_settings_dirty)
        self._settings_loading = False
        self._mark_settings_saved()

    def _persist_connected_config(self, message: str) -> None:
        if not self.save_settings(show_confirmation=False):
            return
        self._mark_settings_saved(message)
        self.set_status(message)

    def _operation_tick(self) -> None:
        self.operation_tick_after_id = None
        if not self.operation_running or self.operation_started_at is None:
            return
        elapsed = max(0, int((datetime.now() - self.operation_started_at).total_seconds()))
        minutes, seconds = divmod(elapsed, 60)
        self.operation_detail_var.set(self.t(f"Виконується {minutes:02d}:{seconds:02d}. Не закривайте програму."))
        self.operation_tick_after_id = self.root.after(1000, self._operation_tick)

    def _start_operation(self, label: str) -> int | None:
        label = self.t(label)
        if self.operation_running:
            self.msg.showinfo(
                "Операція вже виконується",
                f"Зараз триває: {self.operation_var.get().removeprefix('Поточна операція: ')}",
                parent=self.root,
            )
            return None
        self.operation_serial += 1
        operation_id = self.operation_serial
        self.active_operation_id = operation_id
        self.operation_running = True
        self.operation_started_at = datetime.now()
        self.operation_var.set(self.t(f"Поточна операція: {label}"))
        self.operation_detail_var.set(self.t("Запущено…"))
        self.operation_progress.start(12)
        for button in self.operation_buttons:
            button.configure(state="disabled")
        self._operation_tick()
        return operation_id

    def _finish_operation(self, detail: str, *, error: bool = False) -> None:
        self.operation_running = False
        self.active_operation_id = None
        self.operation_progress.stop()
        if self.operation_tick_after_id is not None:
            try:
                self.root.after_cancel(self.operation_tick_after_id)
            except tk.TclError:
                pass
            self.operation_tick_after_id = None
        if self.operation_timeout_after_id is not None:
            try:
                self.root.after_cancel(self.operation_timeout_after_id)
            except tk.TclError:
                pass
            self.operation_timeout_after_id = None
        self.operation_var.set(self.t("Поточна операція: помилка" if error else "Поточна операція: завершено"))
        self.operation_detail_var.set(self.t(detail))
        for button in self.operation_buttons:
            button.configure(state="normal")

    def _operation_is_active(self, operation_id: int) -> bool:
        return self.operation_running and self.active_operation_id == operation_id

    def _async_error_for_operation(self, operation_id: int, error: Exception) -> None:
        if not self._operation_is_active(operation_id):
            return
        self._show_error(error)

    def _async_success_for_operation(
        self,
        operation_id: int,
        result: object,
        success: Callable[[object], None] | None,
        done_label: str,
    ) -> None:
        if not self._operation_is_active(operation_id):
            return
        self._async_success(result, success, done_label)

    def _operation_timeout(
        self,
        operation_id: int,
        timeout_message: str,
        on_timeout: Callable[[str], None] | None,
    ) -> None:
        if not self._operation_is_active(operation_id):
            return
        self.operation_timeout_after_id = None
        if on_timeout is not None:
            try:
                on_timeout(timeout_message)
            except Exception:
                pass
        self.set_status("Помилка")
        self._finish_operation(timeout_message, error=True)
        self.msg.showerror("UA FREE Content Tool", timeout_message, parent=self.root)

    def run_async(
        self,
        action: Callable[[], object],
        success: Callable[[object], None] | None = None,
        *,
        label: str = "Виконання операції",
        done_label: str = "Операцію завершено",
        timeout_seconds: float | None = None,
        timeout_message: str = "Операція не завершилася в установлений час.",
        on_timeout: Callable[[str], None] | None = None,
    ) -> None:
        operation_id = self._start_operation(label)
        if operation_id is None:
            return
        self.set_status(label)
        if timeout_seconds is not None:
            milliseconds = max(1, int(timeout_seconds * 1000))
            self.operation_timeout_after_id = self.root.after(
                milliseconds,
                lambda: self._operation_timeout(operation_id, timeout_message, on_timeout),
            )

        def runner() -> None:
            try:
                result = action()
            except Exception as exc:
                self.root.after(0, lambda error=exc: self._async_error_for_operation(operation_id, error))
                return
            self.root.after(
                0,
                lambda value=result: self._async_success_for_operation(
                    operation_id, value, success, done_label
                ),
            )

        threading.Thread(target=runner, daemon=True).start()

    def _async_success(
        self,
        result: object,
        success: Callable[[object], None] | None,
        done_label: str = "Операцію завершено",
    ) -> None:
        self.set_status("Готово")
        self._finish_operation(done_label)
        if success:
            try:
                success(result)
            except Exception as exc:
                self._show_error(exc)

    def _show_error(self, error: Exception) -> None:
        self.set_status("Помилка")
        self._finish_operation(str(error), error=True)
        self.msg.showerror("UA FREE Content Tool", str(error), parent=self.root)

    def t(self, text: str) -> str:
        config = getattr(self, 'config', None)
        return tr(text, getattr(config, 'ui_language', 'uk'))

    def _apply_language(self, *, refresh: bool = True) -> None:
        language = normalize_language(
            language_from_label(self.ui_language_var.get())
            if hasattr(self, "ui_language_var")
            else self.config.ui_language
        )
        self.config.ui_language = language
        self.root.title("UA FREE Content Tool — v1.1.1")
        localize_widget_tree(self.root, language)
        for variable in (getattr(self, 'status_var', None), getattr(self, 'operation_var', None), getattr(self, 'operation_detail_var', None)):
            if variable is not None:
                variable.set(tr(original_text(variable.get()), language))
        if hasattr(self, "group_filter_box"):
            current = original_text(self.group_filter.get())
            values = tuple(tr(item, language) for item in GROUP_FILTERS)
            self.group_filter_box.configure(values=values)
            self.group_filter.set(tr(current if current in GROUP_FILTERS else "Активні", language))
        if hasattr(self, "queue_filter_box"):
            current = original_text(self.queue_filter.get())
            values = tuple(tr(item, language) for item in QUEUE_FILTERS)
            self.queue_filter_box.configure(values=values)
            self.queue_filter.set(tr(current if current in QUEUE_FILTERS else "Активні", language))
        if hasattr(self, "settings_language_status_var"):
            self.settings_language_status_var.set(
                "Interface and Ollama output: English"
                if language == "en"
                else "Інтерфейс і вихід Ollama: українська"
            )
        if refresh and hasattr(self, "groups_tree"):
            self.refresh_groups()
            self.refresh_queue()
            self.refresh_history()

    def preview_language(self, *_args: object) -> None:
        self._apply_language()
        self._mark_settings_dirty()

    # Sources
    def _build_sources_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Джерела")

        form = ttk.Frame(tab)
        form.pack(fill="x")
        self.source_kind = tk.StringVar(value="rss")
        self.source_name = tk.StringVar()
        self.source_url = tk.StringVar()
        ttk.Label(form, text="Тип").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            form,
            textvariable=self.source_kind,
            values=("rss", "telegram", "url"),
            state="readonly",
            width=12,
        ).grid(row=1, column=0, padx=(0, 8), sticky="ew")
        ttk.Label(form, text="Назва").grid(row=0, column=1, sticky="w")
        ttk.Entry(form, textvariable=self.source_name, width=28).grid(row=1, column=1, padx=(0, 8), sticky="ew")
        ttk.Label(form, text="URL або @telegram_channel").grid(row=0, column=2, sticky="w")
        ttk.Entry(form, textvariable=self.source_url).grid(row=1, column=2, padx=(0, 8), sticky="ew")
        ttk.Button(form, text="Додати", command=self.add_source).grid(row=1, column=3, padx=4)
        form.columnconfigure(2, weight=1)

        buttons = ttk.Frame(tab)
        buttons.pack(fill="x", pady=(10, 4))
        ttk.Button(buttons, text="Оновити список", command=self.refresh_sources).pack(side="left")
        ttk.Button(buttons, text="Видалити", command=self.delete_source).pack(side="left", padx=6)
        self.auto_collect_status_var = tk.StringVar(
            value="Автоматичне оновлення: після запуску і кожні 5 хвилин"
        )
        ttk.Label(buttons, textvariable=self.auto_collect_status_var, foreground="#555").pack(side="right")

        columns = ("id", "kind", "name", "url", "checked")
        self.sources_tree = ttk.Treeview(tab, columns=columns, show="headings", selectmode="browse")
        widths = {"id": 60, "kind": 100, "name": 240, "url": 560, "checked": 180}
        labels = {"id": "ID", "kind": "Тип", "name": "Назва", "url": "Адреса", "checked": "Остання перевірка"}
        for column in columns:
            self.sources_tree.heading(column, text=labels[column])
            self.sources_tree.column(column, width=widths[column], anchor="w")
        self.sources_tree.pack(fill="both", expand=True)

    def add_source(self) -> None:
        kind = self.source_kind.get().strip()
        name = self.source_name.get().strip()
        url = self.source_url.get().strip()
        if not name or not url:
            self.msg.showwarning("Джерело", "Вкажіть назву та адресу.", parent=self.root)
            return
        try:
            self.db.add_source(kind, name, url)
        except Exception as exc:
            self._show_error(exc)
            return
        self.source_name.set("")
        self.source_url.set("")
        self.refresh_sources()

    def refresh_sources(self) -> None:
        self.sources_tree.delete(*self.sources_tree.get_children())
        for source in self.db.list_sources():
            self.sources_tree.insert(
                "",
                "end",
                iid=str(source.id),
                values=(source.id, source.kind, source.name, source.url, source.last_checked_at or "—"),
            )

    def _selected_source_ids(self) -> list[int]:
        return [int(item) for item in self.sources_tree.selection()]

    def delete_source(self) -> None:
        ids = self._selected_source_ids()
        if not ids:
            return
        if not self.msg.askyesno("Видалення", "Видалити вибране джерело і його матеріали?", parent=self.root):
            return
        for source_id in ids:
            self.db.delete_source(source_id)
        self.refresh_sources()
        self.refresh_groups()

    def _collect(self, source_ids: set[int] | None) -> tuple[int, list[str]]:
        total = 0
        errors: list[str] = []
        for source in self.db.list_sources(enabled_only=True):
            if source_ids is not None and source.id not in source_ids:
                continue
            try:
                items = collect_source(source)
                total += self.db.insert_collected(int(source.id), items)
            except Exception as exc:
                errors.append(f"{source.name}: {exc}")
        return total, errors

    def _schedule_next_auto_collect(self) -> None:
        if self.auto_collect_after_id is not None:
            try:
                self.root.after_cancel(self.auto_collect_after_id)
            except tk.TclError:
                pass
            self.auto_collect_after_id = None
        if self.stop_event.is_set():
            return
        next_check = datetime.now(KYIV) + timedelta(milliseconds=AUTO_COLLECT_INTERVAL_MS)
        if hasattr(self, "auto_collect_status_var"):
            self.auto_collect_status_var.set(
                f"Автоматичне оновлення: кожні 5 хвилин · наступна перевірка о {next_check:%H:%M}"
            )
        self.auto_collect_after_id = self.root.after(AUTO_COLLECT_INTERVAL_MS, self._auto_collect)

    def _auto_collect(self) -> None:
        self.auto_collect_after_id = None
        if self.auto_collect_running or self.stop_event.is_set():
            self._schedule_next_auto_collect()
            return
        self.auto_collect_running = True
        if hasattr(self, "auto_collect_status_var"):
            self.auto_collect_status_var.set("Автоматичне оновлення: перевірка триває…")
        self.set_status("Автоматично перевіряю всі джерела…")

        def runner() -> None:
            try:
                result = self._collect(None)
            except Exception as exc:
                self.root.after(0, lambda: self._after_auto_collect_error(exc))
                return
            self.root.after(0, lambda: self._after_auto_collect(result))

        threading.Thread(target=runner, name="automatic-news-collector", daemon=True).start()

    def _after_auto_collect_error(self, error: Exception) -> None:
        self.auto_collect_running = False
        self.set_status(f"Автоматичне оновлення не вдалося: {error}")
        self._schedule_next_auto_collect()

    def _after_auto_collect(self, result: object) -> None:
        self.auto_collect_running = False
        total, errors = result  # type: ignore[misc]
        self.refresh_sources()
        self.refresh_groups()
        self._notify_current_group_updates()
        if errors:
            self.set_status(
                f"Автооновлення завершено. Сьогодні додано: {total}. "
                f"Джерел з помилками: {len(errors)}. Наступна перевірка через 5 хвилин."
            )
        else:
            self.set_status(
                f"Автооновлення завершено. Сьогодні додано нових матеріалів: {total}. "
                "Наступна перевірка через 5 хвилин."
            )
        self._schedule_next_auto_collect()

    # Inbox groups
    def _build_inbox_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Вхідні")

        actions = ttk.Frame(tab)
        actions.pack(fill="x", pady=(0, 6))
        self.group_filter = tk.StringVar(value="Активні")
        ttk.Label(actions, text="Показати").grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.group_filter_box = ttk.Combobox(
            actions, textvariable=self.group_filter, values=tuple(GROUP_FILTERS),
            state="readonly", width=13,
        )
        self.group_filter_box.grid(row=0, column=1, sticky="w", padx=(0, 5))
        self.group_filter_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh_groups())
        ttk.Button(actions, text="Оновити", command=self.refresh_groups).grid(row=0, column=2, padx=3)
        ttk.Button(actions, text="Відновити / прийняти", command=self.accept_selected_group).grid(row=0, column=3, padx=3)
        ttk.Button(actions, text="Видалити", command=self.delete_selected_groups).grid(row=0, column=4, padx=3)
        tk.Button(
            actions, text="Запам’ятати й більше не пропонувати",
            command=self.remember_and_exclude_selected_groups, bg="#b3261e", fg="white",
            activebackground="#8f1f19", activeforeground="white", relief="flat", padx=9, pady=4,
        ).grid(row=0, column=5, padx=3)
        ttk.Button(
            actions, text="Пошук схожих за темою матеріалів", command=self.find_all_by_topic
        ).grid(row=0, column=6, padx=3)
        tk.Button(
            actions, text="Об’єднати в один блок", command=self.merge_selected_groups,
            bg="#2e7d32", fg="white", activebackground="#256628", activeforeground="white",
            relief="flat", padx=9, pady=4,
        ).grid(row=0, column=7, padx=3)
        actions.columnconfigure(8, weight=1)

        self.topic_search_status_var = tk.StringVar(
            value="Оберіть одну новину й натисніть «Пошук схожих за темою матеріалів»."
        )
        ttk.Label(tab, textvariable=self.topic_search_status_var, foreground="#555", wraplength=1350).pack(
            fill="x", pady=(0, 4)
        )
        ttk.Label(
            tab,
            text="Вибір: Shift — діапазон, Ctrl — окремі блоки, Ctrl+A — усі видимі, Delete — просте видалення.",
        ).pack(fill="x", pady=(0, 6))

        tree_frame = ttk.Frame(tab)
        tree_frame.pack(fill="both", expand=True)
        columns = ("id", "status", "title", "sources", "published", "score")
        self.groups_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="extended")
        headings = {
            "id": "Блок", "status": "Статус", "title": "Подія", "sources": "Джерел",
            "published": "Остання згадка", "score": "Вибуховість",
        }
        widths = {"id": 70, "status": 100, "title": 650, "sources": 90, "published": 190, "score": 120}
        for column in columns:
            self.groups_tree.heading(column, text=headings[column])
            self.groups_tree.column(column, width=widths[column], anchor="w")
        self.groups_tree.tag_configure("approved", background="#e7f5e8")
        self.groups_tree.tag_configure("topic_strong", background="#dff2df")
        self.groups_tree.tag_configure("topic_possible", background="#fff4cc")
        groups_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.groups_tree.yview)
        self.groups_tree.configure(yscrollcommand=groups_scroll.set)
        self.groups_tree.pack(side="left", fill="both", expand=True)
        groups_scroll.pack(side="right", fill="y")
        self.groups_tree.bind("<Button-1>", self._remember_group_selection_anchor, add="+")
        self.groups_tree.bind("<Shift-Button-1>", self._select_group_range)
        self.groups_tree.bind("<Double-1>", lambda _event: self.accept_selected_group())
        self.groups_tree.bind("<Control-a>", self._select_all_group_rows)
        self.groups_tree.bind("<Control-A>", self._select_all_group_rows)
        self.groups_tree.bind("<Delete>", self._delete_selected_group_rows)
        self.groups_tree.bind("<Prior>", self._page_group_tree)
        self.groups_tree.bind("<Next>", self._page_group_tree)
        self.groups_tree.bind("<Home>", self._page_group_tree)
        self.groups_tree.bind("<End>", self._page_group_tree)

    def _page_group_tree(self, event: tk.Event) -> str:
        key = str(getattr(event, "keysym", ""))
        if key == "Prior":
            self.groups_tree.yview_scroll(-1, "pages")
        elif key == "Next":
            self.groups_tree.yview_scroll(1, "pages")
        elif key == "Home":
            self.groups_tree.yview_moveto(0.0)
        elif key == "End":
            self.groups_tree.yview_moveto(1.0)
        return "break"

    def refresh_groups(self) -> None:
        selected_before = tuple(self.groups_tree.selection())
        focus_before = self.groups_tree.focus()
        yview_before = self.groups_tree.yview()
        self.groups_tree.delete(*self.groups_tree.get_children())
        selected_filter = original_text(self.group_filter.get())
        status = GROUP_FILTERS.get(selected_filter)
        for group in self.db.list_groups(status=status):
            score = f"{group.explosiveness_score}/100" if group.explosiveness_score else "—"
            tags = ("approved",) if group.status == "approved" else ()
            self.groups_tree.insert(
                "", "end", iid=str(group.id),
                values=(
                    group.id,
                    tr(GROUP_STATUS_LABELS.get(group.status, group.status), self.config.ui_language),
                    group.canonical_title, group.source_count, group.last_published_at or "—", score,
                ),
                tags=tags,
            )
        existing = [iid for iid in selected_before if self.groups_tree.exists(iid)]
        if existing:
            self.groups_tree.selection_set(existing)
        if focus_before and self.groups_tree.exists(focus_before):
            self.groups_tree.focus(focus_before)
        if yview_before:
            self.groups_tree.yview_moveto(float(yview_before[0]))

    def refresh_articles(self) -> None:
        self.refresh_groups()

    def refresh_current_group(self) -> None:
        if self.current_group_id is not None:
            self.load_group(self.current_group_id)
            self.set_status("Блок оновлено з усіма наявними джерелами")

    def _notify_current_group_updates(self) -> None:
        if self.current_group_id is None:
            return
        try:
            latest = self.db.get_group(self.current_group_id)
        except KeyError:
            return
        known = len(self.current_group_articles)
        if latest.source_count > known:
            added = latest.source_count - known
            self.set_status(
                f"До відкритого блоку додано нових джерел: {added}. "
                "Натисніть «Оновити блок», а потім за потреби повторіть рерайт."
            )


    @staticmethod
    def _tree_range(rows: tuple[str, ...], anchor_iid: str | None, target_iid: str) -> tuple[str, ...]:
        """Return an inclusive visual range for deterministic Shift selection."""
        if not rows or target_iid not in rows:
            return ()
        anchor = anchor_iid if anchor_iid in rows else target_iid
        start = rows.index(anchor)
        end = rows.index(target_iid)
        lo, hi = sorted((start, end))
        return rows[lo : hi + 1]

    def _remember_group_selection_anchor(self, event: tk.Event) -> None:
        # Native ttk range selection is inconsistent on some Windows/Tk builds.
        # Record a deterministic anchor on an ordinary click, then handle Shift
        # ourselves instead of trusting the class binding.
        if int(getattr(event, "state", 0)) & 0x0005:
            return
        iid = self.groups_tree.identify_row(int(event.y))
        if iid:
            self._groups_selection_anchor = iid

    def _select_group_range(self, event: tk.Event) -> str:
        target = self.groups_tree.identify_row(int(event.y))
        rows = tuple(self.groups_tree.get_children())
        if not target:
            return "break"
        anchor = self._groups_selection_anchor
        if anchor not in rows:
            focus = self.groups_tree.focus()
            selection = self.groups_tree.selection()
            anchor = focus if focus in rows else (selection[0] if selection else target)
        selected = self._tree_range(rows, anchor, target)
        if selected:
            self.groups_tree.selection_set(selected)
            self.groups_tree.focus(target)
            self.groups_tree.see(target)
            self._groups_selection_anchor = anchor
        return "break"

    def _selected_group_ids(self) -> list[int]:
        selected = set(self.groups_tree.selection())
        return [int(item) for item in self.groups_tree.get_children() if item in selected]

    def _selected_group_id(self) -> int | None:
        selection = self._selected_group_ids()
        return selection[0] if len(selection) == 1 else None

    def _require_single_group_id(self, action: str) -> int | None:
        selection = self._selected_group_ids()
        if not selection:
            self.msg.showinfo("Вхідні", "Оберіть блок у списку.", parent=self.root)
            return None
        if len(selection) > 1:
            self.msg.showinfo(
                "Вхідні",
                f"Для дії «{action}» залиште вибраним один блок. Зараз вибрано: {len(selection)}.",
                parent=self.root,
            )
            return None
        return selection[0]

    def _select_all_group_rows(self, _event: object | None = None) -> str:
        rows = self.groups_tree.get_children()
        if rows:
            self.groups_tree.selection_set(rows)
            self.groups_tree.focus(rows[0])
        return "break"

    def accept_selected_group(self) -> None:
        group_id = self._require_single_group_id("Відновити / прийняти")
        if group_id is None:
            return
        group = self.db.get_group(group_id)
        if group.status == "rejected":
            self.db.set_group_status(group_id, "new")
        forgotten = self.db.forget_content_exclusion_for_group(group_id)
        if forgotten and self.config.learning_enabled:
            self.db.record_learning_event(
                "exclusion_restored", language=self.config.ui_language, group_id=group_id,
                payload={"rules_deactivated": forgotten},
            )
        self.load_group(group_id)
        self.refresh_groups()
        self.notebook.select(self.editor_tab)
        if self.config.threads_trend_search_enabled and self.config.platform_ready("threads"):
            self.root.after(100, self.analyze_current)

    def _delete_selected_group_rows(self, _event: object | None = None) -> str:
        self.delete_selected_groups()
        return "break"

    def reject_selected_group(self) -> None:
        # Backward-compatible command used by older integrations.
        self.delete_selected_groups()

    def reject_selected_groups(self) -> None:
        # Backward-compatible alias. This action deliberately does not teach the
        # permanent exclusion memory.
        self.delete_selected_groups()

    def delete_selected_groups(self) -> None:
        group_ids = self._selected_group_ids()
        if not group_ids:
            self.msg.showinfo("Вхідні", "Оберіть одну або кілька новин у списку.", parent=self.root)
            return
        shown = ", ".join(f"#{group_id}" for group_id in group_ids[:12])
        if len(group_ids) > 12:
            shown += f" та ще {len(group_ids) - 12}"
        question = (
            f"Видалити з активного списку {len(group_ids)} вибрані новини?\n\n"
            f"Вибрано: {shown}.\n\n"
            "Це просте видалення. Система не вчитиметься на цій дії й не блокуватиме схожі новини в майбутньому."
        )
        if not self.msg.askyesno("Видалення новин", question, parent=self.root):
            return
        try:
            changed = self.db.set_groups_status(group_ids, "rejected")
        except Exception as exc:
            self._show_error(exc)
            return
        self.refresh_groups()
        self.set_status(f"Видалено з активного списку: {changed}. Навчальна пам’ять не змінена.")

    def remember_and_exclude_selected_groups(self) -> None:
        group_ids = self._selected_group_ids()
        if not group_ids:
            self.msg.showinfo("Вхідні", "Оберіть одну або кілька новин у списку.", parent=self.root)
            return
        question = (
            f"Запам’ятати {len(group_ids)} вибрані новини як небажані?\n\n"
            "Вони зникнуть з активного списку. Під час наступних зборів програма локально відфільтровуватиме "
            "дуже схожі матеріали, не запускаючи Ollama. Дію можна скасувати, відновивши цей блок у «Відхилених»."
        )
        if not self.msg.askyesno("Запам’ятати й виключати", question, parent=self.root):
            return
        try:
            remembered = self.db.remember_content_exclusions(group_ids)
            if self.config.learning_enabled:
                for group_id in group_ids:
                    self.db.record_learning_event(
                        "content_excluded", language=self.config.ui_language, group_id=group_id,
                        payload={"selected_group_ids": group_ids},
                    )
        except Exception as exc:
            self._show_error(exc)
            return
        self.refresh_groups()
        self.set_status(
            f"Запам’ятано для майбутнього виключення: {remembered}. "
            f"Активних правил: {self.db.content_exclusion_count()}."
        )

    def find_all_by_topic(self) -> None:
        anchor_id = self._require_single_group_id("Пошук схожих за темою матеріалів")
        if anchor_id is None:
            return
        try:
            anchor = self.db.get_group(anchor_id)
        except Exception as exc:
            self._show_error(exc)
            return
        candidate_rows = self.db.topic_candidate_rows(anchor_id)
        topic_feedback = (
            self.db.list_topic_feedback(language=self.config.ui_language)
            if self.config.learning_enabled
            else []
        )
        local_candidates = rank_topic_candidates(
            anchor.combined_text or anchor.canonical_title,
            candidate_rows,
            feedback=topic_feedback,
            limit=12,
            language=self.config.ui_language,
        )
        if not local_candidates:
            self.topic_search_status_var.set(self.t("Схожих матеріалів для об’єднання не знайдено."))
            return
        rows_by_id = {int(row["group_id"]): row for row in candidate_rows}
        shortlisted = [rows_by_id[item.group_id] for item in local_candidates if item.group_id in rows_by_id]
        self.topic_search_status_var.set(
            (f"Ollama is checking {len(shortlisted)} candidates…" if self.config.ui_language == "en"
             else f"Ollama перевіряє {len(shortlisted)} кандидатів…")
        )

        def action() -> object:
            prompt = build_topic_prompt(
                anchor.canonical_title, anchor.combined_text, shortlisted,
                feedback=topic_feedback, language=self.config.ui_language,
            )
            try:
                client = OllamaClient(self.config.ollama_base_url, timeout=180, load_timeout=120)
                raw = client.generate_text(self.config.ollama_model, prompt, num_predict=700)
                model_matches = parse_topic_matches(raw)
                error = ""
            except OllamaError as exc:
                model_matches = {}
                error = str(exc)
            return merge_local_and_ollama(local_candidates, model_matches, minimum_score=45), error

        def success(result: object) -> None:
            matches, error = result  # type: ignore[misc]
            candidate_data: list[dict[str, object]] = []
            for match in matches:
                row = rows_by_id.get(match.group_id)
                if row is None:
                    continue
                candidate_data.append({**row, "score": match.score, "reason": match.reason})
            if not candidate_data:
                suffix = f" {error}" if error else ""
                self.topic_search_status_var.set(self.t("Схожих матеріалів для об’єднання не знайдено.") + suffix)
                return
            self.topic_search_status_var.set(
                (f"Merge candidates: {len(candidate_data)}" if self.config.ui_language == "en"
                 else f"Кандидатів на об’єднання: {len(candidate_data)}")
            )
            TopicCandidatesDialog(
                self.root, anchor_id=anchor_id, anchor_title=anchor.canonical_title,
                candidates=candidate_data, language=self.config.ui_language,
                on_merge=lambda selected, all_ids: self._merge_topic_candidates(
                    anchor_id, selected, all_ids
                ),
            )

        self.run_async(
            action, success,
            label=(f"Topic search for block #{anchor_id}" if self.config.ui_language == "en"
                   else f"Пошук матеріалів по темі блоку #{anchor_id}"),
            done_label=("Topic search completed" if self.config.ui_language == "en"
                        else "Тематичний пошук завершено"),
        )

    def _merge_topic_candidates(
        self, anchor_id: int, selected_ids: list[int], all_candidate_ids: list[int]
    ) -> None:
        if not selected_ids:
            return
        group_ids = [anchor_id, *selected_ids]
        try:
            anchor = self.db.get_group(anchor_id)
            candidate_groups = {group_id: self.db.get_group(group_id) for group_id in all_candidate_ids}
            moved = self.db.merge_groups(anchor_id, group_ids)
            if self.config.learning_enabled:
                for group_id, candidate in candidate_groups.items():
                    decision = "merged" if group_id in selected_ids else "not_related"
                    self.db.record_topic_feedback(
                        anchor.combined_text or anchor.canonical_title,
                        candidate.combined_text or candidate.canonical_title,
                        decision=decision, language=self.config.ui_language,
                    )
                self.db.record_learning_event(
                    "topic_candidate_selection", language=self.config.ui_language,
                    group_id=anchor_id, anchor_group_id=anchor_id,
                    payload={"selected": selected_ids, "rejected": [i for i in all_candidate_ids if i not in selected_ids]},
                )
        except Exception as exc:
            self._show_error(exc)
            return
        self.refresh_groups()
        if self.groups_tree.exists(str(anchor_id)):
            self.groups_tree.selection_set(str(anchor_id))
            self.groups_tree.focus(str(anchor_id))
            self.groups_tree.see(str(anchor_id))
        self.set_status(
            (f"Merged {len(selected_ids)} candidates; moved sources: {moved}."
             if self.config.ui_language == "en"
             else f"Об’єднано кандидатів: {len(selected_ids)}; перенесено джерел: {moved}.")
        )

    def merge_selected_groups(self) -> None:
        group_ids = self._selected_group_ids()
        if len(group_ids) < 2:
            self.msg.showinfo(
                "Об’єднання блоків",
                "Оберіть щонайменше два блоки. Для суцільного діапазону використовуйте Shift, "
                "для окремих рядків — Ctrl.",
                parent=self.root,
            )
            return

        target_group_id = group_ids[0]
        try:
            groups = [self.db.get_group(group_id) for group_id in group_ids]
        except Exception as exc:
            self._show_error(exc)
            return
        target = groups[0]
        source_count = sum(group.source_count for group in groups)
        shown = ", ".join(f"#{group.id}" for group in groups[:12])
        if len(groups) > 12:
            shown += f" та ще {len(groups) - 12}"
        if not self.msg.askyesno(
            "Об’єднання блоків",
            f"Об’єднати {len(groups)} вибрані блоки в один?\n\n"
            f"Основним залишиться верхній вибраний блок #{target.id}:\n{target.canonical_title}\n\n"
            f"До нього буде зібрано джерел: {source_count}.\n"
            f"Вибрані блоки: {shown}.\n\n"
            "Попередній рерайт, факт-картка, платформні тексти та оцінка вибуховості будуть очищені, "
            "бо після додавання джерел їх потрібно створити заново. Медіа основного блоку збережеться.",
            parent=self.root,
        ):
            return

        try:
            moved_articles = self.db.merge_groups(target_group_id, group_ids)
            learned_pairs = sum(
                1
                for source_group in groups[1:]
                if self.db.record_topic_feedback(
                    target.combined_text or target.canonical_title,
                    source_group.combined_text or source_group.canonical_title,
                    decision="merged",
                    language=self.config.ui_language,
                )
            )
            if self.config.learning_enabled:
                self.db.record_learning_event(
                    "manual_groups_merged", language=self.config.ui_language,
                    group_id=target_group_id, anchor_group_id=target_group_id,
                    payload={"merged_group_ids": group_ids[1:], "moved_articles": moved_articles},
                )
        except Exception as exc:
            self._show_error(exc)
            return

        self.refresh_groups()
        target_iid = str(target_group_id)
        if self.groups_tree.exists(target_iid):
            self.groups_tree.selection_set(target_iid)
            self.groups_tree.focus(target_iid)
            self.groups_tree.see(target_iid)
        merged = self.db.get_group(target_group_id)
        self.set_status(
            f"Об’єднано {len(group_ids)} блоки в блок #{target_group_id}. "
            f"Перенесено джерел: {moved_articles}; у блоці тепер: {merged.source_count}. "
            f"Навчальних пар для тематичного пошуку додано: {learned_pairs}."
        )
        self.msg.showinfo(
            "Об’єднання завершено",
            f"Створено один блок #{target_group_id} із {merged.source_count} джерел. "
            "Відкрийте його в редакторі та виконайте новий рерайт.",
            parent=self.root,
        )

    # Editor
    def _build_editor_tab(self) -> None:
        self.editor_tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.editor_tab, text="Редактор")

        header = ttk.Frame(self.editor_tab)
        header.pack(fill="x")
        header.columnconfigure(0, weight=1)
        self.editor_group_label = tk.StringVar(value="Блок не вибрано")
        ttk.Label(header, textvariable=self.editor_group_label, font="TkHeadingFont", wraplength=1250).grid(
            row=0, column=0, sticky="ew", columnspan=2
        )
        actions = ttk.Frame(header)
        actions.grid(row=1, column=0, columnspan=2, sticky="e", pady=(5, 0))
        self.save_block_button = ttk.Button(actions, text="Зберегти", command=self.save_current)
        self.save_block_button.pack(side="left", padx=3)
        self.refresh_block_button = ttk.Button(actions, text="Оновити блок", command=self.refresh_current_group)
        self.refresh_block_button.pack(side="left", padx=3)
        self.analyze_button = ttk.Button(actions, text="Оцінити вибуховість", command=self.analyze_current)
        self.analyze_button.pack(side="left", padx=3)
        self.rewrite_button = ttk.Button(actions, text="Рерайт через Ollama", command=self.rewrite_current)
        self.rewrite_button.pack(side="left", padx=3)
        self.operation_buttons.extend([self.analyze_button, self.rewrite_button])

        analysis = ttk.Frame(self.editor_tab)
        analysis.pack(fill="x", pady=(6, 3))
        analysis.columnconfigure(0, weight=1)
        self.analysis_var = tk.StringVar(value="Вибуховість не розрахована")
        self.analysis_detail_var = tk.StringVar(
            value="Threads-пошук покаже окремо: які запити виконано, скільки збігів і чи була помилка API."
        )
        self.analysis_label = ttk.Label(analysis, textvariable=self.analysis_var, foreground="#333", wraplength=1300)
        self.analysis_label.grid(row=0, column=0, sticky="w")
        self.analysis_detail_label = ttk.Label(
            analysis, textvariable=self.analysis_detail_var, foreground="#666", wraplength=1300
        )
        self.analysis_detail_label.grid(row=1, column=0, sticky="w", pady=(2, 0))

        # Compact fixed bar remains visible at every window size. Detailed
        # platform/media controls live in the dedicated «Публікація» editor tab.
        queue_bar = ttk.Frame(self.editor_tab, padding=(4, 5))
        queue_bar.pack(side="bottom", fill="x")
        ttk.Label(queue_bar, text="Куди публікувати:", font="TkHeadingFont").pack(side="left")
        self.selected_targets_var = tk.StringVar(value="Не вибрано")
        ttk.Label(queue_bar, textvariable=self.selected_targets_var, foreground="#555").pack(side="left", padx=(8, 12))
        ttk.Button(queue_bar, text="Налаштувати платформи й медіа", command=self.open_publication_settings).pack(side="left")
        self.queue_button = ttk.Button(
            queue_bar,
            text="СХВАЛИТИ Й ПОСТАВИТИ В ЧЕРГУ",
            command=self.approve_current,
        )
        self.queue_button.pack(side="right")

        self.editor_panes = tk.PanedWindow(
            self.editor_tab, orient="horizontal", sashwidth=7, sashrelief="raised", borderwidth=0
        )
        self.editor_panes.pack(fill="both", expand=True, pady=(3, 0))
        self.editor_left = ttk.Frame(self.editor_panes)
        self.editor_right = ttk.Frame(self.editor_panes)
        self.editor_panes.add(self.editor_left, minsize=330, stretch="always")
        self.editor_panes.add(self.editor_right, minsize=420, stretch="always")

        source_header = ttk.Frame(self.editor_left)
        source_header.pack(fill="x")
        ttk.Label(source_header, text="Тексти всіх джерел").pack(side="left")
        ttk.Button(source_header, text="Відкрити новину", command=self.open_selected_source).pack(side="right")
        columns = ("n", "source", "title", "time")
        self.group_sources_tree = ttk.Treeview(
            self.editor_left, columns=columns, show="headings", height=6, selectmode="browse"
        )
        for column, label, width in (
            ("n", "№", 40),
            ("source", "Джерело", 130),
            ("title", "Заголовок", 330),
            ("time", "Час", 150),
        ):
            self.group_sources_tree.heading(column, text=label)
            self.group_sources_tree.column(column, width=width, anchor="w", stretch=(column == "title"))
        self.group_sources_tree.pack(fill="x", pady=(4, 5))
        self.group_sources_tree.bind("<<TreeviewSelect>>", lambda _event: self.show_selected_source())
        self.raw_text = ScrolledText(self.editor_left, wrap="word", height=16)
        self.raw_text.pack(fill="both", expand=True)
        self.raw_text.configure(state="disabled")

        ttk.Label(self.editor_right, text="Заголовок").pack(anchor="w")
        self.headline_var = tk.StringVar()
        ttk.Entry(self.editor_right, textvariable=self.headline_var).pack(fill="x", pady=(0, 5))
        ttk.Label(self.editor_right, text="Факт-картка і суперечності між джерелами").pack(anchor="w")
        self.fact_card_text = ScrolledText(self.editor_right, wrap="word", height=5)
        self.fact_card_text.pack(fill="x", pady=(0, 5))

        self.same_text_var = tk.BooleanVar(value=True)  # compatibility: FIX28 always uses one canonical text
        self.text_widgets: dict[str, ScrolledText] = {}
        self.metric_vars: dict[str, tk.StringVar] = {}

        publication_text_box = ttk.LabelFrame(
            self.editor_right,
            text="Текст публікації: один для всіх мереж",
            padding=5,
        )
        publication_text_box.pack(fill="both", expand=True)
        rewrite_widget = ScrolledText(publication_text_box, wrap="word", height=16)
        rewrite_widget.pack(fill="both", expand=True)
        rewrite_widget.edit_modified(False)
        rewrite_widget.bind("<<Modified>>", self._on_base_rewrite_modified)
        self.text_widgets["rewrite"] = rewrite_widget
        self.metric_vars["rewrite"] = tk.StringVar(value=f"0 / {EDITORIAL_TEXT_LIMIT} символів")
        ttk.Label(
            publication_text_box,
            textvariable=self.metric_vars["rewrite"],
            foreground="#555",
        ).pack(anchor="e", pady=(3, 0))
        self.publication_preview_var = tk.StringVar(
            value="Facebook, LinkedIn і Telegram: один допис з медіа. Threads: автоматичний ланцюжок за потреби."
        )
        ttk.Label(
            publication_text_box,
            textvariable=self.publication_preview_var,
            foreground="#555",
            wraplength=900,
        ).pack(anchor="w", pady=(2, 0))
        self.editorial_memory_var = tk.StringVar(value="Редакційна пам’ять: 0 схвалених прикладів")
        ttk.Label(
            publication_text_box,
            textvariable=self.editorial_memory_var,
            foreground="#666",
        ).pack(anchor="w", pady=(2, 0))

        self.publication_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.publication_tab, text="Публікація")
        self.publication_tab.columnconfigure(0, weight=1)
        self.publication_tab.rowconfigure(3, weight=1)

        media = ttk.LabelFrame(self.publication_tab, text="Медіа з Google Drive", padding=7)
        media.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.media_url_var = tk.StringVar()
        self.media_status_var = tk.StringVar(value="Медіа не додано")
        ttk.Entry(media, textvariable=self.media_url_var).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.verify_media_button = ttk.Button(media, text="Перевірити медіа", command=self.verify_media)
        self.verify_media_button.grid(row=0, column=1, padx=3)
        ttk.Button(media, text="Відкрити файл", command=self.open_media_link).grid(row=0, column=2, padx=3)
        ttk.Button(media, text="Прибрати", command=self.clear_media).grid(row=0, column=3, padx=3)
        ttk.Label(media, textvariable=self.media_status_var, foreground="#555", wraplength=1200).grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(4, 0)
        )
        media.columnconfigure(0, weight=1)
        self.operation_buttons.append(self.verify_media_button)

        target_tools = ttk.Frame(self.publication_tab)
        target_tools.grid(row=1, column=0, sticky="ew")
        ttk.Label(target_tools, text="Оберіть платформи:", font="TkHeadingFont").pack(side="left")
        ttk.Label(target_tools, textvariable=self.selected_targets_var, foreground="#555").pack(side="left", padx=(10, 0))
        ttk.Button(target_tools, text="Усі доступні", command=self.select_all_targets).pack(side="right")
        ttk.Button(target_tools, text="Очистити", command=self.clear_all_targets).pack(side="right", padx=5)

        options_row = ttk.Frame(self.publication_tab)
        options_row.grid(row=2, column=0, sticky="ew", pady=(6, 4))
        ttk.Label(
            options_row,
            text="Один текст до 900 символів використовується для всіх платформ.",
            foreground="#555",
        ).pack(side="left", padx=(0, 10))
        self.include_source_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            options_row,
            text="Додати посилання на джерело",
            variable=self.include_source_var,
            command=self.update_text_metrics,
        ).pack(side="left", padx=(0, 10))
        ttk.Label(options_row, text="Абзац про збір UA FREE додається завжди.", foreground="#555").pack(side="left")

        targets_box = ttk.LabelFrame(self.publication_tab, text="Доступні сторінки й профілі", padding=7)
        targets_box.grid(row=3, column=0, sticky="nsew", pady=(4, 8))
        self.targets_canvas = tk.Canvas(targets_box, highlightthickness=0)
        targets_scroll = ttk.Scrollbar(targets_box, orient="vertical", command=self.targets_canvas.yview)
        self.targets_row = ttk.Frame(self.targets_canvas)
        self.targets_window_id = self.targets_canvas.create_window((0, 0), window=self.targets_row, anchor="nw")
        self.targets_row.bind(
            "<Configure>",
            lambda _event: self.targets_canvas.configure(scrollregion=self.targets_canvas.bbox("all")),
        )
        self.targets_canvas.bind(
            "<Configure>",
            lambda event: self.targets_canvas.itemconfigure(self.targets_window_id, width=event.width),
        )
        self.targets_canvas.configure(yscrollcommand=targets_scroll.set)
        self.targets_canvas.pack(side="left", fill="both", expand=True)
        targets_scroll.pack(side="right", fill="y")
        self.target_vars: dict[str, tk.BooleanVar] = {}
        self.target_checks: dict[str, ttk.Checkbutton] = {}
        self.target_column_count = 3
        self._rebuild_target_controls()
        self.publication_tab.bind("<Configure>", self._adapt_publication_layout, add="+")

        publication_actions = ttk.Frame(self.publication_tab)
        publication_actions.grid(row=4, column=0, sticky="ew")
        ttk.Label(
            publication_actions,
            text="Після схвалення матеріал переходить у вкладку «Черга».",
            foreground="#555",
        ).pack(side="left")
        ttk.Button(
            publication_actions,
            text="СХВАЛИТИ Й ПОСТАВИТИ В ЧЕРГУ",
            command=self.approve_current,
        ).pack(side="right")

        self.editor_layout_mode = "horizontal"
        self.editor_tab.bind("<Configure>", self._adapt_editor_layout, add="+")

    def open_publication_settings(self) -> None:
        self.notebook.select(self.publication_tab)

    def _adapt_editor_layout(self, event: tk.Event) -> None:
        width = max(1, int(getattr(event, "width", self.editor_tab.winfo_width())))
        desired = "vertical" if width < 1180 else "horizontal"
        if desired != self.editor_layout_mode:
            try:
                self.editor_panes.configure(orient=desired)
                if desired == "vertical":
                    self.editor_panes.paneconfigure(self.editor_left, minsize=80)
                    self.editor_panes.paneconfigure(self.editor_right, minsize=220)
                    self.root.after_idle(self._position_vertical_editor_sash)
                else:
                    self.editor_panes.paneconfigure(self.editor_left, minsize=330)
                    self.editor_panes.paneconfigure(self.editor_right, minsize=420)
                    self.root.after_idle(self._position_horizontal_editor_sash)
                self.editor_layout_mode = desired
            except tk.TclError:
                pass
        columns = 1 if width < 760 else 2 if width < 1180 else 3
        if columns != getattr(self, "target_column_count", 3):
            self.target_column_count = columns
            self._layout_target_controls()
        wrap = max(500, width - 80)
        self.analysis_label.configure(wraplength=wrap)
        self.analysis_detail_label.configure(wraplength=wrap)

    def _adapt_publication_layout(self, event: tk.Event) -> None:
        width = max(1, int(getattr(event, "width", self.publication_tab.winfo_width())))
        columns = 1 if width < 650 else 2 if width < 1050 else 3 if width < 1500 else 4
        if columns != getattr(self, "target_column_count", 3):
            self.target_column_count = columns
            self._layout_target_controls()

    def _position_vertical_editor_sash(self) -> None:
        try:
            height = max(1, self.editor_panes.winfo_height())
            self.editor_panes.sash_place(0, 0, max(85, int(height * 0.27)))
        except tk.TclError:
            pass

    def _position_horizontal_editor_sash(self) -> None:
        try:
            width = max(1, self.editor_panes.winfo_width())
            self.editor_panes.sash_place(0, max(330, int(width * 0.38)), 0)
        except tk.TclError:
            pass

    def _layout_target_controls(self) -> None:
        columns = max(1, getattr(self, "target_column_count", 3))
        for index, platform in enumerate(self.target_vars):
            check = self.target_checks[platform]
            check.grid_forget()
            check.grid(row=index // columns, column=index % columns, sticky="w", padx=(0, 18), pady=2)
        for column in range(3):
            self.targets_row.columnconfigure(column, weight=1 if column < columns else 0)
        self.targets_canvas.configure(height=70 if len(self.target_vars) <= columns else 92)

    def _update_selected_targets_summary(self) -> None:
        selected = sum(1 for variable in self.target_vars.values() if variable.get())
        available = sum(1 for key in self.target_vars if self.config.platform_ready(key))
        self.selected_targets_var.set(f"Вибрано: {selected} з {available}")

    def select_all_targets(self) -> None:
        for key, variable in self.target_vars.items():
            variable.set(self.config.platform_ready(key))
        self._update_selected_targets_summary()

    def clear_all_targets(self) -> None:
        for variable in self.target_vars.values():
            variable.set(False)
        self._update_selected_targets_summary()

    def _rebuild_target_controls(self) -> None:
        if not hasattr(self, "targets_row"):
            return
        previous = {key: variable.get() for key, variable in self.target_vars.items()}
        for child in self.targets_row.winfo_children():
            child.destroy()
        self.target_vars = {}
        self.target_checks = {}
        labels = target_labels(self.config)
        keys = publication_target_keys(self.config)
        for platform in keys:
            variable = tk.BooleanVar(value=previous.get(platform, False))
            ready = self.config.platform_ready(platform)
            check = ttk.Checkbutton(
                self.targets_row,
                text=labels.get(platform, platform),
                variable=variable,
                state="normal" if ready else "disabled",
                command=self._update_selected_targets_summary,
            )
            self.target_vars[platform] = variable
            self.target_checks[platform] = check
        if self.config.platform_ready("telegram") and not any(var.get() for var in self.target_vars.values()):
            self.target_vars["telegram"].set(True)
        self._layout_target_controls()
        self._update_selected_targets_summary()

    def load_group(self, group_id: int) -> None:
        group = self.db.get_group(group_id)
        self.current_group_id = group_id
        self.current_group_articles = group.articles
        self.editor_group_label.set(f"Блок #{group.id} · {group.canonical_title} · джерел: {group.source_count}")
        self.headline_var.set(group.headline or group.canonical_title)
        self._set_text(self.fact_card_text, group.fact_card)
        self.include_source_var.set(group.include_source_link)
        self._set_text(self.text_widgets["rewrite"], group.rewrite_text)
        self.editorial_memory_var.set(
            f"Редакційна пам’ять: {self.db.editorial_example_count()} схвалених прикладів"
        )
        self.media_url_var.set(group.media_drive_url)
        if group.media_file_id:
            self.media_status_var.set(
                f"{group.media_kind.upper()}: {group.media_name}, {group.media_size / (1024 * 1024):.1f} МБ. "
                "Після успішної публікації файл буде безповоротно видалено з Drive."
            )
        else:
            self.media_status_var.set("Медіа не додано")
        self.group_sources_tree.delete(*self.group_sources_tree.get_children())
        for index, article in enumerate(group.articles, start=1):
            self.group_sources_tree.insert(
                "",
                "end",
                iid=str(article.id),
                values=(index, article.source_name, article.title, article.published_at or "—"),
            )
        if group.articles:
            self.group_sources_tree.selection_set(str(group.articles[0].id))
            self.show_selected_source()
        self._display_analysis(group)
        queued_statuses = self.db.target_statuses_for_group(group.id)
        if queued_statuses:
            self.apply_existing_targets(queued_statuses)
        else:
            self.apply_recommendations(group.recommended_platforms)
        self.update_text_metrics()

    @staticmethod
    def _set_text(widget: ScrolledText, value: str, readonly: bool = False) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        if readonly:
            widget.configure(state="disabled")

    def show_selected_source(self) -> None:
        selection = self.group_sources_tree.selection()
        if not selection:
            return
        article_id = int(selection[0])
        article = next((item for item in self.current_group_articles if item.id == article_id), None)
        if article:
            self._set_text(self.raw_text, article.raw_text, readonly=True)

    def open_selected_source(self) -> None:
        selection = self.group_sources_tree.selection()
        if not selection:
            return
        article_id = int(selection[0])
        article = next((item for item in self.current_group_articles if item.id == article_id), None)
        if article and article.url:
            webbrowser.open(article.url, new=2)

    def open_media_link(self) -> None:
        if self.media_url_var.get().strip():
            webbrowser.open(self.media_url_var.get().strip(), new=2)

    def rewrite_current(self) -> None:
        if self.current_group_id is None:
            self.msg.showinfo("Редактор", "Спочатку прийміть блок у роботу.", parent=self.root)
            return
        self.db.set_group_options(self.current_group_id, include_source_link=self.include_source_var.get())
        group = self.db.get_group(self.current_group_id)
        config = self.config

        def action() -> object:
            # The selected model is normally preloaded in the background. If the
            # user clicks immediately after startup, briefly wait for that warmup
            # instead of sending a competing cold request to Ollama.
            event = self.ollama_prewarm_event
            if event is not None and self.ollama_prewarm_model == config.ollama_model and not event.is_set():
                event.wait(timeout=120)
            examples = rank_editorial_examples(
                group.combined_text,
                self.db.list_editorial_examples(language=config.ui_language),
                limit=config.learning_examples_limit if config.learning_enabled else 0,
            )
            primary_client = OllamaClient(config.ollama_base_url, timeout=240, load_timeout=120)
            fallback_client = OllamaClient(config.ollama_base_url, timeout=180, load_timeout=120)
            rewrite_result, model_used, used_fallback = rewrite_article_with_fallback(
                primary_client,
                config.ollama_model,
                config.ollama_fallback_model,
                group,
                fallback_client=fallback_client,
                editorial_examples=examples,
                language=config.ui_language,
            )
            return rewrite_result, model_used, used_fallback, len(examples)

        def success(result: object) -> None:
            rewrite_result, model_used, used_fallback, example_count = result  # type: ignore[misc]
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
            if config.learning_enabled:
                self.db.record_learning_event(
                    "rewrite_generated", language=config.ui_language, group_id=group.id,
                    payload={"model": model_used, "fallback": bool(used_fallback), "examples": example_count},
                )
            self.refresh_groups()
            self.update_text_metrics()
            memory_note = (
                f" · використано прикладів із редакційної пам’яті: {example_count}"
                if example_count
                else " · редакційна пам’ять ще накопичується"
            )
            source_note = (
                f" · передано моделі джерел: {rewrite_result.source_count_used} "
                f"із {rewrite_result.source_count_total}"
            )
            compact_note = " · текст автоматично стиснуто до ліміту 900" if rewrite_result.auto_compacted else ""
            self.set_status(
                (f"Рерайт створено запасною моделлю: {model_used}" if used_fallback
                 else f"Рерайт створено моделлю: {model_used}")
                + source_note + compact_note + memory_note
            )

        self.run_async(
            action,
            success,
            label=f"Рерайт через Ollama: один базовий текст із {group.source_count} джерел",
            done_label="Рерайт завершено: один текст для всіх платформ",
        )

    def _editor_values(self) -> tuple[str, str, str, dict[str, str]]:
        rewrite = self.text_widgets["rewrite"].get("1.0", "end").strip()
        return (
            self.headline_var.get().strip(),
            self.fact_card_text.get("1.0", "end").strip(),
            rewrite,
            self._platform_texts_from_rewrite(rewrite),
        )

    def _platform_texts_from_rewrite(self, rewrite: str) -> dict[str, str]:
        source_url = ""
        if self.current_group_id is not None:
            try:
                source_url = self.db.get_group(self.current_group_id).primary_url
            except KeyError:
                source_url = ""
        return platform_texts_from_base(
            rewrite,
            include_source_link=self.include_source_var.get(),
            source_url=source_url,
        )

    def _sync_platform_texts_from_rewrite(self) -> None:
        # FIX28 has no independent platform editors. The compatibility method is
        # deliberately a no-op so old integrations do not break.
        self.same_text_var.set(True)

    def _on_base_rewrite_modified(self, _event: object | None = None) -> None:
        widget = self.text_widgets["rewrite"]
        if not widget.edit_modified():
            return
        widget.edit_modified(False)
        self._on_base_rewrite_changed()

    def _on_base_rewrite_changed(self, _event: object | None = None) -> None:
        self.update_text_metrics()

    def _toggle_text_sync(self) -> None:
        self.same_text_var.set(True)
        self.update_text_metrics()

    def save_current(self) -> bool:
        if self.current_group_id is None:
            return False
        headline, fact_card, rewrite, platform_texts = self._editor_values()
        try:
            validate_editorial_text(rewrite)
        except TextLimitError as exc:
            self.msg.showwarning("Редактор", str(exc), parent=self.root)
            return False
        self.db.save_group_rewrite(
            self.current_group_id,
            headline=headline,
            fact_card=fact_card,
            rewrite_text=rewrite,
            platform_texts=platform_texts,
        )
        self.db.set_group_options(self.current_group_id, include_source_link=self.include_source_var.get())
        self.refresh_groups()
        self.update_text_metrics()
        self.set_status("Блок збережено: один текст для всіх платформ")
        return True

    def analyze_current(self) -> None:
        if self.current_group_id is None:
            return
        group = self.db.get_group(self.current_group_id)
        queries = extract_trend_queries(group)
        now = datetime.now(KYIV)
        since = now.replace(hour=0, minute=0, second=0, microsecond=0)

        def action() -> object:
            sample = ThreadsTrendSample(None, {}, "Threads-пошук вимкнений або профіль не підключено.")
            if self.config.threads_trend_search_enabled and self.config.platform_ready("threads"):
                sample = threads_keyword_sample(
                    self.config.threads_token,
                    queries,
                    since=since,
                    until=now,
                )
            score, confidence, details, recommendations = calculate_explosiveness(group, sample.count)
            details["threads_queries"] = sample.per_query
            details["threads_error"] = sample.error
            details["threads_query_candidates"] = queries
            return score, confidence, details, recommendations, sample

        def success(result: object) -> None:
            score, confidence, details, recommendations, sample = result  # type: ignore[misc]
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
            if sample.count is None:
                self.operation_detail_var.set(f"Оцінка готова, але Threads недоступний: {sample.error}")
            else:
                self.operation_detail_var.set(
                    f"Оцінка готова. Threads: {sample.count} унікальних дописів за {len(sample.per_query)} запитами."
                )

        query_label = ", ".join(f"«{item}»" for item in queries[:3]) or "без запиту"
        self.run_async(
            action,
            success,
            label=f"Оцінка вибуховості: Threads {query_label}",
            done_label="Оцінку вибуховості завершено",
        )

    def _display_analysis(self, group: NewsGroup) -> None:
        details = group.explosiveness_details
        if not group.explosiveness_score and not details:
            self.analysis_var.set("Вибуховість не розрахована")
            self.analysis_detail_var.set("Натисніть «Оцінити вибуховість».")
            return
        threads = details.get("threads_posts")
        rec = ", ".join(group.recommended_platforms) or "без автоматичної рекомендації"
        partial = " · оцінка часткова" if threads is None else ""
        self.analysis_var.set(
            f"Вибуховість: {group.explosiveness_score}/100 · надійність: "
            f"{group.explosiveness_confidence}% · джерел: {group.source_count}{partial} · рекомендовано: {rec}"
        )

        per_query = details.get("threads_queries")
        error = str(details.get("threads_error") or "").strip()
        candidates = details.get("threads_query_candidates")
        if isinstance(per_query, dict) and per_query:
            parts = [f"«{query}» — {count}" for query, count in per_query.items()]
            self.analysis_detail_var.set(
                f"Threads за сьогодні: {threads or 0} унікальних дописів. Запити: " + "; ".join(parts)
            )
        elif threads == 0:
            shown = ", ".join(f"«{item}»" for item in candidates) if isinstance(candidates, list) else ""
            self.analysis_detail_var.set(
                "Threads-пошук працює, але сьогодні не знайшов збігів" + (f" за запитами {shown}." if shown else ".")
            )
        elif threads is None:
            self.analysis_detail_var.set(f"Threads недоступний: {error or 'невідома помилка'}. Локальну оцінку все одно розраховано.")
        else:
            self.analysis_detail_var.set(f"Threads за сьогодні: {threads} унікальних дописів.")

    def apply_existing_targets(self, statuses: dict[str, str]) -> None:
        for variable in self.target_vars.values():
            variable.set(False)
        for platform in statuses:
            if platform in self.target_vars:
                self.target_vars[platform].set(True)
        self._update_selected_targets_summary()

    def apply_recommendations(self, recommendations: list[str]) -> None:
        for variable in self.target_vars.values():
            variable.set(False)
        for recommendation in recommendations:
            if recommendation == "facebook":
                for key in self.target_vars:
                    if key.startswith("facebook:") and self.config.platform_ready(key):
                        self.target_vars[key].set(True)
            elif recommendation in self.target_vars and self.config.platform_ready(recommendation):
                self.target_vars[recommendation].set(True)
        if not any(variable.get() for variable in self.target_vars.values()) and self.config.platform_ready("telegram"):
            self.target_vars["telegram"].set(True)
        self._update_selected_targets_summary()

    def verify_media(self) -> None:
        drive_url = self.media_url_var.get().strip()
        if not drive_url:
            self.msg.showwarning("Медіа", "Вставте посилання на файл Google Drive.", parent=self.root)
            return
        if not self.config.platform_ready("google_drive"):
            self.msg.showwarning(
                "Google Drive",
                "Спочатку підключіть Google Drive у налаштуваннях.",
                parent=self.root,
            )
            return
        try:
            file_id = extract_drive_file_id(drive_url)
        except Exception as exc:
            self._show_error(exc)
            return

        # Перевірка Drive має працювати і без відкритого блоку новини.
        # Інакше кнопка мовчки нічого не робила на окремій вкладці «Публікація».
        target_group_id = self.current_group_id
        self.media_status_var.set("Перевіряю файл у Google Drive…")

        def action() -> object:
            client = GoogleDriveClient(
                self.config.google_client_id,
                self.config.google_client_secret,
                self.config.google_refresh_token,
            )
            return client.inspect_media(file_id)

        def success(result: object) -> None:
            info = result
            if not info.can_delete:  # type: ignore[attr-defined]
                raise GoogleDriveError(
                    "Підключений Google-акаунт не може безповоротно видалити цей файл. "
                    "Завантажте файл зі свого підключеного акаунта або надайте йому право видалення."
                )

            if info.public_direct:  # type: ignore[attr-defined]
                threads_status = "Threads уже бачить пряме посилання."
            elif info.can_share:  # type: ignore[attr-defined]
                threads_status = (
                    "Для Threads програма сама тимчасово відкриє доступ до цього файла під час публікації."
                )
            else:
                threads_status = (
                    "Файл придатний для Telegram, Facebook і LinkedIn; для Threads цей акаунт не має права "
                    "тимчасово відкрити доступ."
                )
            base_status = (
                f"✓ Перевірено: {info.kind.upper()} · {info.name} · "  # type: ignore[attr-defined]
                f"{info.size / (1024 * 1024):.1f} МБ · {threads_status}"  # type: ignore[attr-defined]
            )
            if target_group_id is None:
                self.media_status_var.set(
                    base_status + " Відкрийте блок новини в редакторі, щоб прикріпити цей файл до публікації."
                )
                return

            self.db.set_group_media(
                target_group_id,
                drive_url=drive_url,
                file_id=info.file_id,  # type: ignore[attr-defined]
                name=info.name,  # type: ignore[attr-defined]
                kind=info.kind,  # type: ignore[attr-defined]
                mime=info.mime_type,  # type: ignore[attr-defined]
                size=info.size,  # type: ignore[attr-defined]
            )
            self.media_status_var.set(base_status + f" Прикріплено до блоку #{target_group_id}.")

        self.run_async(
            action,
            success,
            label="Google Drive: перевіряю медіафайл",
            done_label="Медіафайл перевірено",
        )

    def clear_media(self) -> None:
        if self.current_group_id is not None:
            self.db.clear_group_media(self.current_group_id)
        self.media_url_var.set("")
        self.media_status_var.set("Медіа не додано")

    def update_text_metrics(self) -> None:
        if self.current_group_id is None:
            return
        try:
            group = self.db.get_group(self.current_group_id)
        except KeyError:
            return
        _, _, rewrite, _platform_texts = self._editor_values()
        length = len(rewrite)
        suffix = " · ЗАВЕЛИКИЙ" if length > EDITORIAL_TEXT_LIMIT else ""
        self.metric_vars["rewrite"].set(f"{length} / {EDITORIAL_TEXT_LIMIT} символів{suffix}")

        finals = {
            platform: compose_publication_text(
                rewrite,
                platform,
                include_source_link=self.include_source_var.get(),
                source_url=group.primary_url,
            )
            for platform in ("facebook", "threads", "linkedin", "telegram")
        }
        threads_parts = metrics_for(finals["threads"], "threads").parts
        telegram_length = len(finals["telegram"])
        telegram_note = (
            f"Telegram: підпис {telegram_length}/{TELEGRAM_MEDIA_CAPTION_LIMIT}"
            if group.media_file_id
            else f"Telegram: текст {telegram_length} символів"
        )
        if group.media_file_id and telegram_length > TELEGRAM_MEDIA_CAPTION_LIMIT:
            telegram_note += " · завеликий для підпису"
        self.publication_preview_var.set(
            f"Facebook: 1 допис · LinkedIn: 1 допис · {telegram_note} · "
            f"Threads: {'1 допис' if threads_parts == 1 else f'ланцюжок із {threads_parts} частин'}"
        )

    def approve_current(self) -> None:
        if self.current_group_id is None or not self.save_current():
            return
        selected = [platform for platform, variable in self.target_vars.items() if variable.get()]
        if not selected:
            self.msg.showwarning("Черга", "Оберіть хоча б одну платформу.", parent=self.root)
            return
        group = self.db.get_group(self.current_group_id)
        headline, _fact_card, rewrite, _platform_texts = self._editor_values()
        targets: dict[str, str] = {}
        try:
            validate_editorial_text(rewrite)
            for target in selected:
                logical = "facebook" if target.startswith("facebook:") else target
                final = compose_publication_text(
                    rewrite,
                    logical,
                    include_source_link=group.include_source_link,
                    source_url=group.primary_url,
                )
                validate_media_message(final, logical, has_media=bool(group.media_file_id))
                targets[target] = final
        except TextLimitError as exc:
            self._show_error(exc)
            return
        if group.media_file_id and not self.config.platform_ready("google_drive"):
            self._show_error(GoogleDriveError("Google Drive не підключено, медіа неможливо завантажити."))
            return
        latest = parse_iso(self.db.latest_scheduled_at())
        now_kyiv = datetime.now(KYIV)
        slot = next_publish_slot(
            now=now_kyiv,
            latest_scheduled=latest,
            start_hour=self.config.publish_start_hour,
            end_hour=self.config.publish_end_hour,
            interval_minutes=self.config.publish_interval_minutes,
        )
        try:
            result = self.db.queue_targets(
                self.db.lead_article_id(group.id),
                slot.isoformat(timespec="seconds"),
                targets,
            )
        except Exception as exc:
            self._show_error(exc)
            return
        learned = self.db.record_editorial_example(
            group.id,
            final_text=rewrite,
            headline=headline,
            language=self.config.ui_language,
        )
        if self.config.learning_enabled:
            self.db.record_learning_event(
                "publication_approved", language=self.config.ui_language, group_id=group.id,
                payload={"batch_id": result.batch_id, "targets": sorted(targets), "example_added": learned},
            )
        if learned:
            self.editorial_memory_var.set(
                (f"Editorial memory: {self.db.editorial_example_count(language=self.config.ui_language)} approved examples"
                 if self.config.ui_language == "en"
                 else f"Редакційна пам’ять: {self.db.editorial_example_count(language=self.config.ui_language)} схвалених прикладів")
            )
        self.worker.wake()
        self.refresh_groups()
        self.refresh_queue()
        self.notebook.select(self.queue_tab)
        labels = target_labels(self.config)
        scheduled = (parse_iso(result.scheduled_at) or slot).astimezone(KYIV)
        details: list[str] = []
        if result.added:
            details.append("Додано: " + ", ".join(labels.get(item, item) for item in result.added))
        if result.removed:
            details.append("Прибрано з очікування: " + ", ".join(labels.get(item, item) for item in result.removed))
        if result.already_sent:
            details.append(
                "Уже опубліковано, дубль не створено: "
                + ", ".join(labels.get(item, item) for item in result.already_sent)
            )
        if result.status == "completed" and not result.added:
            lead = f"Пакет #{result.batch_id}: на вибраних платформах матеріал уже опубліковано."
        elif result.created:
            lead = f"Пакет #{result.batch_id} створено на {scheduled.strftime('%d.%m.%Y %H:%M')} за Києвом."
        else:
            lead = f"Пакет #{result.batch_id} оновлено. Час: {scheduled.strftime('%d.%m.%Y %H:%M')} за Києвом."
        self.msg.showinfo(
            "Черга",
            lead + (("\n\n" + "\n".join(details)) if details else "") + "\n\nВідкрито вкладку «Черга».",
            parent=self.root,
        )

    # Queue
    def _build_queue_tab(self) -> None:
        self.queue_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.queue_tab, text="Черга")
        buttons = ttk.Frame(self.queue_tab)
        buttons.pack(fill="x", pady=(0, 6))
        ttk.Label(buttons, text="Показати").pack(side="left")
        self.queue_filter = tk.StringVar(value="Активні")
        queue_filter_box = ttk.Combobox(
            buttons,
            textvariable=self.queue_filter,
            values=tuple(QUEUE_FILTERS),
            state="readonly",
            width=13,
        )
        queue_filter_box.pack(side="left", padx=(5, 8))
        queue_filter_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh_queue())
        ttk.Button(buttons, text="Оновити", command=self.refresh_queue).pack(side="left")
        ttk.Button(buttons, text="Відкрити й редагувати", command=self.open_selected_batch).pack(side="left", padx=6)
        ttk.Button(buttons, text="Повторити невідправлені", command=self.resume_selected_batch).pack(side="left", padx=(0, 6))
        ttk.Button(
            buttons,
            text="Перепланувати пропущені / призупинені",
            command=self.reschedule_interrupted_batches,
        ).pack(side="left", padx=(0, 6))
        ttk.Button(
            buttons,
            text="Скасувати / прибрати",
            command=self.cancel_selected_batches,
        ).pack(side="left")
        ttk.Button(buttons, text="Запустити один пакет зараз", command=self.run_worker_once).pack(side="right")

        self.queue_summary_var = tk.StringVar(value="Активна черга: завантаження…")
        ttk.Label(self.queue_tab, textvariable=self.queue_summary_var, font="TkHeadingFont").pack(
            fill="x", pady=(0, 3)
        )
        self.queue_alert_var = tk.StringVar(value="")
        ttk.Label(
            self.queue_tab,
            textvariable=self.queue_alert_var,
            foreground="#9a5b00",
            wraplength=1280,
        ).pack(fill="x", pady=(0, 5))

        ttk.Label(
            self.queue_tab,
            text="Вибір: Shift — діапазон, Ctrl — окремі пакети, Ctrl+A — усі видимі, Delete — прибрати.",
        ).pack(fill="x", pady=(0, 6))

        columns = ("batch", "block", "schedule", "status", "attempts", "targets", "cleanup")
        self.queue_tree = ttk.Treeview(self.queue_tab, columns=columns, show="headings", selectmode="extended")
        labels = {
            "batch": "Пакет",
            "block": "Новина",
            "schedule": "Час",
            "status": "Статус",
            "attempts": "Спроби",
            "targets": "Платформи",
            "cleanup": "Очищення Drive",
        }
        widths = {
            "batch": 75,
            "block": 320,
            "schedule": 170,
            "status": 110,
            "attempts": 70,
            "targets": 520,
            "cleanup": 240,
        }
        for column in columns:
            self.queue_tree.heading(column, text=labels[column])
            self.queue_tree.column(column, width=widths[column], anchor="w")
        self.queue_tree.pack(fill="both", expand=True)
        self.queue_tree.bind("<Button-1>", self._remember_queue_selection_anchor, add="+")
        self.queue_tree.bind("<Shift-Button-1>", self._select_queue_range)
        self.queue_tree.bind("<Double-1>", lambda _event: self.open_selected_batch())
        self.queue_tree.bind("<Delete>", self._delete_selected_queue_rows)
        self.queue_tree.bind("<Control-a>", self._select_all_queue_rows)
        self.queue_tree.bind("<Control-A>", self._select_all_queue_rows)


    def _remember_queue_selection_anchor(self, event: tk.Event) -> None:
        if int(getattr(event, "state", 0)) & 0x0005:
            return
        iid = self.queue_tree.identify_row(int(event.y))
        if iid:
            self._queue_selection_anchor = iid

    def _select_queue_range(self, event: tk.Event) -> str:
        target = self.queue_tree.identify_row(int(event.y))
        rows = tuple(self.queue_tree.get_children())
        if not target:
            return "break"
        anchor = self._queue_selection_anchor
        if anchor not in rows:
            focus = self.queue_tree.focus()
            selection = self.queue_tree.selection()
            anchor = focus if focus in rows else (selection[0] if selection else target)
        selected = self._tree_range(rows, anchor, target)
        if selected:
            self.queue_tree.selection_set(selected)
            self.queue_tree.focus(target)
            self.queue_tree.see(target)
            self._queue_selection_anchor = anchor
        return "break"

    def _selected_queue_batch_ids(self) -> list[int]:
        return [int(item) for item in self.queue_tree.selection()]

    def _selected_queue_batch_id(self) -> int | None:
        selection = self._selected_queue_batch_ids()
        return selection[0] if len(selection) == 1 else None

    def _require_single_queue_batch_id(self, action: str) -> int | None:
        selection = self._selected_queue_batch_ids()
        if not selection:
            self.msg.showinfo("Черга", "Оберіть пакет у списку.", parent=self.root)
            return None
        if len(selection) > 1:
            self.msg.showinfo(
                "Черга",
                f"Для дії «{action}» залиште вибраним один пакет. Зараз вибрано: {len(selection)}.",
                parent=self.root,
            )
            return None
        return selection[0]

    def _select_all_queue_rows(self, _event: object | None = None) -> str:
        rows = self.queue_tree.get_children()
        if rows:
            self.queue_tree.selection_set(rows)
            self.queue_tree.focus(rows[0])
        return "break"

    def _delete_selected_queue_rows(self, _event: object | None = None) -> str:
        self.cancel_selected_batches()
        return "break"

    def open_selected_batch(self) -> None:
        batch_id = self._require_single_queue_batch_id("Відкрити й редагувати")
        if batch_id is None:
            return
        try:
            group_id = self.db.group_id_for_batch(batch_id)
            self.load_group(group_id)
        except Exception as exc:
            self._show_error(exc)
            return
        self.notebook.select(self.publication_tab)
        self.set_status(
            f"Відкрито пакет #{batch_id}. Позначте потрібні платформи: невідправлені можна додати або прибрати."
        )

    def resume_selected_batch(self) -> None:
        batch_id = self._require_single_queue_batch_id("Повторити невідправлені")
        if batch_id is None:
            return
        try:
            batch = self.db.get_batch(batch_id)
            if batch.status == "in_progress":
                raise ValueError("Пакет уже публікується.")
            if batch.status in {"completed", "cancelled"}:
                raise ValueError("Оберіть активний або призупинений пакет.")
            if not self.msg.askyesno(
                "Повторна спроба",
                "Повторити лише невідправлені платформи?\n\n"
                "Уже успішні публікації не дублюватимуться. Перед повтором оновіть токен або права, якщо чергу було призупинено через помилку доступу.",
                parent=self.root,
            ):
                return
            self.db.resume_batch(batch_id)
            self.worker.wake()
        except Exception as exc:
            self._show_error(exc)
            return
        self.refresh_queue()
        self.msg.showinfo(
            "Черга",
            f"Пакет #{batch_id} відновлено. У роботу підуть лише невідправлені платформи.",
            parent=self.root,
        )

    def reschedule_interrupted_batches(self) -> None:
        now = datetime.now(KYIV)
        recoverable = []
        for batch in self.db.list_batches(limit=5000, statuses={"paused", "pending"}):
            parsed = parse_iso(batch.scheduled_at)
            if batch.status == "paused" or (
                batch.status == "pending"
                and parsed is not None
                and parsed.astimezone(KYIV) <= now
            ):
                recoverable.append(batch)
        recoverable.sort(
            key=lambda batch: ((parse_iso(batch.scheduled_at) or datetime.min.replace(tzinfo=KYIV)), batch.id)
        )
        if not recoverable:
            self.msg.showinfo(
                "Черга",
                "Призупинених або прострочених невідправлених пакетів немає.",
                parent=self.root,
            )
            return
        paused_count = sum(batch.status == "paused" for batch in recoverable)
        overdue_count = len(recoverable) - paused_count
        if not self.msg.askyesno(
            "Відновлення розкладу",
            f"Перепланувати {len(recoverable)} пакетів на найближчі вільні слоти?\n\n"
            f"Призупинено: {paused_count}. Прострочено в очікуванні: {overdue_count}.\n\n"
            "Уже опубліковані платформи не дублюються. Невідправлені цілі буде очищено від старих помилок "
            "і розставлено послідовно за поточним інтервалом. Спочатку оновіть і перевірте токени.",
            parent=self.root,
        ):
            return
        recovery_ids = {batch.id for batch in recoverable}
        active_future = []
        for batch in self.db.list_batches(limit=5000, statuses={"pending", "in_progress"}):
            if batch.id in recovery_ids:
                continue
            parsed = parse_iso(batch.scheduled_at)
            if parsed is not None and parsed.astimezone(KYIV) > now:
                active_future.append(parsed.astimezone(KYIV))
        latest = max(active_future) if active_future else None
        schedules: dict[int, str] = {}
        for batch in recoverable:
            slot = next_publish_slot(
                now=now,
                latest_scheduled=latest,
                start_hour=self.config.publish_start_hour,
                end_hour=self.config.publish_end_hour,
                interval_minutes=self.config.publish_interval_minutes,
            )
            schedules[batch.id] = slot.isoformat(timespec="seconds")
            latest = slot
        try:
            resumed = self.db.reschedule_recoverable_batches(schedules)
            if hasattr(self, "worker"):
                self.worker.wake()
        except Exception as exc:
            self._show_error(exc)
            return
        self.refresh_queue()
        first = parse_iso(schedules[resumed[0]]).astimezone(KYIV) if resumed else None
        last = parse_iso(schedules[resumed[-1]]).astimezone(KYIV) if resumed else None
        range_text = (
            f" Перший слот: {first.strftime('%d.%m.%Y %H:%M')}, останній: {last.strftime('%d.%m.%Y %H:%M')} за Києвом."
            if first is not None and last is not None
            else ""
        )
        self.msg.showinfo(
            "Черга",
            f"Переплановано пакетів: {len(resumed)}.{range_text}",
            parent=self.root,
        )

    def reschedule_all_paused_batches(self) -> None:
        """Compatibility entry point retained for older probes."""
        self.reschedule_interrupted_batches()

    def cancel_selected_batch(self) -> None:
        """Backward-compatible single-button entry point."""
        self.cancel_selected_batches()

    def cancel_selected_batches(self) -> None:
        batch_ids = self._selected_queue_batch_ids()
        if not batch_ids:
            self.msg.showinfo("Черга", "Оберіть один або кілька пакетів у списку.", parent=self.root)
            return

        if len(batch_ids) == 1:
            title = "Скасування пакета"
            question = (
                f"Скасувати пакет #{batch_ids[0]} і прибрати його з активної черги?\n\n"
                "Уже опубліковані дописи не видаляються. Сам блок новини залишиться доступним для повторного налаштування."
            )
        else:
            title = "Скасування вибраних пакетів"
            shown = ", ".join(f"#{item}" for item in batch_ids[:12])
            if len(batch_ids) > 12:
                shown += f" та ще {len(batch_ids) - 12}"
            question = (
                f"Скасувати {len(batch_ids)} вибраних пакетів і прибрати їх з активної черги?\n\n"
                f"Пакети: {shown}.\n\n"
                "Операція виконується цілісно: якщо хоча б один пакет зараз публікується або вже завершений, жоден із вибраних пакетів не буде скасовано. "
                "Уже опубліковані дописи не видаляються."
            )
        if not self.msg.askyesno(title, question, parent=self.root):
            return

        try:
            cancelled = self.db.cancel_batches(batch_ids)
        except Exception as exc:
            self._show_error(exc)
            return
        self.refresh_queue()
        self.refresh_groups()
        if not cancelled:
            result_text = "Усі вибрані пакети вже були скасовані."
        elif len(cancelled) == 1:
            result_text = f"Пакет #{cancelled[0]} скасовано й прибрано з активної черги."
        else:
            result_text = f"Скасовано й прибрано з активної черги: {len(cancelled)} пакетів."
        self.msg.showinfo("Черга", result_text, parent=self.root)

    def _schedule_queue_refresh(self) -> None:
        if self.stop_event.is_set():
            return
        if self.queue_refresh_after_id is not None:
            try:
                self.root.after_cancel(self.queue_refresh_after_id)
            except tk.TclError:
                pass
        self.queue_refresh_after_id = self.root.after(5000, self._periodic_queue_refresh)

    def _periodic_queue_refresh(self) -> None:
        self.queue_refresh_after_id = None
        if self.stop_event.is_set():
            return
        try:
            self.refresh_queue()
        finally:
            self._schedule_queue_refresh()

    def refresh_queue(self) -> None:
        self._queue_selection_anchor = None
        self.queue_tree.delete(*self.queue_tree.get_children())
        labels = target_labels(self.config)
        statuses = QUEUE_FILTERS.get(self.queue_filter.get())
        now_kyiv = datetime.now(KYIV)
        for batch in self.db.list_batches(statuses=statuses):
            try:
                group_id = self.db.group_id_for_batch(batch.id)
                group = self.db.get_group(group_id)
                block_label = f"#{group.id} · {group.canonical_title}"
            except (KeyError, ValueError):
                block_label = "Блок недоступний"
            target_parts: list[str] = []
            for item in batch.targets:
                target_text = f"{labels.get(item.platform, item.platform)}: {TARGET_STATUS_LABELS.get(item.status, item.status)}"
                if item.status == "failed" and item.last_error:
                    clean_error = " ".join(str(item.last_error).split())
                    if len(clean_error) > 180:
                        clean_error = clean_error[:177] + "…"
                    target_text += f" — {clean_error}"
                target_parts.append(target_text)
            targets = ", ".join(target_parts)
            schedule_text, schedule_local = _format_kyiv_schedule(batch.scheduled_at)
            status_text = BATCH_STATUS_LABELS.get(batch.status, batch.status)
            if batch.status == "pending" and schedule_local is not None and schedule_local <= now_kyiv:
                status_text = f"прострочено на {_format_overdue(now_kyiv - schedule_local)}"
            self.queue_tree.insert(
                "",
                "end",
                iid=str(batch.id),
                values=(
                    batch.id,
                    block_label,
                    schedule_text + " (Київ)",
                    status_text,
                    batch.attempts,
                    targets,
                    batch.cleanup_error or "—",
                ),
            )
        self._update_queue_summary()

    def _update_queue_summary(self) -> None:
        if not hasattr(self, "queue_summary_var"):
            return
        batches = self.db.list_batches(limit=5000, statuses={"pending", "in_progress", "paused"})
        now = datetime.now(KYIV)
        pending = sum(batch.status == "pending" for batch in batches)
        publishing = sum(batch.status == "in_progress" for batch in batches)
        paused = sum(batch.status == "paused" for batch in batches)
        overdue = 0
        for batch in batches:
            if batch.status != "pending":
                continue
            parsed = parse_iso(batch.scheduled_at)
            if parsed is not None and parsed.astimezone(KYIV) <= now:
                overdue += 1
        self.queue_summary_var.set(
            f"Активна черга: очікує {pending} · прострочено {overdue} · публікується {publishing} · призупинено {paused}"
        )
        if paused and hasattr(self, "queue_alert_var") and not self.queue_alert_var.get().strip():
            self.queue_alert_var.set(
                "Є призупинені пакети. Перевірте помилки платформ, оновіть токени, потім натисніть «Перепланувати всі призупинені»."
            )

    def _show_worker_result(self, value: object) -> None:
        self.refresh_queue()
        self.refresh_history()
        if not isinstance(value, WorkerResult):
            return
        if value.busy:
            self.msg.showinfo(
                "Черга",
                "Інша публікація вже виконується. Програма не запускає паралельний пакет; дочекайтеся завершення поточної платформи.",
                parent=self.root,
            )
            return
        if not value.claimed:
            self.msg.showinfo(
                "Черга",
                "Немає пакета, час публікації якого вже настав.",
                parent=self.root,
            )
            return
        labels = target_labels(self.config)
        lines = [f"Пакет #{value.batch_id} оброблено."]
        if value.sent_platforms:
            lines.append(
                "Опубліковано зараз: "
                + ", ".join(labels.get(item, item) for item in value.sent_platforms)
            )
        if value.failed_platforms:
            lines.append("Не опубліковано:")
            for platform, error in value.failed_platforms.items():
                lines.append(f"• {labels.get(platform, platform)}: {error}")
            lines.append("Успішні публікації не дублюватимуться.")
            if value.paused:
                lines.append(
                    "Автоматичні повтори призупинено, щоб не робити десятки однакових запитів. "
                    "Оновіть токен/права й натисніть «Повторити невідправлені»."
                )
                if value.pause_reason:
                    lines.append(value.pause_reason)
            else:
                lines.append("Невідправлені цілі залишено для наступної контрольованої спроби.")
        elif value.completed:
            lines.append("Усі вибрані платформи опубліковано успішно.")
        else:
            lines.append("Пакет залишився активним, зокрема для завершення очищення Google Drive.")
        self.msg.showwarning(
            "Часткова публікація" if value.failed_platforms else "Результат публікації",
            "\n\n".join(lines),
            parent=self.root,
        ) if value.failed_platforms else self.msg.showinfo(
            "Результат публікації",
            "\n\n".join(lines),
            parent=self.root,
        )

    def run_worker_once(self) -> None:
        self.run_async(
            self.worker.run_once,
            self._show_worker_result,
            label="Черга: виконую одну публікацію",
            done_label="Перевірку черги завершено",
        )

    # Settings
    def _build_history_tab(self) -> None:
        self.history_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.history_tab, text="Історія публікацій")

        actions = ttk.Frame(self.history_tab)
        actions.pack(fill="x", pady=(0, 6))
        ttk.Button(actions, text="Оновити", command=self.refresh_history).pack(side="left")
        ttk.Button(
            actions, text="Оновити статистику вибраної",
            command=self.refresh_selected_history_metrics,
        ).pack(side="left", padx=6)
        ttk.Button(actions, text="Відкрити допис", command=self.open_history_post).pack(side="left")
        self.history_summary_var = tk.StringVar(value="Опубліковані матеріали: завантаження…")
        ttk.Label(actions, textvariable=self.history_summary_var, foreground="#555").pack(side="right")

        pane = ttk.Panedwindow(self.history_tab, orient="vertical")
        pane.pack(fill="both", expand=True)
        top = ttk.Frame(pane)
        bottom = ttk.Frame(pane)
        pane.add(top, weight=3)
        pane.add(bottom, weight=2)

        columns = ("batch", "headline", "published", "networks", "status", "views", "likes", "shares", "comments", "checked")
        self.history_tree = ttk.Treeview(top, columns=columns, show="headings", selectmode="browse")
        headings = {
            "batch": "Пакет", "headline": "Рерайчений заголовок", "published": "Дата і час",
            "networks": "Мережі", "status": "Статус", "views": "Перегляди",
            "likes": "Реакції", "shares": "Репости", "comments": "Коментарі",
            "checked": "Статистику оновлено",
        }
        widths = {
            "batch": 65, "headline": 430, "published": 155, "networks": 260,
            "status": 110, "views": 90, "likes": 80, "shares": 80,
            "comments": 90, "checked": 165,
        }
        for column in columns:
            self.history_tree.heading(column, text=headings[column])
            self.history_tree.column(column, width=widths[column], anchor="w")
        scroll = ttk.Scrollbar(top, orient="vertical", command=self.history_tree.yview)
        self.history_tree.configure(yscrollcommand=scroll.set)
        self.history_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.history_tree.bind("<<TreeviewSelect>>", lambda _event: self.show_history_details())
        self.history_tree.bind("<Double-1>", lambda _event: self.open_history_post())

        ttk.Label(bottom, text="Текст і дані по мережах").pack(anchor="w", pady=(6, 2))
        self.history_details = ScrolledText(bottom, wrap="word", height=12)
        self.history_details.pack(fill="both", expand=True)
        self.history_details.configure(state="disabled")
        self.history_rows: dict[int, dict[str, object]] = {}

    @staticmethod
    def _history_metrics(targets: list[dict[str, object]]) -> tuple[dict[str, int], str, bool]:
        totals = {"views": 0, "likes": 0, "shares": 0, "comments": 0}
        checked = ""
        has_metrics = False
        for target in targets:
            progress = target.get("progress")
            if not isinstance(progress, dict):
                continue
            metrics = progress.get("metrics")
            if isinstance(metrics, dict) and metrics:
                has_metrics = True
                totals["views"] += int(metrics.get("views") or 0)
                totals["likes"] += int(metrics.get("likes") or metrics.get("reactions") or 0)
                totals["shares"] += int(metrics.get("shares") or metrics.get("reposts") or metrics.get("quotes") or 0)
                totals["comments"] += int(metrics.get("comments") or metrics.get("replies") or 0)
            checked = max(checked, str(progress.get("metrics_checked_at") or ""))
        return totals, checked, has_metrics

    def refresh_history(self) -> None:
        if not hasattr(self, "history_tree"):
            return
        selected = self.history_tree.selection()
        self.history_tree.delete(*self.history_tree.get_children())
        rows = self.db.list_publication_history(limit=1000)
        self.history_rows = {int(row["batch_id"]): row for row in rows}
        labels = target_labels(self.config)
        for row in rows:
            batch_id = int(row["batch_id"])
            targets = row.get("targets")
            target_rows = targets if isinstance(targets, list) else []
            sent = [target for target in target_rows if str(target.get("status")) == "sent"]
            networks = ", ".join(labels.get(str(target.get("platform")), str(target.get("platform"))) for target in sent)
            metrics, checked, has_metrics = self._history_metrics(target_rows)
            published_raw = str(row.get("published_at") or row.get("scheduled_at") or "")
            published, _parsed = _format_kyiv_schedule(published_raw)
            checked_text, _checked_parsed = _format_kyiv_schedule(checked) if checked else ("—", None)
            statuses = {str(target.get("status")) for target in target_rows}
            status_text = "опубліковано" if statuses == {"sent"} else "частково опубліковано"
            self.history_tree.insert(
                "", "end", iid=str(batch_id),
                values=(
                    batch_id, str(row.get("headline") or ""), published, networks or "—",
                    tr(status_text, self.config.ui_language),
                    metrics["views"] if has_metrics else "—",
                    metrics["likes"] if has_metrics else "—",
                    metrics["shares"] if has_metrics else "—",
                    metrics["comments"] if has_metrics else "—", checked_text,
                ),
            )
        self.history_summary_var.set(
            (f"Published items: {len(rows)}" if self.config.ui_language == "en" else f"Опубліковані матеріали: {len(rows)}")
        )
        if selected and self.history_tree.exists(selected[0]):
            self.history_tree.selection_set(selected[0])
        elif rows:
            first = str(rows[0]["batch_id"])
            self.history_tree.selection_set(first)
            self.history_tree.focus(first)
        self.show_history_details()

    def _selected_history_row(self) -> dict[str, object] | None:
        selected = self.history_tree.selection() if hasattr(self, "history_tree") else ()
        return self.history_rows.get(int(selected[0])) if selected else None

    def show_history_details(self) -> None:
        if not hasattr(self, "history_details"):
            return
        row = self._selected_history_row()
        lines: list[str] = []
        if row:
            lines.extend([str(row.get("headline") or ""), "", str(row.get("rewrite_text") or ""), "", "МЕРЕЖІ:"])
            labels = target_labels(self.config)
            targets = row.get("targets")
            for target in targets if isinstance(targets, list) else []:
                progress = target.get("progress") if isinstance(target.get("progress"), dict) else {}
                metrics = progress.get("metrics") if isinstance(progress.get("metrics"), dict) else {}
                parts = [
                    labels.get(str(target.get("platform")), str(target.get("platform"))),
                    TARGET_STATUS_LABELS.get(str(target.get("status")), str(target.get("status"))),
                ]
                if metrics:
                    parts.append(
                        "перегляди {views}; реакції {likes}; репости {shares}; коментарі {comments}".format(
                            views=int(metrics.get("views") or 0),
                            likes=int(metrics.get("likes") or metrics.get("reactions") or 0),
                            shares=int(metrics.get("shares") or metrics.get("reposts") or metrics.get("quotes") or 0),
                            comments=int(metrics.get("comments") or metrics.get("replies") or 0),
                        )
                    )
                error = str(progress.get("metrics_error") or "")
                note = str(progress.get("metrics_note") or "")
                if error:
                    parts.append("помилка статистики: " + error)
                if note:
                    parts.append(note)
                lines.append(" • " + " | ".join(parts))
        self.history_details.configure(state="normal")
        self.history_details.delete("1.0", "end")
        self.history_details.insert("1.0", "\n".join(lines))
        self.history_details.configure(state="disabled")

    def refresh_selected_history_metrics(self) -> None:
        row = self._selected_history_row()
        if not row:
            self.msg.showinfo("Історія публікацій", "Оберіть опублікований матеріал.", parent=self.root)
            return
        targets = row.get("targets")
        target_rows = targets if isinstance(targets, list) else []
        sent_targets = [target for target in target_rows if str(target.get("status")) == "sent"]

        def work() -> int:
            updated = 0
            for target in sent_targets:
                result = collect_publication_metrics(
                    self.config, str(target.get("platform") or ""),
                    str(target.get("remote_id") or ""),
                    target.get("progress") if isinstance(target.get("progress"), dict) else {},
                )
                self.db.save_publication_metrics(
                    int(target["id"]), metrics=result.metrics, error=result.error,
                    note=result.note, permalink_url=result.permalink_url,
                )
                updated += 1
            return updated

        self.run_async(
            work, lambda _value: self.refresh_history(),
            label="Оновлюю статистику публікації", done_label="Статистику публікації оновлено",
        )

    def open_history_post(self) -> None:
        row = self._selected_history_row()
        if not row:
            return
        targets = row.get("targets")
        urls: list[str] = []
        for target in targets if isinstance(targets, list) else []:
            progress = target.get("progress")
            if isinstance(progress, dict) and progress.get("permalink_url"):
                urls.append(str(progress["permalink_url"]))
        if not urls:
            self.msg.showinfo(
                "Історія публікацій",
                "Посилання ще не отримано. Оновіть статистику вибраної публікації.",
                parent=self.root,
            )
            return
        webbrowser.open(urls[0])

    def _build_settings_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text="Налаштування")

        sticky = ttk.Frame(tab, padding=(4, 2, 4, 8))
        sticky.pack(fill="x")
        self.settings_dirty_var = tk.StringVar(value="Усі зміни збережено")
        self.storage_status_var = tk.StringVar(
            value=(
                f"Портативні дані: {data_dir()}"
                if portable_mode()
                else f"Локальні дані: {data_dir()}"
            )
        )
        self.ui_font_size_var = tk.StringVar(value=str(self.config.ui_font_size))
        self.ui_language_var = tk.StringVar(value=language_label(self.config.ui_language))
        self.settings_language_status_var = tk.StringVar()

        font_controls = ttk.Frame(sticky)
        font_controls.grid(row=0, column=0, sticky="w")
        ttk.Label(font_controls, text="Розмір шрифту:").pack(side="left")
        ttk.Button(font_controls, text="A−", width=4, command=lambda: self.change_font_size(-1)).pack(side="left", padx=(6, 2))
        self.ui_font_size_combo = ttk.Combobox(
            font_controls,
            textvariable=self.ui_font_size_var,
            values=("9", "10", "11", "12", "13", "14", "16", "18", "20", "22", "24"),
            state="readonly",
            width=5,
        )
        self.ui_font_size_combo.pack(side="left", padx=2)
        self.ui_font_size_combo.bind("<<ComboboxSelected>>", self.preview_font_size)
        ttk.Button(font_controls, text="A+", width=4, command=lambda: self.change_font_size(1)).pack(side="left", padx=(2, 10))
        ttk.Label(font_controls, text="Мова програми").pack(side="left", padx=(12, 4))
        self.ui_language_combo = ttk.Combobox(
            font_controls, textvariable=self.ui_language_var,
            values=tuple(LANGUAGE_LABELS.values()), state="readonly", width=12,
        )
        self.ui_language_combo.pack(side="left", padx=(0, 6))
        self.ui_language_combo.bind("<<ComboboxSelected>>", self.preview_language)
        ttk.Label(font_controls, textvariable=self.settings_language_status_var, foreground="#555").pack(side="left")

        ttk.Label(sticky, textvariable=self.settings_dirty_var, foreground="#555").grid(
            row=0, column=1, sticky="w", padx=10
        )
        self.settings_save_button = ttk.Button(
            sticky,
            text="ЗБЕРЕГТИ ЗМІНИ",
            command=self.save_settings,
        )
        self.settings_save_button.grid(row=0, column=2, sticky="e")
        ttk.Label(
            sticky,
            textvariable=self.storage_status_var,
            foreground="#555",
            anchor="w",
        ).grid(row=1, column=0, columnspan=3, sticky="ew", pady=(5, 0))
        sticky.columnconfigure(1, weight=1)

        body = ttk.Frame(tab)
        body.pack(fill="both", expand=True)
        canvas = tk.Canvas(body, highlightthickness=0)
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=canvas.yview)
        form = ttk.Frame(canvas, padding=(4, 2, 12, 12))
        form.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        form_window = canvas.create_window((0, 0), window=form, anchor="nw")
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(form_window, width=max(1, event.width)),
        )
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.settings_vars: dict[str, tk.StringVar] = {}
        self.ollama_status_var = tk.StringVar(value="Натисніть «Знайти моделі».")
        self.meta_status_var = tk.StringVar(value=self._meta_status_text())
        self.threads_status_var = tk.StringVar(value=self._threads_status_text())
        self.threads_search_status_var = tk.StringVar(value="Пошук трендів Threads: не перевірено.")
        self.linkedin_status_var = tk.StringVar(value=self._linkedin_status_text())
        self.telegram_status_var = tk.StringVar(value=self._telegram_status_text())
        self.google_status_var = tk.StringVar(value=self._google_status_text())
        self.connection_diagnostics_status_var = tk.StringVar(
            value="Автоматична перевірка підключень запуститься після відкриття програми."
        )

        ai = ttk.LabelFrame(form, text="1. Ollama і моделі", padding=10)
        ai.pack(fill="x", pady=(0, 8))
        ttk.Button(ai, text="Знайти моделі", command=self.scan_ollama_models).grid(row=0, column=0, sticky="w")
        ttk.Label(ai, textvariable=self.ollama_status_var, foreground="#555").grid(row=0, column=1, columnspan=2, sticky="w", padx=10)
        ttk.Label(ai, text="Основна модель").grid(row=1, column=0, sticky="w", pady=(10, 2))
        self.ollama_model_var = tk.StringVar(value=self.config.ollama_model)
        self.ollama_model_combo = ttk.Combobox(ai, textvariable=self.ollama_model_var, state="readonly", width=42)
        self.ollama_model_combo.grid(row=2, column=0, columnspan=2, sticky="ew", padx=(0, 10))
        ttk.Label(ai, text="Запасна модель").grid(row=1, column=2, sticky="w", pady=(10, 2))
        self.ollama_fallback_var = tk.StringVar(value=self.config.ollama_fallback_model or "Без запасної моделі")
        self.ollama_fallback_combo = ttk.Combobox(ai, textvariable=self.ollama_fallback_var, state="readonly", width=42)
        self.ollama_fallback_combo.grid(row=2, column=2, sticky="ew")
        ai.columnconfigure(1, weight=1)
        ai.columnconfigure(2, weight=1)

        platforms = ttk.LabelFrame(form, text="2. Платформи й Google Drive", padding=8)
        platforms.pack(fill="x", pady=(0, 8))

        diagnostics = ttk.LabelFrame(platforms, text="Автоматична діагностика токенів і прав", padding=8)
        diagnostics.pack(fill="x", pady=4)
        diagnostics_top = ttk.Frame(diagnostics)
        diagnostics_top.pack(fill="x")
        ttk.Label(
            diagnostics_top,
            textvariable=self.connection_diagnostics_status_var,
            foreground="#555",
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        self.connection_diagnostics_button = ttk.Button(
            diagnostics_top,
            text="Перевірити всі підключення зараз",
            command=lambda: self.run_connection_diagnostics(automatic=False),
        )
        self.connection_diagnostics_button.grid(row=1, column=0, sticky="w", pady=(6, 0))
        diagnostics_top.columnconfigure(0, weight=1)
        diagnostics_table = ttk.Frame(diagnostics)
        diagnostics_table.pack(fill="x", expand=True, pady=(6, 0))
        self.connection_diagnostics_tree = ttk.Treeview(
            diagnostics_table,
            columns=("platform", "status", "detail"),
            show="headings",
            height=5,
        )
        self.connection_diagnostics_tree.heading("platform", text="Платформа")
        self.connection_diagnostics_tree.heading("status", text="Стан")
        self.connection_diagnostics_tree.heading("detail", text="Що перевірено / що зробити")
        self.connection_diagnostics_tree.column("platform", width=130, anchor="w")
        self.connection_diagnostics_tree.column("status", width=170, anchor="w")
        self.connection_diagnostics_tree.column("detail", width=760, anchor="w")
        diagnostics_scroll = ttk.Scrollbar(
            diagnostics_table,
            orient="vertical",
            command=self.connection_diagnostics_tree.yview,
        )
        self.connection_diagnostics_tree.configure(yscrollcommand=diagnostics_scroll.set)
        self.connection_diagnostics_tree.pack(side="left", fill="x", expand=True)
        diagnostics_scroll.pack(side="right", fill="y")
        ttk.Label(
            diagnostics,
            text=(
                "Перевірка виконується автоматично після запуску та кожні 6 годин. "
                "Збій мережі не оголошується простроченим токеном. Для Telegram окремо перевіряються "
                "права адміністратора і can_post_messages."
            ),
            foreground="#666",
            wraplength=1050,
        ).pack(fill="x", pady=(5, 0))

        facebook_app = ttk.LabelFrame(platforms, text="Facebook застосунок", padding=8)
        facebook_app.pack(fill="x", pady=4)
        self.settings_vars["facebook_app_id"] = tk.StringVar(value=self.config.facebook_app_id)
        self.settings_vars["facebook_app_secret"] = tk.StringVar(value=self.config.facebook_app_secret)
        ttk.Label(facebook_app, text="Facebook App ID").grid(row=0, column=0, sticky="w")
        ttk.Entry(facebook_app, textvariable=self.settings_vars["facebook_app_id"], width=32).grid(
            row=1, column=0, sticky="ew", padx=(0, 8)
        )
        ttk.Label(facebook_app, text="Facebook App Secret").grid(row=0, column=1, sticky="w")
        ttk.Entry(
            facebook_app, textvariable=self.settings_vars["facebook_app_secret"], show="•", width=48
        ).grid(row=1, column=1, sticky="ew")
        ttk.Button(
            facebook_app, text="Відкрити налаштування застосунку",
            command=lambda: webbrowser.open("https://developers.facebook.com/apps/", new=2),
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        facebook_app.columnconfigure(0, weight=1)
        facebook_app.columnconfigure(1, weight=1)

        threads_app = ttk.LabelFrame(platforms, text="Threads застосунок", padding=8)
        threads_app.pack(fill="x", pady=4)
        self.settings_vars["threads_app_id"] = tk.StringVar(value=self.config.threads_app_id)
        self.settings_vars["threads_app_secret"] = tk.StringVar(value=self.config.threads_app_secret)
        ttk.Label(threads_app, text="Threads App ID").grid(row=0, column=0, sticky="w")
        ttk.Entry(threads_app, textvariable=self.settings_vars["threads_app_id"], width=32).grid(
            row=1, column=0, sticky="ew", padx=(0, 8)
        )
        ttk.Label(threads_app, text="Threads App Secret").grid(row=0, column=1, sticky="w")
        ttk.Entry(
            threads_app, textvariable=self.settings_vars["threads_app_secret"], show="•", width=48
        ).grid(row=1, column=1, sticky="ew")
        ttk.Button(
            threads_app, text="Відкрити налаштування застосунку",
            command=lambda: webbrowser.open("https://developers.facebook.com/apps/", new=2),
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        threads_app.columnconfigure(0, weight=1)
        threads_app.columnconfigure(1, weight=1)

        meta = ttk.LabelFrame(platforms, text="Facebook Pages", padding=8)
        meta.pack(fill="x", pady=4)
        self.settings_vars["meta_user_access_token"] = tk.StringVar(value=self.config.meta_user_access_token)
        ttk.Label(meta, text="Facebook User Access Token").grid(row=0, column=0, sticky="w")
        ttk.Entry(meta, textvariable=self.settings_vars["meta_user_access_token"], show="•", width=72).grid(
            row=1, column=0, columnspan=2, sticky="ew"
        )
        meta_actions = ttk.Frame(meta)
        meta_actions.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Button(
            meta_actions,
            text="Відкрити Graph API Explorer",
            command=lambda: webbrowser.open("https://developers.facebook.com/tools/explorer/", new=2),
        ).pack(side="left")
        ttk.Button(meta_actions, text="Знайти сторінки", command=self.connect_meta).pack(side="left", padx=(6, 0))
        ttk.Label(meta, textvariable=self.meta_status_var, foreground="#555").grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(5, 2)
        )
        ttk.Label(
            meta,
            text=(
                "Усі знайдені сторінки автоматично стають доступними в редакторі. Якщо вказані App ID і App Secret, "
                "короткий токен з Graph API Explorer спочатку буде обміняно на довготривалий."
            ),
            foreground="#666",
        ).grid(row=4, column=0, columnspan=2, sticky="ew", pady=(3, 4))
        self.meta_pages_tree = ttk.Treeview(meta, columns=("name", "id"), show="headings", height=5)
        self.meta_pages_tree.heading("name", text="Сторінка")
        self.meta_pages_tree.heading("id", text="ID")
        self.meta_pages_tree.column("name", width=420, anchor="w")
        self.meta_pages_tree.column("id", width=230, anchor="w")
        meta_pages_scroll = ttk.Scrollbar(meta, orient="vertical", command=self.meta_pages_tree.yview)
        self.meta_pages_tree.configure(yscrollcommand=meta_pages_scroll.set)
        self.meta_pages_tree.grid(row=5, column=0, columnspan=2, sticky="ew")
        meta_pages_scroll.grid(row=5, column=2, sticky="ns")
        meta.columnconfigure(0, weight=1)
        self.meta_pages = [
            MetaPage(str(row.get("id", "")), str(row.get("name", "")), str(row.get("access_token", "")))
            for row in configured_facebook_pages(self.config)
        ]
        self._refresh_meta_pages_view()

        threads = ttk.LabelFrame(platforms, text="Threads", padding=8)
        threads.pack(fill="x", pady=4)
        self.settings_vars["threads_token"] = tk.StringVar(value=self.config.threads_token)
        ttk.Label(threads, text="Threads access token").grid(row=0, column=0, sticky="w")
        ttk.Entry(threads, textvariable=self.settings_vars["threads_token"], show="•", width=70).grid(
            row=1, column=0, sticky="ew"
        )
        threads_actions = ttk.Frame(threads)
        threads_actions.grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Button(threads_actions, text="Визначити профіль", command=self.connect_threads).pack(side="left")
        self.threads_trend_button = ttk.Button(
            threads_actions,
            text="Перевірити пошук трендів",
            command=self.check_threads_trends,
        )
        self.threads_trend_button.pack(side="left", padx=(6, 0))
        ttk.Button(
            threads_actions,
            text="Meta for Developers",
            command=lambda: webbrowser.open("https://developers.facebook.com/apps/", new=2),
        ).pack(side="left", padx=(6, 0))
        ttk.Label(threads, textvariable=self.threads_status_var, foreground="#555").grid(
            row=3, column=0, sticky="ew", pady=(5, 0)
        )
        ttk.Label(threads, textvariable=self.threads_search_status_var, foreground="#555").grid(
            row=4, column=0, sticky="ew", pady=(3, 0)
        )
        ttk.Label(
            threads,
            text=(
                "Результат з’явиться тут і в окремому вікні. Очікування відповіді — до 12 секунд. "
                "За наявності App Secret короткий токен автоматично обмінюється на довготривалий; чинний довготривалий токен програма оновлює до завершення строку."
            ),
            foreground="#666",
            wraplength=1050,
        ).grid(row=5, column=0, sticky="ew", pady=(3, 0))
        threads.columnconfigure(0, weight=1)

        linkedin = ttk.LabelFrame(platforms, text="LinkedIn", padding=8)
        linkedin.pack(fill="x", pady=4)
        self.settings_vars["linkedin_token"] = tk.StringVar(value=self.config.linkedin_token)
        ttk.Label(linkedin, text="LinkedIn Access Token").grid(row=0, column=0, sticky="w")
        ttk.Entry(linkedin, textvariable=self.settings_vars["linkedin_token"], show="•", width=70).grid(
            row=1, column=0, sticky="ew"
        )
        linkedin_actions = ttk.Frame(linkedin)
        linkedin_actions.grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Button(
            linkedin_actions,
            text="Відкрити Token Generator",
            command=lambda: webbrowser.open("https://www.linkedin.com/developers/tools/oauth/token-generator", new=2),
        ).pack(side="left")
        ttk.Button(linkedin_actions, text="Перевірити токен", command=self.connect_linkedin).pack(side="left", padx=(6, 0))
        ttk.Label(linkedin, textvariable=self.linkedin_status_var, foreground="#555").grid(
            row=3, column=0, sticky="ew", pady=(5, 2)
        )
        linkedin.columnconfigure(0, weight=1)

        telegram = ttk.LabelFrame(platforms, text="Telegram", padding=8)
        telegram.pack(fill="x", pady=4)
        self.settings_vars["telegram_bot_token"] = tk.StringVar(value=self.config.telegram_bot_token)
        self.settings_vars["telegram_chat_id"] = tk.StringVar(value=self.config.telegram_chat_id)
        ttk.Label(telegram, text="Bot token").grid(row=0, column=0, sticky="w")
        ttk.Entry(telegram, textvariable=self.settings_vars["telegram_bot_token"], show="•", width=48).grid(
            row=1, column=0, sticky="ew", padx=(0, 8)
        )
        ttk.Label(telegram, text="Канал, наприклад @uafree_org").grid(row=0, column=1, sticky="w")
        ttk.Entry(telegram, textvariable=self.settings_vars["telegram_chat_id"], width=34).grid(
            row=1, column=1, sticky="ew"
        )
        telegram_actions = ttk.Frame(telegram)
        telegram_actions.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Button(telegram_actions, text="Перевірити", command=self.connect_telegram).pack(side="left")
        ttk.Label(telegram, textvariable=self.telegram_status_var, foreground="#555").grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(5, 0)
        )
        telegram.columnconfigure(0, weight=1)
        telegram.columnconfigure(1, weight=1)

        google = ttk.LabelFrame(platforms, text="Google Drive — тимчасове медіа", padding=8)
        google.pack(fill="x", pady=4)
        self.settings_vars["google_client_id"] = tk.StringVar(value=self.config.google_client_id)
        self.settings_vars["google_client_secret"] = tk.StringVar(value=self.config.google_client_secret)
        ttk.Label(google, text="OAuth Client ID типу Desktop app").grid(row=0, column=0, sticky="w")
        ttk.Entry(google, textvariable=self.settings_vars["google_client_id"], width=70).grid(
            row=1, column=0, sticky="ew", padx=(0, 8)
        )
        ttk.Label(google, text="Client secret").grid(row=0, column=1, sticky="w")
        ttk.Entry(google, textvariable=self.settings_vars["google_client_secret"], show="•", width=28).grid(
            row=1, column=1, sticky="ew"
        )
        google_actions = ttk.Frame(google)
        google_actions.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Button(
            google_actions,
            text="Google Cloud",
            command=lambda: webbrowser.open("https://console.cloud.google.com/apis/credentials", new=2),
        ).pack(side="left")
        ttk.Button(google_actions, text="Підключити Drive", command=self.connect_google_drive).pack(side="left", padx=(6, 0))
        ttk.Label(google, textvariable=self.google_status_var, foreground="#555").grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(5, 2)
        )
        ttk.Label(
            google,
            text=(
                "Папка й файли можуть залишатися приватними. Для Threads програма сама тимчасово відкриває "
                "доступ лише до конкретного файла, а після успіху безповоротно видаляє його. Вручну змінювати "
                "доступ кожного медіа не потрібно. Оплата Google Cloud і Free Trial не потрібні."
            ),
            foreground="#666",
            wraplength=1000,
        ).grid(row=4, column=0, columnspan=2, sticky="ew")
        google.columnconfigure(0, weight=1)

        appearance = ttk.LabelFrame(form, text="3. Вигляд", padding=10)
        appearance.pack(fill="x", pady=(0, 8))
        ttk.Label(
            appearance,
            text="Розмір шрифту змінюється одразу. Натисніть «ЗБЕРЕГТИ ЗМІНИ», щоб він лишився після перезапуску.",
        ).pack(anchor="w")
        font_row = ttk.Frame(appearance)
        font_row.pack(anchor="w", pady=(6, 0))
        ttk.Label(font_row, text="Шрифт:").pack(side="left")
        ttk.Button(font_row, text="A−", command=lambda: self.change_font_size(-1)).pack(side="left", padx=(8, 3))
        ttk.Label(font_row, textvariable=self.ui_font_size_var, width=4, anchor="center").pack(side="left")
        ttk.Button(font_row, text="A+", command=lambda: self.change_font_size(1)).pack(side="left", padx=3)

        workflow = ttk.LabelFrame(form, text="4. Збір і тренди", padding=10)
        workflow.pack(fill="x", pady=(0, 8))
        self.threads_trend_var = tk.BooleanVar(value=self.config.threads_trend_search_enabled)
        ttk.Label(
            workflow,
            text="Усі увімкнені джерела перевіряються автоматично після запуску і кожні 5 хвилин.",
        ).pack(anchor="w")
        ttk.Checkbutton(workflow, text="Використовувати Threads для оцінки вибуховості, якщо дозвіл доступний", variable=self.threads_trend_var).pack(anchor="w")

        learning = ttk.LabelFrame(form, text="Локальне навчання", padding=8)
        learning.pack(fill="x", pady=(0, 8))
        self.learning_enabled_var = tk.BooleanVar(value=self.config.learning_enabled)
        self.learning_examples_limit_var = tk.StringVar(value=str(self.config.learning_examples_limit))
        self.learning_stats_var = tk.StringVar(value="")
        ttk.Checkbutton(
            learning, text="Використовувати навчальні приклади в промптах Ollama",
            variable=self.learning_enabled_var,
        ).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(learning, text="Кількість прикладів у промпті").grid(row=1, column=0, sticky="w", pady=(7, 0))
        ttk.Combobox(
            learning, textvariable=self.learning_examples_limit_var,
            values=tuple(str(value) for value in range(1, 13)), state="readonly", width=6,
        ).grid(row=1, column=1, sticky="w", padx=6, pady=(7, 0))
        ttk.Button(learning, text="Оновити статистику", command=self.refresh_learning_stats).grid(
            row=1, column=2, sticky="w", pady=(7, 0)
        )
        ttk.Label(learning, textvariable=self.learning_stats_var, foreground="#555").grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(6, 3)
        )
        learning_actions = ttk.Frame(learning)
        learning_actions.grid(row=3, column=0, columnspan=3, sticky="w", pady=(5, 0))
        ttk.Button(learning_actions, text="Експортувати навчальні дані", command=self.export_learning_data_ui).pack(side="left")
        ttk.Button(learning_actions, text="Імпортувати навчальні дані", command=self.import_learning_data_ui).pack(side="left", padx=6)
        ttk.Button(learning_actions, text="Очистити навчальну історію", command=self.clear_learning_history_ui).pack(side="left")
        ttk.Button(
            learning_actions, text="Керувати виключеннями", command=self.open_content_exclusions_ui
        ).pack(side="left", padx=6)
        self.refresh_learning_stats()

        schedule = ttk.LabelFrame(form, text="5. Розклад", padding=10)
        schedule.pack(fill="x", pady=(0, 8))
        self.publish_start_var = tk.StringVar(value=str(self.config.publish_start_hour))
        self.publish_end_var = tk.StringVar(value=str(self.config.publish_end_hour))
        self.publish_interval_var = tk.StringVar(value=str(self.config.publish_interval_minutes))
        ttk.Label(schedule, text="Публікувати з").grid(row=0, column=0, sticky="w")
        ttk.Combobox(schedule, textvariable=self.publish_start_var, values=tuple(str(i) for i in range(24)), state="readonly", width=8).grid(row=1, column=0, padx=(0, 10))
        ttk.Label(schedule, text="до").grid(row=0, column=1, sticky="w")
        ttk.Combobox(schedule, textvariable=self.publish_end_var, values=tuple(str(i) for i in range(1, 25)), state="readonly", width=8).grid(row=1, column=1, padx=(0, 10))
        ttk.Label(schedule, text="Інтервал").grid(row=0, column=2, sticky="w")
        ttk.Combobox(schedule, textvariable=self.publish_interval_var, values=("15", "20", "30", "45", "60", "90", "120"), state="readonly", width=10).grid(row=1, column=2, padx=(0, 6))
        ttk.Label(schedule, text="хвилин").grid(row=1, column=3, sticky="w")

        actions = ttk.Frame(form)
        actions.pack(fill="x", pady=(4, 0))
        action_buttons = ttk.Frame(actions)
        action_buttons.grid(row=0, column=0, sticky="w")
        ttk.Button(action_buttons, text="ЗБЕРЕГТИ ЗМІНИ", command=self.save_settings).pack(side="left")
        ttk.Button(action_buttons, text="Створити backup", command=self.create_backup_ui).pack(side="left", padx=6)
        ttk.Button(action_buttons, text="Імпортувати backup", command=self.import_backup_ui).pack(side="left", padx=6)
        ttk.Label(
            actions,
            text=(
                "Портативні налаштування зашифровані. Для перенесення копіюйте всю папку програми разом із Data."
                if portable_mode()
                else "Секрети й Google refresh token шифруються Windows DPAPI."
            ),
            foreground="#555",
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", pady=(6, 0))
        actions.columnconfigure(0, weight=1)

        self._update_target_availability()
        self._install_settings_change_tracking()
        self.root.after(400, lambda: self.scan_ollama_models(show_errors=False))

    def _refresh_meta_pages_view(self) -> None:
        if not hasattr(self, "meta_pages_tree"):
            return
        self.meta_pages_tree.delete(*self.meta_pages_tree.get_children())
        for page in self.meta_pages:
            self.meta_pages_tree.insert("", "end", iid=page.id, values=(page.name, page.id))

    def _meta_status_text(self) -> str:
        pages = configured_facebook_pages(self.config)
        if not pages:
            return "Не підключено"
        names = ", ".join(page["name"] for page in pages[:4])
        suffix = f" та ще {len(pages) - 4}" if len(pages) > 4 else ""
        expiry = (
            " · " + _expiry_label(self.config.meta_user_token_expires_at)
            if self.config.meta_user_token_expires_at
            else " · строк дії токена не визначено"
        )
        return f"Підключено сторінок: {len(pages)} · {names}{suffix}{expiry}"

    def _threads_status_text(self) -> str:
        name = self.config.threads_profile_name or self.config.threads_user_id
        if not self.config.platform_ready("threads"):
            return "Не підключено"
        expiry = (
            " · " + _expiry_label(self.config.threads_token_expires_at)
            if self.config.threads_token_expires_at
            else " · строк дії токена не визначено"
        )
        return f"Підключено: {name}{expiry}"

    def _linkedin_status_text(self) -> str:
        name = self.config.linkedin_profile_name or self.config.linkedin_author_urn
        return f"Підключено: {name}" if self.config.platform_ready("linkedin") else "Не підключено"

    def _telegram_status_text(self) -> str:
        return f"Налаштовано для {self.config.telegram_chat_id}" if self.config.platform_ready("telegram") else "Не підключено"

    def _google_status_text(self) -> str:
        if not self.config.platform_ready("google_drive"):
            return "Не підключено"
        return f"Підключено: {self.config.google_account_email or 'Google-акаунт'}"

    def _diagnostics_config_snapshot(self) -> AppConfig:
        payload = asdict(self.config)
        if hasattr(self, "settings_vars"):
            for key in (
                "meta_app_id",
                "meta_app_secret",
                "meta_user_access_token",
                "threads_token",
                "linkedin_token",
                "telegram_bot_token",
                "telegram_chat_id",
                "google_client_id",
                "google_client_secret",
            ):
                variable = self.settings_vars.get(key)
                if variable is not None:
                    payload[key] = variable.get().strip()
        return AppConfig(**payload)

    def _schedule_connection_diagnostics(self) -> None:
        if self.stop_event.is_set():
            return
        if self.connection_diagnostics_after_id is not None:
            try:
                self.root.after_cancel(self.connection_diagnostics_after_id)
            except tk.TclError:
                pass
        self.connection_diagnostics_after_id = self.root.after(
            TOKEN_DIAGNOSTIC_INTERVAL_MS,
            lambda: self.run_connection_diagnostics(automatic=True),
        )

    def run_connection_diagnostics(self, *, automatic: bool = False) -> None:
        if self.connection_diagnostics_running:
            if not automatic:
                self.msg.showinfo(
                    "Діагностика підключень",
                    "Перевірка токенів і прав уже виконується.",
                    parent=self.root,
                )
            return
        if self.connection_diagnostics_after_id is not None:
            try:
                self.root.after_cancel(self.connection_diagnostics_after_id)
            except tk.TclError:
                pass
            self.connection_diagnostics_after_id = None
        self.connection_diagnostics_running = True
        snapshot = self._diagnostics_config_snapshot()
        if hasattr(self, "connection_diagnostics_button"):
            self.connection_diagnostics_button.configure(state="disabled")
        if hasattr(self, "connection_diagnostics_status_var"):
            self.connection_diagnostics_status_var.set(
                "Перевіряю Facebook, Threads, LinkedIn, Telegram і Google Drive…"
            )

        def task() -> None:
            try:
                report = diagnose_connections(snapshot)
            except Exception as exc:
                try:
                    self.root.after(0, lambda: self._connection_diagnostics_failed(exc, automatic))
                except tk.TclError:
                    pass
                return
            try:
                self.root.after(
                    0,
                    lambda: self._connection_diagnostics_completed(report, snapshot, automatic),
                )
            except tk.TclError:
                pass

        threading.Thread(
            target=task,
            name="connection-diagnostics",
            daemon=True,
        ).start()

    def _connection_diagnostics_failed(self, error: Exception, automatic: bool) -> None:
        self.connection_diagnostics_running = False
        if hasattr(self, "connection_diagnostics_button"):
            self.connection_diagnostics_button.configure(state="normal")
        text = "Автоматична діагностика завершилася внутрішньою помилкою; токени не оголошено недійсними."
        if hasattr(self, "connection_diagnostics_status_var"):
            self.connection_diagnostics_status_var.set(text)
        if not automatic:
            self.msg.showerror(
                "Діагностика підключень",
                text + "\n\n" + str(error),
                parent=self.root,
            )
        self._schedule_connection_diagnostics()

    def _persist_diagnostic_metadata(
        self,
        report: ConnectionDiagnosticsReport,
        snapshot: AppConfig,
    ) -> None:
        # Never save over fields while the user is editing them. Live diagnostics may
        # still show the result, but metadata refresh waits for a clean settings form.
        if self.settings_dirty:
            return
        changed = False
        if (
            report.meta_profile is not None
            and report.meta_pages
            and snapshot.meta_user_access_token == self.config.meta_user_access_token
        ):
            pages = [
                {"id": page.id, "name": page.name, "access_token": page.access_token}
                for page in report.meta_pages
            ]
            if pages != self.config.facebook_pages:
                self.config.facebook_pages = pages
                self.config.sync_legacy_facebook_slots()
                self.meta_pages = list(report.meta_pages)
                self._refresh_meta_pages_view()
                changed = True
        if (
            report.threads_profile is not None
            and snapshot.threads_token == self.config.threads_token
        ):
            profile = report.threads_profile
            if self.config.threads_user_id != profile.id or self.config.threads_profile_name != profile.name:
                self.config.threads_user_id = profile.id
                self.config.threads_profile_name = profile.name
                changed = True
        if (
            report.linkedin_profile is not None
            and snapshot.linkedin_token == self.config.linkedin_token
        ):
            profile = report.linkedin_profile
            if (
                self.config.linkedin_author_urn != profile.author_urn
                or self.config.linkedin_profile_name != profile.name
            ):
                self.config.linkedin_author_urn = profile.author_urn
                self.config.linkedin_profile_name = profile.name
                changed = True
        if (
            report.google_profile is not None
            and snapshot.google_refresh_token == self.config.google_refresh_token
        ):
            email = report.google_profile.account_email
            if email and self.config.google_account_email != email:
                self.config.google_account_email = email
                changed = True
        if changed:
            save_config(self.config)
            self.publisher_factory.config = self.config
            self._update_target_availability()

    def _connection_diagnostics_completed(
        self,
        report: ConnectionDiagnosticsReport,
        snapshot: AppConfig,
        automatic: bool,
    ) -> None:
        self.connection_diagnostics_running = False
        if hasattr(self, "connection_diagnostics_button"):
            self.connection_diagnostics_button.configure(state="normal")
        self._persist_diagnostic_metadata(report, snapshot)

        if hasattr(self, "connection_diagnostics_tree"):
            self.connection_diagnostics_tree.delete(*self.connection_diagnostics_tree.get_children())
            for item in report.items:
                self.connection_diagnostics_tree.insert(
                    "",
                    "end",
                    iid=item.key,
                    values=(
                        item.label,
                        DIAGNOSTIC_STATUS_LABELS.get(item.status, item.status),
                        item.message,
                    ),
                )

        by_key = {item.key: item for item in report.items}
        status_vars = {
            "facebook": getattr(self, "meta_status_var", None),
            "threads": getattr(self, "threads_status_var", None),
            "linkedin": getattr(self, "linkedin_status_var", None),
            "telegram": getattr(self, "telegram_status_var", None),
            "google_drive": getattr(self, "google_status_var", None),
        }
        for key, variable in status_vars.items():
            item = by_key.get(key)
            if variable is not None and item is not None:
                variable.set(item.message)

        facebook_item = by_key.get("facebook")
        threads_item = by_key.get("threads")
        if facebook_item is not None and facebook_item.status == STATUS_OK:
            if hasattr(self, "worker"):
                self.worker.clear_auth_blocks("facebook")
        if threads_item is not None and threads_item.status == STATUS_OK:
            if hasattr(self, "worker"):
                self.worker.clear_auth_blocks("threads")

        action_items = report.action_items
        temporary_items = report.temporary_items
        checked = [item for item in report.items if item.status != STATUS_NOT_CONFIGURED]
        if action_items:
            names = ", ".join(item.label for item in action_items)
            summary = f"Потрібна увага: {names}. Деталі наведені нижче."
            self.set_status(summary)
            if hasattr(self, "queue_alert_var"):
                self.queue_alert_var.set(
                    summary + " Автоматична перевірка не блокує інтерфейс. Відкрийте «Налаштування» або «Черга»."
                )
        elif temporary_items:
            names = ", ".join(item.label for item in temporary_items)
            summary = f"Частину підключень тимчасово не перевірено: {names}. Токени не відхилено."
            self.set_status(summary)
        elif checked:
            summary = "Усі налаштовані токени й права актуальні на момент перевірки."
            self.set_status(summary)
        else:
            summary = "Платформи ще не налаштовано."
        if hasattr(self, "connection_diagnostics_status_var"):
            stamp = datetime.now(KYIV).strftime("%d.%m.%Y %H:%M")
            self.connection_diagnostics_status_var.set(f"{summary} Перевірено: {stamp} за Києвом.")

        signature = tuple((item.key, item.status, item.message) for item in action_items)
        # Automatic diagnostics must never open a modal window over publication.
        # The result remains visible in the diagnostics table, status bar and queue banner.
        should_warn = bool(action_items) and not automatic
        if should_warn:
            lines = ["Програма виявила підключення, які потребують дії:"]
            for item in action_items:
                lines.append(f"• {item.label}: {item.message}")
            self.msg.showwarning(
                "Потрібно оновити токен або права",
                "\n\n".join(lines),
                parent=self.root,
            )
        elif not automatic:
            details = [summary]
            if temporary_items:
                details.extend(f"• {item.label}: {item.message}" for item in temporary_items)
            self.msg.showinfo(
                "Діагностика підключень",
                "\n\n".join(details),
                parent=self.root,
            )
        self.last_connection_warning_signature = signature
        self._schedule_connection_diagnostics()

    def _schedule_threads_token_maintenance(self) -> None:
        if self.stop_event.is_set():
            return
        if self.threads_token_maintenance_after_id is not None:
            try:
                self.root.after_cancel(self.threads_token_maintenance_after_id)
            except tk.TclError:
                pass
        self.threads_token_maintenance_after_id = self.root.after(
            24 * 60 * 60 * 1000,
            self._maybe_refresh_threads_token_async,
        )

    def _maybe_refresh_threads_token_async(self) -> None:
        self.threads_token_maintenance_after_id = None
        token = self.config.threads_token.strip()
        expiry = parse_iso(self.config.threads_token_expires_at)
        now = datetime.now(KYIV)
        if not token or expiry is None:
            self._schedule_threads_token_maintenance()
            return
        expiry = expiry.astimezone(KYIV)
        if expiry <= now:
            reason = "Threads-токен прострочено; автоматичне оновлення після завершення строку неможливе."
            self.worker.block_auth("threads", reason)
            if hasattr(self, "threads_status_var"):
                self.threads_status_var.set(reason)
            if hasattr(self, "queue_alert_var"):
                self.queue_alert_var.set(reason + " Створіть новий токен і переплануйте призупинені пакети.")
            self._schedule_threads_token_maintenance()
            return
        if expiry - now > timedelta(days=7):
            self._schedule_threads_token_maintenance()
            return
        refreshed_at = parse_iso(self.config.threads_token_refreshed_at)
        if refreshed_at is not None and now - refreshed_at.astimezone(KYIV) < timedelta(hours=24):
            self._schedule_threads_token_maintenance()
            return
        expected_token = token

        def runner() -> None:
            try:
                refreshed = refresh_threads_long_lived_token(expected_token)
            except Exception as exc:
                message = "Threads-токен не вдалося автоматично оновити: " + str(exc)
                try:
                    self.root.after(0, lambda: self.threads_status_var.set(message))
                except tk.TclError:
                    pass
                return

            def apply() -> None:
                if self.config.threads_token != expected_token:
                    return
                self.config.threads_token = refreshed.access_token
                self.config.threads_token_expires_at = _expiry_from_seconds(refreshed.expires_in)
                self.config.threads_token_refreshed_at = datetime.now(KYIV).isoformat(timespec="seconds")
                if hasattr(self, "settings_vars") and "threads_token" in self.settings_vars and not self.settings_dirty:
                    self.settings_vars["threads_token"].set(refreshed.access_token)
                save_config(self.config)
                self.publisher_factory.config = self.config
                if hasattr(self, "worker"):
                    self.worker.clear_auth_blocks("threads")
                self.threads_status_var.set(
                    "Threads-токен автоматично оновлено; " + _expiry_label(self.config.threads_token_expires_at)
                )
                self.worker.wake()

            try:
                self.root.after(0, apply)
            except tk.TclError:
                pass

        threading.Thread(target=runner, name="threads-token-refresh", daemon=True).start()
        self._schedule_threads_token_maintenance()

    def _prewarm_ollama_model_async(self, model: str | None = None) -> None:
        selected = str(model or self.config.ollama_model or "").strip()
        if not selected or not hasattr(self, "ollama_status_var"):
            return
        current = self.ollama_prewarm_event
        if self.ollama_prewarm_model == selected and current is not None and not current.is_set():
            return
        self.ollama_prewarm_serial += 1
        serial = self.ollama_prewarm_serial
        event = threading.Event()
        self.ollama_prewarm_model = selected
        self.ollama_prewarm_event = event
        self.ollama_status_var.set(f"Підготовка моделі {selected} у фоні…")

        def runner() -> None:
            error_text = ""
            try:
                OllamaClient(self.config.ollama_base_url, timeout=240, load_timeout=120).preload_model(selected)
            except Exception as exc:
                error_text = str(exc)
            finally:
                event.set()

            def finish() -> None:
                if serial != self.ollama_prewarm_serial:
                    return
                if error_text:
                    self.ollama_status_var.set(f"Модель не підготовлена: {error_text}")
                else:
                    self.ollama_status_var.set(f"Модель {selected} готова до швидкого рерайту")

            try:
                self.root.after(0, finish)
            except tk.TclError:
                pass

        threading.Thread(target=runner, name="ollama-prewarm", daemon=True).start()

    def scan_ollama_models(self, show_errors: bool = True) -> None:
        self.ollama_status_var.set("Сканування…")

        def action() -> list[str]:
            return OllamaClient(self.config.ollama_base_url, timeout=20).list_models()

        def success(result: object) -> None:
            models = list(result) if isinstance(result, list) else []
            self._set_model_choices(models)
            self.ollama_status_var.set(f"Знайдено моделей: {len(models)}" if models else "Ollama працює, але моделей не знайдено.")

        if show_errors:
            self.run_async(action, success, label="Ollama: сканую встановлені моделі", done_label="Сканування Ollama завершено")
            return

        def runner() -> None:
            try:
                result = action()
            except Exception:
                self.root.after(0, lambda: self.ollama_status_var.set("Ollama не знайдено. Запустіть Ollama і натисніть кнопку."))
                return
            self.root.after(0, lambda: success(result))

        threading.Thread(target=runner, daemon=True).start()

    def _set_model_choices(self, models: list[str]) -> None:
        unique = list(dict.fromkeys(model for model in models if model))
        self.ollama_model_combo.configure(values=unique)
        self.ollama_fallback_combo.configure(values=["Без запасної моделі", *unique])
        previous_loading = self._settings_loading
        self._settings_loading = True
        try:
            if self.ollama_model_var.get() not in unique:
                self.ollama_model_var.set(unique[0] if unique else "")
            fallback = self.ollama_fallback_var.get()
            if fallback not in ["Без запасної моделі", *unique] or fallback == self.ollama_model_var.get():
                self.ollama_fallback_var.set(next((model for model in unique if model != self.ollama_model_var.get()), "Без запасної моделі"))
        finally:
            self._settings_loading = previous_loading
        self._prewarm_ollama_model_async(self.ollama_model_var.get())

    def connect_meta(self) -> None:
        user_token = self.settings_vars["meta_user_access_token"].get().strip()
        app_id_var = self.settings_vars.get("facebook_app_id")
        app_secret_var = self.settings_vars.get("facebook_app_secret")
        app_id = app_id_var.get().strip() if app_id_var is not None else self.config.facebook_app_id
        app_secret = app_secret_var.get().strip() if app_secret_var is not None else self.config.facebook_app_secret
        graph_version = self.config.meta_graph_version or "v26.0"
        self.meta_status_var.set("Перевіряється токен і завантажуються сторінки…")

        def action() -> object:
            token_for_pages = user_token
            expires_at = ""
            lifecycle_note = ""
            if app_id and app_secret:
                try:
                    exchanged = exchange_facebook_long_lived_token(
                        user_token, app_id, app_secret, graph_version
                    )
                    token_for_pages = exchanged.access_token
                    expires_at = _expiry_from_seconds(exchanged.expires_in)
                    lifecycle_note = "Короткий Facebook-токен обміняно на довготривалий."
                except PlatformSetupError as exc:
                    # A token may already be long-lived. Validate it before deciding
                    # that the connection is unusable.
                    lifecycle_note = "Автоматичний обмін не виконано: " + str(exc)
            pages = load_meta_pages(token_for_pages, graph_version)
            return token_for_pages, expires_at, pages, lifecycle_note

        def success(result: object) -> None:
            token_for_pages, expires_at, pages, lifecycle_note = result  # type: ignore[misc]
            self._meta_connected(
                str(token_for_pages),
                str(expires_at),
                pages,
                str(lifecycle_note),
            )

        self.run_async(
            action,
            success,
            label="Facebook: перевіряю токен і завантажую всі сторінки",
            done_label="Facebook-сторінки завантажено",
            timeout_seconds=35,
            timeout_message=(
                "Facebook не відповів за 35 секунд. Перевірку зупинено в інтерфейсі; токен не змінено."
            ),
        )

    def _meta_connected(
        self,
        user_token: str,
        expires_at: str,
        pages: object,
        lifecycle_note: str = "",
    ) -> None:
        app_id_var = self.settings_vars.get("facebook_app_id")
        app_secret_var = self.settings_vars.get("facebook_app_secret")
        self.config.facebook_app_id = app_id_var.get().strip() if app_id_var is not None else self.config.facebook_app_id
        self.config.facebook_app_secret = app_secret_var.get().strip() if app_secret_var is not None else self.config.facebook_app_secret
        self.config.meta_app_id = self.config.facebook_app_id
        self.config.meta_app_secret = self.config.facebook_app_secret
        self.config.meta_user_access_token = user_token
        self.config.meta_user_token_expires_at = expires_at
        self.settings_vars["meta_user_access_token"].set(user_token)
        self.meta_pages = list(pages)  # type: ignore[arg-type]
        self.config.facebook_pages = [
            {"id": page.id, "name": page.name, "access_token": page.access_token}
            for page in self.meta_pages
        ]
        self.config.sync_legacy_facebook_slots()
        if hasattr(self, "worker"):
            self.worker.clear_auth_blocks("facebook")
        self._refresh_meta_pages_view()
        expiry = _expiry_label(expires_at) if expires_at else "строк дії Meta не повідомила"
        extra = f" {lifecycle_note}" if lifecycle_note else ""
        self.meta_status_var.set(
            f"Підключено сторінок: {len(self.meta_pages)}; {expiry}.{extra}"
        )
        self._persist_connected_config("Facebook-токен і всі доступні сторінки збережено")

    def connect_threads(self) -> None:
        token = self.settings_vars["threads_token"].get().strip()
        app_secret_var = self.settings_vars.get("threads_app_secret")
        app_secret = app_secret_var.get().strip() if app_secret_var is not None else self.config.threads_app_secret
        self.threads_status_var.set(
            "Профіль Threads: перевіряю токен і строк дії…"
        )

        profile_timeout_seconds = 12

        def action() -> object:
            try:
                final_token = token
                expires_at = ""
                lifecycle_note = ""
                exchange_error: PlatformSetupError | None = None
                if app_secret:
                    try:
                        exchanged = exchange_threads_long_lived_token(token, app_secret)
                        final_token = exchanged.access_token
                        expires_at = _expiry_from_seconds(exchanged.expires_in)
                        lifecycle_note = "Короткий Threads-токен обміняно на довготривалий."
                    except PlatformSetupError as exc:
                        exchange_error = exc
                if not expires_at:
                    try:
                        refreshed = refresh_threads_long_lived_token(token)
                        final_token = refreshed.access_token
                        expires_at = _expiry_from_seconds(refreshed.expires_in)
                        lifecycle_note = "Довготривалий Threads-токен оновлено."
                    except PlatformSetupError as refresh_error:
                        if exchange_error is not None:
                            lifecycle_note = "Автоматичне подовження не виконано: " + str(exchange_error)
                        elif app_secret:
                            lifecycle_note = "Автоматичне подовження не виконано: " + str(refresh_error)
                profile = inspect_threads_token(final_token)
                return profile, final_token, expires_at, lifecycle_note
            except Exception as exc:
                self.root.after(
                    0,
                    lambda message=str(exc): self.threads_status_var.set(
                        "Профіль Threads: НЕ ПІДКЛЮЧЕНО. " + message
                    ),
                )
                raise

        def success(result: object) -> None:
            profile, final_token, expires_at, lifecycle_note = result  # type: ignore[misc]
            app_id_var = self.settings_vars.get("threads_app_id")
            self.config.threads_app_id = app_id_var.get().strip() if app_id_var is not None else self.config.threads_app_id
            self.config.threads_app_secret = app_secret
            self.config.meta_app_id = self.config.facebook_app_id or self.config.threads_app_id
            self.config.meta_app_secret = self.config.facebook_app_secret or self.config.threads_app_secret
            self.config.threads_token = str(final_token)
            self.config.threads_token_expires_at = str(expires_at)
            self.config.threads_token_refreshed_at = datetime.now(KYIV).isoformat(timespec="seconds")
            self.config.threads_user_id = profile.id  # type: ignore[attr-defined]
            self.config.threads_profile_name = profile.name  # type: ignore[attr-defined]
            self.settings_vars["threads_token"].set(str(final_token))
            if hasattr(self, "worker"):
                self.worker.clear_auth_blocks("threads")
            username = profile.username  # type: ignore[attr-defined]
            display_name = f"@{username}" if username else str(profile.name)  # type: ignore[attr-defined]
            expiry = _expiry_label(str(expires_at)) if expires_at else "строк дії Meta не повідомила"
            extra = f" {lifecycle_note}" if lifecycle_note else ""
            self.threads_status_var.set(
                f"Публікація підключена: {display_name}; {expiry}.{extra}"
            )
            self._persist_connected_config("Новий Threads-токен і профіль збережено")
            self.msg.showinfo(
                "Threads",
                f"Профіль визначено: {display_name}. Токен збережено.\n\n{expiry}."
                + (("\n\n" + lifecycle_note) if lifecycle_note else "")
                + "\n\nПошук трендів перевіряється окремою кнопкою.",
                parent=self.root,
            )

        self.run_async(
            action,
            success,
            label="Threads: перевіряю профіль і строк дії (до 12 секунд)",
            done_label="Threads-профіль перевірено",
            timeout_seconds=profile_timeout_seconds,
            timeout_message=(
                "Threads не відповів за 12 секунд. Перевірку зупинено в інтерфейсі; токен не змінено."
            ),
            on_timeout=lambda message: self.threads_status_var.set(
                "Профіль Threads: НЕ ПІДКЛЮЧЕНО. " + message
            ),
        )

    def check_threads_trends(self) -> None:
        token = self.settings_vars["threads_token"].get().strip()
        if not token:
            self.threads_search_status_var.set("Пошук трендів Threads: вставте токен.")
            self.msg.showwarning("Threads", "Вставте Threads access token.", parent=self.root)
            return
        self.threads_search_status_var.set(
            "Пошук трендів Threads: перевіряю keyword_search, очікування до 12 секунд…"
        )

        def success(result: object) -> None:
            available, detail = result  # type: ignore[misc]
            if available:
                self.config.threads_token = token
                self.threads_search_status_var.set(
                    "Пошук трендів Threads: ПІДКЛЮЧЕНО. Токен збережено."
                )
                self._persist_connected_config("Threads keyword search підключено; токен збережено")
                self.msg.showinfo(
                    "Threads",
                    "Пошук трендів підключено. Дозвіл threads_keyword_search працює.",
                    parent=getattr(self, "root", None),
                )
                return
            self.threads_search_status_var.set(
                "Пошук трендів Threads: НЕ ПІДКЛЮЧЕНО. "
                f"{detail}"
            )
            self.msg.showwarning(
                "Threads",
                "Пошук трендів не підключено.\n\n" + str(detail),
                parent=getattr(self, "root", None),
            )

        self.run_async(
            lambda: check_threads_keyword_access(token),
            success,
            label="Threads: перевіряю keyword_search (до 12 секунд)",
            done_label="Перевірку Threads-пошуку завершено",
            timeout_seconds=12,
            timeout_message=(
                "Threads keyword_search не відповів за 12 секунд. Перевірку зупинено в інтерфейсі. "
                "Це може бути збій DNS, мережі або Meta API."
            ),
            on_timeout=lambda message: self.threads_search_status_var.set(
                "Пошук трендів Threads: НЕ ПІДКЛЮЧЕНО. " + message
            ),
        )

    def connect_linkedin(self) -> None:
        token = self.settings_vars["linkedin_token"].get().strip()
        self.linkedin_status_var.set("Перевіряється токен…")

        def success(result: object) -> None:
            profile = result
            self.config.linkedin_author_urn = profile.author_urn  # type: ignore[attr-defined]
            self.config.linkedin_profile_name = profile.name  # type: ignore[attr-defined]
            self.config.linkedin_token = profile.access_token  # type: ignore[attr-defined]
            self.linkedin_status_var.set(f"Підключено і збережено: {profile.name}")
            self._persist_connected_config("LinkedIn-токен збережено")

        self.run_async(
            lambda: inspect_linkedin_token(token),
            success,
            label="LinkedIn: перевіряю токен",
            done_label="LinkedIn-токен перевірено",
        )

    def connect_telegram(self) -> None:
        token = self.settings_vars["telegram_bot_token"].get().strip()
        target = self.settings_vars["telegram_chat_id"].get().strip()

        def success(result: object) -> None:
            self.config.telegram_bot_token = token
            self.config.telegram_chat_id = target
            self.telegram_status_var.set(
                f"Бот @{result.username} має доступ до «{result.target_title}». Налаштування збережено."  # type: ignore[attr-defined]
            )
            self._persist_connected_config("Telegram-токен і канал збережено")

        self.run_async(
            lambda: inspect_telegram_bot(token, target),
            success,
            label="Telegram: перевіряю бота і канал",
            done_label="Telegram перевірено",
        )

    def connect_google_drive(self) -> None:
        client_id = self.settings_vars["google_client_id"].get().strip()
        client_secret = self.settings_vars["google_client_secret"].get().strip()
        self.google_status_var.set("Очікується вхід у Google через браузер…")

        def success(result: object) -> None:
            self.config.google_client_id = client_id
            self.config.google_client_secret = client_secret
            self.config.google_refresh_token = result.refresh_token  # type: ignore[attr-defined]
            self.config.google_account_email = result.account_email  # type: ignore[attr-defined]
            self.google_status_var.set(f"Підключено і збережено: {self.config.google_account_email or 'Google-акаунт'}")
            self._persist_connected_config("Google Drive підключено і збережено")

        self.run_async(
            lambda: authorize_google_drive(client_id, client_secret),
            success,
            label="Google Drive: очікую авторизацію в браузері",
            done_label="Google Drive підключено",
        )

    def save_settings(self, *, show_confirmation: bool = True) -> bool:
        try:
            old_meta_token = self.config.meta_user_access_token
            old_threads_token = self.config.threads_token
            new_facebook_app_id = self.settings_vars["facebook_app_id"].get().strip()
            new_facebook_app_secret = self.settings_vars["facebook_app_secret"].get().strip()
            new_threads_app_id = self.settings_vars["threads_app_id"].get().strip()
            new_threads_app_secret = self.settings_vars["threads_app_secret"].get().strip()
            new_meta_token = self.settings_vars["meta_user_access_token"].get().strip()
            new_threads_token = self.settings_vars["threads_token"].get().strip()
            new_google_id = self.settings_vars["google_client_id"].get().strip()
            new_google_secret = self.settings_vars["google_client_secret"].get().strip()
            pages = [
                {"id": page.id, "name": page.name, "access_token": page.access_token}
                for page in self.meta_pages
            ]
            if new_meta_token != self.config.meta_user_access_token:
                pages = []
                self.meta_pages = []
            payload = asdict(self.config)
            if new_meta_token != old_meta_token:
                payload["meta_user_token_expires_at"] = ""
            if new_threads_token != old_threads_token:
                payload["threads_token_expires_at"] = ""
                payload["threads_token_refreshed_at"] = ""
            payload.update(
                {
                    "ollama_base_url": "http://127.0.0.1:11434",
                    "ollama_model": self.ollama_model_var.get().strip(),
                    "ollama_fallback_model": ""
                    if self.ollama_fallback_var.get() == "Без запасної моделі"
                    else self.ollama_fallback_var.get().strip(),
                    "facebook_app_id": new_facebook_app_id,
                    "facebook_app_secret": new_facebook_app_secret,
                    "threads_app_id": new_threads_app_id,
                    "threads_app_secret": new_threads_app_secret,
                    "meta_app_id": new_facebook_app_id or new_threads_app_id,
                    "meta_app_secret": new_facebook_app_secret or new_threads_app_secret,
                    "ui_language": language_from_label(self.ui_language_var.get()),
                    "learning_enabled": self.learning_enabled_var.get(),
                    "learning_examples_limit": int(self.learning_examples_limit_var.get()),
                    "meta_user_access_token": new_meta_token,
                    "threads_token": new_threads_token,
                    "linkedin_token": self.settings_vars["linkedin_token"].get().strip(),
                    "telegram_bot_token": self.settings_vars["telegram_bot_token"].get().strip(),
                    "telegram_chat_id": self.settings_vars["telegram_chat_id"].get().strip(),
                    "google_client_id": new_google_id,
                    "google_client_secret": new_google_secret,
                    "auto_collect_on_start": True,
                    "threads_trend_search_enabled": self.threads_trend_var.get(),
                    "publish_start_hour": int(self.publish_start_var.get()),
                    "publish_end_hour": int(self.publish_end_var.get()),
                    "publish_interval_minutes": int(self.publish_interval_var.get()),
                    "ui_font_size": int(self.ui_font_size_var.get()),
                    "meta_graph_version": self.config.meta_graph_version or "v26.0",
                    "linkedin_version": self.config.linkedin_version or "202607",
                    "facebook_pages": pages,
                }
            )
            if new_google_id != self.config.google_client_id or new_google_secret != self.config.google_client_secret:
                payload.update(google_refresh_token="", google_account_email="")
            config = AppConfig(**payload)
            config.sync_legacy_facebook_slots()
            config.validate()
            save_config(config)
        except (ValueError, ConfigError, PlatformSetupError, GoogleDriveError) as exc:
            self._show_error(exc)
            return False
        self.config = config
        self.publisher_factory.config = config
        if hasattr(self, "worker"):
            if new_meta_token != old_meta_token:
                self.worker.clear_auth_blocks("facebook")
            if new_threads_token != old_threads_token:
                self.worker.clear_auth_blocks("threads")
            if new_meta_token != old_meta_token or new_threads_token != old_threads_token:
                self.worker.wake()
        self._prewarm_ollama_model_async(config.ollama_model)
        self._apply_ui_font_size(config.ui_font_size)
        self.ui_language_var.set(language_label(config.ui_language))
        self._apply_language(refresh=False)
        self._refresh_meta_pages_view()
        self.meta_status_var.set(self._meta_status_text())
        self.threads_status_var.set(self._threads_status_text())
        self.linkedin_status_var.set(self._linkedin_status_text())
        self.telegram_status_var.set(self._telegram_status_text())
        self.google_status_var.set(self._google_status_text())
        self._update_target_availability()
        self._schedule_next_auto_collect()
        self._mark_settings_saved("Збережено в портативній папці" if portable_mode() else "Збережено на цьому комп’ютері")
        self.set_status("Налаштування й токени зашифровано та збережено в папці програми" if portable_mode() else "Налаштування й токени зашифровано та збережено")
        if show_confirmation:
            self.msg.showinfo(
                "Налаштування",
                (
                    "Зміни збережено в папці Data. Після перенесення всієї папки програми на інший Windows-комп’ютер ці налаштування залишаться."
                    if portable_mode()
                    else "Зміни збережено. Після перезапуску програма відкриє саме ці значення."
                ),
                parent=self.root,
            )
        if not self.connection_diagnostics_running:
            self.root.after(800, lambda: self.run_connection_diagnostics(automatic=True))
        return True

    def _update_target_availability(self) -> None:
        if not hasattr(self, "targets_row"):
            return
        self._rebuild_target_controls()

    def refresh_learning_stats(self) -> None:
        if not hasattr(self, "learning_stats_var"):
            return
        stats = self.db.learning_stats()
        examples = stats.get("editorial_examples", {})
        if self.config.ui_language == "en":
            self.learning_stats_var.set(
                f"Examples: UK {examples.get('uk', 0)} · EN {examples.get('en', 0)} · "
                f"merge feedback: {stats.get('topic_feedback', 0)} · events: {stats.get('events', 0)} · "
                f"active exclusions: {stats.get('active_exclusions', 0)}"
            )
        else:
            self.learning_stats_var.set(
                f"Приклади: UK {examples.get('uk', 0)} · EN {examples.get('en', 0)} · "
                f"рішень про об’єднання: {stats.get('topic_feedback', 0)} · подій: {stats.get('events', 0)} · "
                f"активних виключень: {stats.get('active_exclusions', 0)}"
            )

    def export_learning_data_ui(self) -> None:
        selected = self.files.asksaveasfilename(
            parent=self.root, title=self.t("Експортувати навчальні дані"),
            defaultextension=".json", filetypes=[("JSON", "*.json")],
            initialfile="UA_FREE_learning_data.json",
        )
        if not selected:
            return
        try:
            path = self.db.export_learning_data(Path(selected))
        except Exception as exc:
            self._show_error(exc)
            return
        self.msg.showinfo(self.t("Локальне навчання"), str(path), parent=self.root)

    def import_learning_data_ui(self) -> None:
        selected = self.files.askopenfilename(
            parent=self.root, title=self.t("Імпортувати навчальні дані"),
            filetypes=[("JSON", "*.json")],
        )
        if not selected:
            return
        try:
            counts = self.db.import_learning_data(Path(selected))
        except Exception as exc:
            self._show_error(exc)
            return
        self.refresh_learning_stats()
        self.msg.showinfo(self.t("Локальне навчання"), str(counts), parent=self.root)

    def open_content_exclusions_ui(self) -> None:
        ContentExclusionsDialog(
            self.root, self.db, language=self.config.ui_language,
            on_change=self.refresh_learning_stats,
        )

    def clear_learning_history_ui(self) -> None:
        question = (
            "Delete editorial examples, merge feedback, and learning events? Permanent inbox exclusions will remain."
            if self.config.ui_language == "en"
            else "Видалити редакційні приклади, рішення про об’єднання та навчальні події? Постійні виключення новин залишаться."
        )
        if not self.msg.askyesno(self.t("Очистити навчальну історію"), question, parent=self.root):
            return
        self.db.clear_learning_history()
        self.refresh_learning_stats()

    def create_backup_ui(self) -> None:
        self.run_async(
            create_backup,
            lambda path: self.msg.showinfo("Backup", f"Створено:\n{path}", parent=self.root),
            label="Створюю резервну копію",
            done_label="Резервну копію створено",
        )

    def import_backup_ui(self) -> None:
        selected = self.files.askopenfilename(parent=self.root, title="Оберіть backup", filetypes=[("UA FREE backup", "*.zip")])
        if not selected:
            return
        if not self.msg.askyesno("Імпорт", "Поточні дані спочатку буде збережено в safety backup. Продовжити?", parent=self.root):
            return

        def success(result: object) -> None:
            try:
                self.config = load_config()
            except ConfigError:
                self.config = AppConfig()
            self.publisher_factory.config = self.config
            self.db = Database()
            self.worker.database = self.db
            self.refresh_sources()
            self.refresh_groups()
            self.refresh_queue()
            self.refresh_history()
            self._update_target_availability()
            self.ui_language_var.set(language_label(self.config.ui_language))
            self._apply_language()
            self.refresh_learning_stats()
            self.msg.showinfo(
                "Імпорт",
                f"Імпорт завершено. Safety backup: {getattr(result, 'safety_backup', '')}",
                parent=self.root,
            )

        self.run_async(
            lambda: import_backup(Path(selected)),
            success,
            label="Імпортую резервну копію",
            done_label="Імпорт завершено",
        )
