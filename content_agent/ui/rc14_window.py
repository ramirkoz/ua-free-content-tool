from __future__ import annotations

import logging
import threading
import tkinter as tk
from datetime import datetime

from ..database_rc14 import PUBLICATION_HISTORY_RETENTION_DAYS
from ..scheduling import KYIV
from . import main_window as legacy
from .v1_3_window import MainWindow as Rc13Window

logger = logging.getLogger("content_agent.ui.rc14")
QUEUE_REFRESH_INTERVAL_MS = 15_000
HISTORY_MAINTENANCE_INTERVAL_MS = 24 * 60 * 60 * 1000


class MainWindow(Rc13Window):
    """RC14: keep Tk responsive while Data maintenance runs off the UI thread."""

    VERSION_LABEL = "1.3.1-rc14"

    def __init__(self, root: tk.Tk, database, config) -> None:
        self._rc14_initializing = True
        self._rc14_maintenance_ready = False
        self.history_maintenance_after_id: str | None = None
        database._rc14_defer_startup_maintenance = True
        try:
            super().__init__(root, database, config)
        finally:
            database._rc14_defer_startup_maintenance = False
            self._rc14_initializing = False
        self._apply_v13_labels()
        self.root.after(100, self._begin_startup_maintenance)

    def _apply_v13_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v1.3.1-rc14")
        button = getattr(self, "rewrite_button", None)
        if button is not None:
            button.configure(
                text="Rewrite via AI Router + Fact Guard"
                if getattr(self.config, "ui_language", "uk") == "en"
                else "Рерайт через AI Router + Fact Guard"
            )
        history_all = getattr(self, "history_refresh_all_button", None)
        if history_all is not None:
            history_all.configure(
                text="Refresh statistics for 7 days"
                if getattr(self.config, "ui_language", "uk") == "en"
                else "Оновити статистику за 7 діб"
            )

    def refresh_sources(self) -> None:
        if not getattr(self, "_rc14_initializing", False):
            super().refresh_sources()

    def refresh_groups(self) -> None:
        if not getattr(self, "_rc14_initializing", False):
            super().refresh_groups()

    def refresh_history(self) -> None:
        if getattr(self, "_rc14_initializing", False):
            return
        super().refresh_history()
        if hasattr(self, "history_summary_var"):
            count = len(getattr(self, "history_rows", {}))
            self.history_summary_var.set(
                f"Published in the last 7 days: {count}"
                if getattr(self.config, "ui_language", "uk") == "en"
                else f"Опубліковано за останні 7 діб: {count}"
            )

    def refresh_queue(self) -> None:
        if getattr(self, "_rc14_initializing", False) or not hasattr(self, "queue_tree"):
            return
        self._queue_selection_anchor = None
        self.queue_tree.delete(*self.queue_tree.get_children())
        labels = legacy.target_labels(self.config)
        statuses = legacy.QUEUE_FILTERS.get(self.queue_filter.get())
        now_kyiv = datetime.now(KYIV)
        batches = self.db.list_batches(statuses=statuses)
        block_labels = self.db.group_labels_for_batches(batch.id for batch in batches)
        for batch in batches:
            target_parts: list[str] = []
            for item in batch.targets:
                text = (
                    f"{labels.get(item.platform, item.platform)}: "
                    f"{legacy.TARGET_STATUS_LABELS.get(item.status, item.status)}"
                )
                if item.status == "failed" and item.last_error:
                    clean = " ".join(str(item.last_error).split())
                    text += " — " + (clean if len(clean) <= 180 else clean[:177] + "…")
                target_parts.append(text)
            schedule_text, schedule_local = legacy._format_kyiv_schedule(batch.scheduled_at)
            status_text = legacy.BATCH_STATUS_LABELS.get(batch.status, batch.status)
            if batch.status == "pending" and schedule_local is not None and schedule_local <= now_kyiv:
                status_text = f"прострочено на {legacy._format_overdue(now_kyiv - schedule_local)}"
            self.queue_tree.insert(
                "",
                "end",
                iid=str(batch.id),
                values=(
                    batch.id,
                    block_labels.get(batch.id, "Блок недоступний"),
                    schedule_text + " (Київ)",
                    status_text,
                    batch.attempts,
                    ", ".join(target_parts),
                    batch.cleanup_error or "—",
                ),
            )
        self._update_queue_summary()

    def _schedule_queue_refresh(self) -> None:
        if self.stop_event.is_set():
            return
        if self.queue_refresh_after_id is not None:
            try:
                self.root.after_cancel(self.queue_refresh_after_id)
            except tk.TclError:
                pass
        self.queue_refresh_after_id = self.root.after(
            QUEUE_REFRESH_INTERVAL_MS, self._periodic_queue_refresh
        )

    def _startup_queue_migration_gate(self) -> None:
        if not getattr(self, "_rc14_maintenance_ready", False):
            return
        super()._startup_queue_migration_gate()

    def _begin_startup_maintenance(self) -> None:
        if getattr(self, "_closing", False) or self.stop_event.is_set():
            return
        self.status_var.set("Запуск: обслуговування Data у фоні…")

        def work() -> None:
            started = datetime.now().timestamp()
            try:
                recovered = self.db.recover_abandoned_batches(max_automatic_attempts=3)
                stale = self.db.archive_stale_groups()
                archived = self.db.archive_old_publication_history(PUBLICATION_HISTORY_RETENTION_DAYS)
                logger.info(
                    "RC14 startup maintenance recovered=%d stale_groups=%d history_archived=%d duration=%.3fs",
                    len(recovered), stale, archived, datetime.now().timestamp() - started,
                )
                self._post_ui(lambda: self._finish_startup_maintenance(recovered, stale, archived))
            except Exception as exc:
                logger.exception("RC14 startup maintenance failed")
                self._post_ui(lambda error=exc: self._fail_startup_maintenance(error))

        threading.Thread(target=work, name="startup-maintenance", daemon=True).start()

    def _finish_startup_maintenance(self, recovered: list[int], stale: int, archived: int) -> None:
        if getattr(self, "_closing", False):
            return
        self.refresh_sources()
        self.refresh_groups()
        self.refresh_queue()
        self.refresh_history()
        self._rc14_maintenance_ready = True
        if recovered:
            self.status_var.set(
                "Безпечно призупинено перервані/виснажені пакети: "
                + ", ".join(f"#{item}" for item in recovered[:12])
            )
        elif stale or archived:
            self.status_var.set(f"Готово · архівовано блоків: {stale}; публікацій: {archived}")
        else:
            self.status_var.set("Готово")
        self._schedule_history_maintenance()
        self.root.after(10, self._startup_queue_migration_gate)

    def _fail_startup_maintenance(self, exc: Exception) -> None:
        self._rc14_maintenance_ready = False
        self.status_var.set("Публікацію не запущено: обслуговування Data не завершено.")
        self.msg.showerror(
            "Перевірка Data не завершена",
            "Планувальник залишився вимкненим. Помилка: " + str(exc),
            parent=self.root,
        )

    def _schedule_history_maintenance(self) -> None:
        if self.stop_event.is_set() or getattr(self, "_closing", False):
            return
        if self.history_maintenance_after_id is not None:
            try:
                self.root.after_cancel(self.history_maintenance_after_id)
            except tk.TclError:
                pass
        self.history_maintenance_after_id = self.root.after(
            HISTORY_MAINTENANCE_INTERVAL_MS, self._run_history_maintenance
        )

    def _run_history_maintenance(self) -> None:
        self.history_maintenance_after_id = None
        if self.stop_event.is_set() or getattr(self, "_closing", False):
            return

        def work() -> None:
            try:
                archived = self.db.archive_old_publication_history(PUBLICATION_HISTORY_RETENTION_DAYS)
                logger.info("RC14 daily publication history archived=%d", archived)
                if archived:
                    self._post_ui(self.refresh_history)
            except Exception:
                logger.exception("RC14 daily history maintenance failed")
            finally:
                self._post_ui(self._schedule_history_maintenance)

        threading.Thread(target=work, name="history-maintenance", daemon=True).start()

    def connect_threads(self) -> None:
        token = self.settings_vars["threads_token"].get().strip()
        app_secret_var = self.settings_vars.get("threads_app_secret")
        app_secret = app_secret_var.get().strip() if app_secret_var is not None else self.config.threads_app_secret
        self.threads_status_var.set("Профіль Threads: перевіряю токен і строк дії…")

        def action() -> object:
            try:
                final_token = token
                expires_at = ""
                lifecycle_note = ""
                exchange_error: legacy.PlatformSetupError | None = None
                if app_secret:
                    try:
                        exchanged = legacy.exchange_threads_long_lived_token(token, app_secret)
                        final_token = exchanged.access_token
                        expires_at = legacy._expiry_from_seconds(exchanged.expires_in)
                        lifecycle_note = "Короткий Threads-токен обміняно на довготривалий."
                    except legacy.PlatformSetupError as exc:
                        exchange_error = exc
                if not expires_at:
                    try:
                        refreshed = legacy.refresh_threads_long_lived_token(token)
                        final_token = refreshed.access_token
                        expires_at = legacy._expiry_from_seconds(refreshed.expires_in)
                        lifecycle_note = "Довготривалий Threads-токен оновлено."
                    except legacy.PlatformSetupError as refresh_error:
                        if exchange_error is not None:
                            lifecycle_note = "Автоматичне подовження не виконано: " + str(exchange_error)
                        elif app_secret:
                            lifecycle_note = "Автоматичне подовження не виконано: " + str(refresh_error)
                return legacy.inspect_threads_token(final_token), final_token, expires_at, lifecycle_note
            except Exception as exc:
                self._post_ui(
                    lambda message=str(exc): self.threads_status_var.set(
                        "Профіль Threads: НЕ ПІДКЛЮЧЕНО. " + message
                    )
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
            expiry = legacy._expiry_label(str(expires_at)) if expires_at else "строк дії Meta не повідомила"
            extra = f" {lifecycle_note}" if lifecycle_note else ""
            self.threads_status_var.set(f"Публікація підключена: {display_name}; {expiry}.{extra}")
            self._persist_connected_config("Новий Threads-токен і профіль збережено")
            self.msg.showinfo(
                "Threads",
                f"Профіль визначено: {display_name}. Токен збережено.\n\n{expiry}."
                + (("\n\n" + lifecycle_note) if lifecycle_note else ""),
                parent=self.root,
            )

        self.run_async(
            action,
            success,
            label="Threads: перевіряю профіль і строк дії (до 12 секунд)",
            done_label="Threads-профіль перевірено",
            timeout_seconds=12,
            timeout_message="Threads не відповів за 12 секунд. Перевірку зупинено в інтерфейсі; токен не змінено.",
            on_timeout=lambda message: self.threads_status_var.set(
                "Профіль Threads: НЕ ПІДКЛЮЧЕНО. " + message
            ),
        )

    def close(self) -> None:
        if self.history_maintenance_after_id is not None:
            try:
                self.root.after_cancel(self.history_maintenance_after_id)
            except tk.TclError:
                pass
            self.history_maintenance_after_id = None
        super().close()
