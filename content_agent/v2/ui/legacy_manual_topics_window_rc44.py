from __future__ import annotations

import logging
import os
import queue
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import simpledialog, ttk

from ...ai_router import (
    AIProviderSecrets,
    load_provider_secrets,
    provider_health_text,
    save_provider_secrets,
    test_ai_router,
)
from ...app.container import AppServices, build_services
from ...config import AppConfig, ConfigError, load_config
from ...i18n import language_label
from ...paths import portable_mode
from ..publishing.outcomes import PublicationOutcome
from .manual_topics_window import ALL_SOURCES, ALL_TOPICS, MainWindow as Rc43MainWindow

logger = logging.getLogger("content_agent.v2.ui.rc44")
_RESTORE_PASSWORD_ENV = "UA_FREE_RESTORE_PASSWORD"


class MainWindow(Rc43MainWindow):
    """Stable V2 shell for source topics, composition and operator-safe UX.

    The file name stays stable intentionally: new behavior moves toward services
    and explicit composition rather than another version-numbered MainWindow layer.
    """

    def __init__(self, root, database_or_services, config=None) -> None:
        # RC48: RC15 owns a historical source-only filter. V2 owns the authoritative
        # Source + Topic controls, so the old layer must not render or mutate them.
        self._disable_rc15_source_filter = True
        if isinstance(database_or_services, AppServices):
            services = database_or_services
            self.services = services
            super().__init__(root, services.db, services.config)
        else:
            super().__init__(root, database_or_services, config)
            self.services = build_services(config=self.config, database=self.db)
        try:
            setattr(self.root, "_ua_free_post_ui", self._post_ui)
        except Exception:
            logger.exception("Could not expose UI dispatcher to child dialogs")

        self._apply_rc48_shell_layout()
        self._apply_rc48_publication_layout()
        self._apply_rc48_inbox_labels()
        self._install_rc48_history_unknown_controls()
        self._install_rc48_keyboard_shortcuts()
        self._install_rc50_migration_backup_button()

    def save_ai_provider_keys(self) -> None:
        """Persist the direct-provider fields owned by the canonical V2 AI tab."""
        try:
            current = load_provider_secrets()
            values = getattr(self, "ai_provider_vars", {})
            updated = AIProviderSecrets(
                gemini_api_key=str(values["gemini_api_key"].get() or ""),
                nvidia_api_key=str(values["nvidia_api_key"].get() or ""),
                groq_api_key=str(values["groq_api_key"].get() or ""),
                cloudflare_account_id=str(values["cloudflare_account_id"].get() or ""),
                cloudflare_api_token=str(values["cloudflare_api_token"].get() or ""),
                codex_enabled=bool(self.codex_enabled_var.get()),
                local_enabled=bool(self.local_enabled_var.get()),
                local_base_url=current.local_base_url,
                local_model=current.local_model,
            )
            save_provider_secrets(updated)
            self.refresh_v2_ai_status()
            self.v2_router_status_var.set(provider_health_text())
            self.set_status("AI Router: прямі провайдери збережено.")
        except Exception as exc:
            self._show_error(exc)

    def test_ai_router_ui(self) -> None:
        """Run the canonical Router probe without blocking Tk."""
        def action() -> str:
            return test_ai_router()

        def success(result: object) -> None:
            self.refresh_v2_ai_status()
            health = provider_health_text()
            self.v2_router_status_var.set(f"{result}\n{health}" if health else str(result))
            self.set_status(str(result))

        self.run_async(
            action,
            success,
            label="Перевіряю AI Router",
            done_label="AI Router перевірено",
            timeout_seconds=165,
            timeout_message="AI Router не завершив перевірку за 165 секунд.",
            modal_errors=False,
            modal_timeout=False,
        )

    def _drain_ui_events(self) -> None:
        """Keep Tk alive while making queued callback failures observable."""
        self._ui_dispatch_after_id = None
        self._ui_last_pulse = time.monotonic()
        if getattr(self, "_closing", False):
            return
        processed = 0
        while processed < 200:
            try:
                callback = self._ui_event_queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except Exception:
                logger.exception("Queued UI callback failed")
            processed += 1
        if not getattr(self, "_closing", False):
            try:
                self._ui_dispatch_after_id = self.root.after(50, self._drain_ui_events)
            except tk.TclError:
                self._ui_dispatch_after_id = None

    def create_backup_ui(self) -> None:
        """Create the credential-free durable RC50 backup."""
        self.run_async(
            self.services.maintenance.create_backup,
            lambda path: self.msg.showinfo("Backup", f"Створено:\n{path}", parent=self.root),
            label="Створюю резервну копію",
            done_label="Резервну копію створено",
        )

    def create_migration_backup_ui(self) -> None:
        """Create an explicit password-protected cross-machine credential backup."""
        password = simpledialog.askstring(
            "Migration backup",
            "Введіть пароль для захисту credentials (мінімум 10 символів):",
            parent=self.root,
            show="*",
        )
        if password is None:
            return
        confirmation = simpledialog.askstring(
            "Migration backup",
            "Повторіть пароль:",
            parent=self.root,
            show="*",
        )
        if confirmation is None:
            return
        if password != confirmation:
            self.msg.showerror("Migration backup", "Паролі не збігаються.", parent=self.root)
            return
        if len(password) < 10:
            self.msg.showerror(
                "Migration backup",
                "Пароль має містити щонайменше 10 символів.",
                parent=self.root,
            )
            return
        self.run_async(
            lambda: self.services.maintenance.create_migration_backup(password),
            lambda path: self.msg.showinfo(
                "Migration backup",
                "Створено захищену копію для перенесення на інший комп’ютер:\n" + str(path),
                parent=self.root,
            ),
            label="Створюю migration backup",
            done_label="Migration backup створено",
        )

    def _install_rc50_migration_backup_button(self) -> None:
        if hasattr(self, "_rc50_migration_backup_button"):
            return
        for widget in self._rc48_walk(self.root):
            if not isinstance(widget, (ttk.Button, tk.Button)):
                continue
            try:
                if str(widget.cget("text") or "") != "Створити backup":
                    continue
            except Exception:
                continue
            button = ttk.Button(
                widget.master,
                text="Migration backup…",
                command=self.create_migration_backup_ui,
            )
            try:
                button.pack(side="left", padx=6, after=widget)
            except tk.TclError:
                button.pack(side="left", padx=6)
            self._rc50_migration_backup_button = button
            return

    def _rc50_restart_after_restore(self, credential_password: str | None) -> None:
        executable = Path(sys.executable).resolve()
        if portable_mode() and executable.name.casefold() == "ua_free_content_tool.exe":
            env = os.environ.copy()
            if credential_password:
                env[_RESTORE_PASSWORD_ENV] = credential_password
            command = (
                f"Wait-Process -Id {os.getpid()}; "
                f"Start-Process -FilePath '{str(executable).replace("'", "''")}'"
            )
            try:
                subprocess.Popen(
                    [
                        "powershell.exe",
                        "-NoLogo",
                        "-NoProfile",
                        "-WindowStyle",
                        "Hidden",
                        "-Command",
                        command,
                    ],
                    cwd=str(executable.parent),
                    env=env,
                    close_fds=True,
                )
            except Exception as exc:
                logger.exception("Could not schedule portable restart after restore")
                self.msg.showwarning(
                    "Відновлення підготовлено",
                    "Backup підготовлено, але автоматичний перезапуск не вдався. "
                    "Закрийте програму і запустіть її знову.\n\n" + str(exc),
                    parent=self.root,
                )
                return
            self.close()
            return
        self.msg.showinfo(
            "Відновлення підготовлено",
            "Backup перевірено й підготовлено. Закрийте програму та запустіть її знову, "
            "щоб застосувати відновлення до створення бази даних.",
            parent=self.root,
        )

    def import_backup_ui(self) -> None:
        """Validate now, apply only after restart before database construction."""
        selected = self.files.askopenfilename(
            parent=self.root,
            title="Оберіть backup",
            filetypes=[("UA FREE backup", "*.zip")],
        )
        if not selected:
            return
        archive = Path(selected)
        try:
            requires_password = self.services.maintenance.backup_requires_password(archive)
        except Exception as exc:
            self._show_error(exc)
            return
        password: str | None = None
        if requires_password:
            password = simpledialog.askstring(
                "Migration backup",
                "Цей backup містить захищені credentials. Введіть пароль:",
                parent=self.root,
                show="*",
            )
            if password is None:
                return
        if not self.msg.askyesno(
            "Імпорт",
            "Backup буде перевірено й підготовлено. Поточні дані спочатку збережуться "
            "в safety backup, а відновлення застосовується тільки після перезапуску. Продовжити?",
            parent=self.root,
        ):
            return

        def success(result: object) -> None:
            safety = getattr(result, "safety_backup", "")
            self.msg.showinfo(
                "Відновлення підготовлено",
                f"Backup перевірено. Safety backup: {safety}\n\n"
                "Зараз програма перезапуститься й застосує відновлення до створення робочої бази.",
                parent=self.root,
            )
            self._rc50_restart_after_restore(password)

        self.run_async(
            lambda: self.services.maintenance.stage_restore(
                archive,
                credential_password=password,
            ),
            success,
            label="Перевіряю та готую backup",
            done_label="Відновлення підготовлено",
        )

    # ------------------------------------------------------------------
    # RC44 manual source/topic filters, now authoritative over the retired RC15
    # source-only filter.
    # ------------------------------------------------------------------
    def _install_manual_topic_inbox_filters(self) -> None:
        if hasattr(self, "inbox_source_filter_box"):
            return
        tree = getattr(self, "groups_tree", None)
        if tree is None:
            return

        tree_frame = tree.master
        tab = tree_frame.master
        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=(0, 6), before=tree_frame)
        self._manual_topic_filter_bar = bar

        self.inbox_source_filter_var = tk.StringVar(master=self.root, value=ALL_SOURCES)
        self.inbox_topic_filter_var = tk.StringVar(master=self.root, value=ALL_TOPICS)

        ttk.Label(bar, text="Фільтри:").pack(side="left")
        ttk.Label(bar, text="Джерело:").pack(side="left", padx=(10, 4))
        self.inbox_source_filter_box = ttk.Combobox(
            bar,
            textvariable=self.inbox_source_filter_var,
            state="readonly",
            width=24,
        )
        self.inbox_source_filter_box.pack(side="left", padx=(0, 8))
        self.inbox_source_filter_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh_groups())

        ttk.Label(bar, text="Тема:").pack(side="left", padx=(0, 4))
        self.inbox_topic_filter_box = ttk.Combobox(
            bar,
            textvariable=self.inbox_topic_filter_var,
            state="readonly",
            width=20,
        )
        self.inbox_topic_filter_box.pack(side="left", padx=(0, 8))
        self.inbox_topic_filter_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh_groups())

        ttk.Button(
            bar,
            text="Скинути",
            command=self.reset_manual_topic_filters,
        ).pack(side="left")

        self._refresh_inbox_filter_choices()

    # ------------------------------------------------------------------
    # RC48 shell: no useful status information may live below the visible screen.
    # ------------------------------------------------------------------
    @staticmethod
    def _rc48_walk(parent: tk.Misc):
        for child in parent.winfo_children():
            yield child
            yield from MainWindow._rc48_walk(child)

    def _apply_rc48_shell_layout(self) -> None:
        try:
            screen_w = max(800, int(self.root.winfo_screenwidth()))
            screen_h = max(600, int(self.root.winfo_screenheight()))
            width = max(760, min(1440, screen_w - 40))
            height = max(500, min(920, screen_h - 80))
            self.root.geometry(f"{width}x{height}")
            self.root.minsize(min(900, width), min(650, height))
        except Exception:
            logger.exception("Could not apply adaptive RC48 window geometry")

        notebook = getattr(self, "notebook", None)
        if notebook is None:
            return

        old_activity = None
        old_status = None
        operation_token = str(getattr(self, "operation_var", ""))
        status_token = str(getattr(self, "status_var", ""))
        for child in list(self.root.winfo_children()):
            if child is notebook:
                continue
            if isinstance(child, ttk.Frame):
                for nested in child.winfo_children():
                    try:
                        if str(nested.cget("textvariable")) == operation_token:
                            old_activity = child
                            break
                    except Exception:
                        continue
            if isinstance(child, ttk.Label):
                try:
                    if str(child.cget("textvariable")) == status_token:
                        old_status = child
                except Exception:
                    pass

        if old_activity is not None:
            old_activity.pack_forget()
        if old_status is not None:
            old_status.pack_forget()
        notebook.pack_forget()

        bar = ttk.Frame(self.root, padding=(10, 4))
        bar.pack(side="bottom", fill="x")
        self._rc48_status_bar = bar
        ttk.Label(bar, textvariable=self.operation_var).pack(side="left")
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Label(bar, textvariable=self.status_var, anchor="w").pack(side="left", fill="x", expand=True)
        self.operation_progress = ttk.Progressbar(bar, mode="indeterminate", length=130)
        self.operation_progress.pack(side="right", padx=(8, 0))
        notebook.pack(side="top", fill="both", expand=True, padx=8, pady=(2, 2))

    def _apply_rc48_publication_layout(self) -> None:
        tab = getattr(self, "publication_tab", None)
        if tab is None:
            return
        try:
            tab.rowconfigure(3, weight=1, minsize=170)
        except Exception:
            pass
        canvas = getattr(self, "targets_canvas", None)
        if canvas is not None:
            try:
                canvas.configure(height=170)
            except Exception:
                pass
        media_tree = getattr(self, "media_candidates_tree", None)
        if media_tree is not None:
            try:
                media_tree.configure(height=3)
            except Exception:
                pass

    def _layout_target_controls(self) -> None:
        super()._layout_target_controls()
        canvas = getattr(self, "targets_canvas", None)
        if canvas is not None:
            try:
                canvas.configure(height=max(170, int(canvas.cget("height") or 0)))
            except Exception:
                pass

    def _apply_rc48_inbox_labels(self) -> None:
        tree = getattr(self, "groups_tree", None)
        if tree is None:
            return
        tab = tree.master.master
        replacements = {
            "Запам’ятати й більше не пропонувати": "Більше не пропонувати…",
            "Пошук схожих за темою матеріалів": "Знайти схожі",
            "Об’єднати в один блок": "Об’єднати",
            "Знайти за ключовими словами": "Знайти",
            "Редагувати склад блоку": "Склад блоку…",
        }
        for widget in self._rc48_walk(tab):
            if not isinstance(widget, (ttk.Button, tk.Button)):
                continue
            try:
                text = str(widget.cget("text") or "")
            except Exception:
                continue
            replacement = replacements.get(text)
            if replacement:
                try:
                    widget.configure(text=replacement)
                except Exception:
                    pass

    def _install_rc48_keyboard_shortcuts(self) -> None:
        try:
            self.root.bind("<Control-f>", self._rc48_focus_inbox_search, add="+")
            self.root.bind("<Control-F>", self._rc48_focus_inbox_search, add="+")
            self.root.bind("<Escape>", self._rc48_escape_inbox_search, add="+")
        except Exception:
            logger.exception("Could not install RC48 Inbox shortcuts")

    def _rc48_focus_inbox_search(self, _event=None):
        entry = getattr(self, "_rc14_keyword_entry", None)
        if entry is None:
            return None
        try:
            entry.focus_set()
            entry.selection_range(0, "end")
            return "break"
        except Exception:
            return None

    def _rc48_escape_inbox_search(self, _event=None):
        entry = getattr(self, "_rc14_keyword_entry", None)
        if entry is None:
            return None
        try:
            if self.root.focus_get() is entry and str(self.keyword_search_var.get() or ""):
                self.keyword_search_var.set("")
                return "break"
        except Exception:
            return None
        return None

    # ------------------------------------------------------------------
    # RC48 publication outcome UX. Unknown is not an ordinary failure.
    # ------------------------------------------------------------------
    def _rc48_latest_targets_for_group(self, group_id: int) -> dict[str, dict[str, object]]:
        with self.db.connect() as db:
            rows = db.execute(
                "SELECT t.id,t.platform,t.status,t.remote_id,t.last_error,t.progress_json,t.outcome "
                "FROM publication_targets t "
                "JOIN publication_batches b ON b.id=t.batch_id "
                "JOIN articles a ON a.id=b.article_id "
                "WHERE a.group_id=? ORDER BY t.id DESC",
                (int(group_id),),
            ).fetchall()
        latest: dict[str, dict[str, object]] = {}
        for row in rows:
            platform = str(row["platform"] or "")
            if platform and platform not in latest:
                latest[platform] = {key: row[key] for key in row.keys()}
        return latest

    def _rc48_unknown_targets(self, group_id: int) -> list[dict[str, object]]:
        return [
            row
            for row in self._rc48_latest_targets_for_group(group_id).values()
            if str(row.get("outcome") or "") == PublicationOutcome.UNKNOWN.value
        ]

    def _install_rc48_history_unknown_controls(self) -> None:
        retry = getattr(self, "history_retry_button", None)
        parent = getattr(retry, "master", None)
        if parent is None or hasattr(self, "_rc48_unknown_status_var"):
            return
        try:
            retry.configure(text="Повторити")
        except Exception:
            pass
        self._rc48_unknown_status_var = tk.StringVar(master=self.root, value="")
        self._rc48_unknown_label = ttk.Label(
            parent,
            textvariable=self._rc48_unknown_status_var,
            foreground="#8a6200",
        )
        self._rc48_unknown_label.pack(side="left", padx=(10, 4))
        self._rc48_post_exists_button = ttk.Button(
            parent,
            text="Пост є",
            command=self._rc48_confirm_unknown_sent,
            state="disabled",
        )
        self._rc48_post_exists_button.pack(side="left", padx=(4, 2))
        self._rc48_post_absent_button = ttk.Button(
            parent,
            text="Поста немає",
            command=self._rc48_confirm_unknown_not_sent,
            state="disabled",
        )
        self._rc48_post_absent_button.pack(side="left", padx=2)
        overview = getattr(self, "history_overview_tree", None)
        detail = getattr(self, "history_detail_tree", None)
        if overview is not None:
            overview.bind("<<TreeviewSelect>>", lambda _event: self._update_rc48_history_unknown_state(), add="+")
        if detail is not None:
            detail.bind("<<TreeviewSelect>>", lambda _event: self._update_rc48_history_unknown_state(), add="+")
        self._update_rc48_history_unknown_state()

    def refresh_history(self) -> None:
        super().refresh_history()
        if hasattr(self, "_rc48_unknown_status_var"):
            self._update_rc48_history_unknown_state()

    def _update_rc48_history_unknown_state(self) -> None:
        variable = getattr(self, "_rc48_unknown_status_var", None)
        if variable is None:
            return
        group_id = self._selected_history_group_id_v2()
        unknown = self._rc48_unknown_targets(group_id) if group_id is not None else []
        if unknown:
            labels = self._destination_labels()
            names = [labels.get(str(row.get("platform") or ""), str(row.get("platform") or "")) for row in unknown]
            variable.set("? Невідомо — перевірте платформу: " + ", ".join(names[:3]))
            self._rc48_post_exists_button.configure(state="normal")
            self._rc48_post_absent_button.configure(state="normal")
            retry = getattr(self, "history_retry_button", None)
            if retry is not None:
                retry.configure(state="disabled")
        else:
            variable.set("")
            self._rc48_post_exists_button.configure(state="disabled")
            self._rc48_post_absent_button.configure(state="disabled")

    def _rc48_confirm_unknown_sent(self) -> None:
        group_id = self._selected_history_group_id_v2()
        unknown = self._rc48_unknown_targets(group_id) if group_id is not None else []
        if not unknown:
            return
        if not self.msg.askyesno(
            "Підтвердити публікацію",
            "Ви перевірили платформу і бачите, що пост справді опубліковано?\n\n"
            "Після підтвердження цей результат буде зафіксовано як успішний і повтор заблокується.",
            parent=self.root,
        ):
            return
        try:
            for row in unknown:
                self.db.confirm_target_sent(int(row["id"]))
            self.refresh_history()
            self.set_status("Невідомий результат підтверджено оператором як опублікований.")
        except Exception as exc:
            self._show_error(exc)

    def _rc48_confirm_unknown_not_sent(self) -> None:
        group_id = self._selected_history_group_id_v2()
        unknown = self._rc48_unknown_targets(group_id) if group_id is not None else []
        if not unknown:
            return
        if not self.msg.askyesno(
            "Дозволити повтор",
            "Ви перевірили платформу і переконалися, що поста немає?\n\n"
            "Тільки після цього повторна відправка буде дозволена.",
            parent=self.root,
        ):
            return
        try:
            for row in unknown:
                self.db.confirm_target_not_sent(int(row["id"]))
            self.refresh_history()
            self.set_status("Оператор підтвердив: поста немає. Безпечний повтор дозволено.")
        except Exception as exc:
            self._show_error(exc)

    def publish_now_current(self) -> None:
        group_id = getattr(self, "current_group_id", None)
        if group_id is not None:
            selected = [key for key, variable in getattr(self, "target_vars", {}).items() if variable.get()]
            unknown = self._rc48_unknown_targets(int(group_id))
            blocked = {str(row.get("platform") or "") for row in unknown}.intersection(selected)
            if blocked:
                labels = self._destination_labels()
                names = ", ".join(labels.get(key, key) for key in sorted(blocked))
                self.msg.showwarning(
                    "Публікацію заблоковано",
                    "Для цього матеріалу є невідомий результат на: " + names + ".\n\n"
                    "Спочатку відкрийте «Історію публікацій» і позначте «Пост є» або «Поста немає». "
                    "Це захищає від випадкового дубля.",
                    parent=self.root,
                )
                return
        super().publish_now_current()

    # ------------------------------------------------------------------
    # RC48 editor safety: an AI rewrite may not silently erase operator edits.
    # ------------------------------------------------------------------
    def rewrite_current(self) -> None:
        group_id = getattr(self, "current_group_id", None)
        widget = getattr(self, "text_widgets", {}).get("rewrite") if hasattr(self, "text_widgets") else None
        if group_id is not None and widget is not None:
            try:
                current = str(widget.get("1.0", "end-1c") or "").strip()
                group = self.db.get_group(int(group_id))
                ai_draft = str(getattr(group, "ai_draft_text", "") or "").strip()
            except Exception:
                current = ""
                ai_draft = ""
            if current and current != ai_draft:
                if not self.msg.askyesno(
                    "Замінити відредагований текст?",
                    "Поточний текст відрізняється від останнього AI-чернетки.\n\n"
                    "Новий рерайт замінить ваші ручні правки. Продовжити?",
                    parent=self.root,
                ):
                    return
        super().rewrite_current()


__all__ = ["MainWindow"]
