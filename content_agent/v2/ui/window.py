from __future__ import annotations

import re
import tkinter as tk
from tkinter import ttk

from ...ai_router import (
    clear_router_cooldowns,
    load_provider_secrets,
    provider_health_text,
    save_provider_secrets,
    test_ai_router,
)
from ...codex_runtime import inspect_codex_cached, peek_codex_status_cache
from ...inbox_layout_v1_3_1_rc8 import inbox_layout_path, save_widths
from ...ui.v1_4_rc30_window import MainWindow as LegacyMainWindow
from ...google_drive import DriveMediaInfo, GoogleDriveError
from ...managed_media_drive import ManagedGoogleDriveClient
from ...readable_media_names import readable_post_media_filename
from ...ui.media_workflow import format_media_size
from ...version import APP_VERSION
from ..ai.openrouter_backend import OpenRouterBackend
from ..ai.service import backend_status, test_active_backend
from ..ai.settings import (
    AIBackendSettings,
    BACKEND_AGENT,
    BACKEND_OPENROUTER,
    BACKEND_ROUTER,
    load_backend_settings,
    load_openrouter_api_key,
    save_backend_settings,
    save_openrouter_api_key,
)
from ..ai.usage import usage_summary
from ..supervisor.diagnostics import instance_identity
from ..supervisor.resilient_runtime import ResilientSupervisorRuntime
from ..publishing.retry import assess_failed_target
from .media_drive import ReadableMediaDriveClient


class MainWindow(LegacyMainWindow):
    """Canonical V2 window.

    Legacy UI behavior is isolated behind one compatibility boundary; current V2
    services, media naming, supervisor and watchdog live here instead of in an RC chain.
    """

    VERSION_LABEL = APP_VERSION

    def __init__(self, root, database, config) -> None:
        self.v2_backend_settings = load_backend_settings()
        self.v2_backend_var = tk.StringVar(master=root, value=self.v2_backend_settings.active_backend)
        self.v2_openrouter_key_var = tk.StringVar(master=root, value="")
        self.v2_openrouter_budget_var = tk.StringVar(master=root, value=f"{self.v2_backend_settings.openrouter_monthly_budget_usd:.2f}")
        self.v2_ai_status_var = tk.StringVar(master=root, value="AI V2: ініціалізація…")
        self.v2_openrouter_status_var = tk.StringVar(master=root, value="OpenRouter: не перевірено")
        self.v2_router_status_var = tk.StringVar(master=root, value="AI Router: не перевірено")
        self.v2_agent_status_var = tk.StringVar(master=root, value="Agent: не перевірено")
        self.v2_supervisor_status_var = tk.StringVar(master=root, value="Supervisor: запуск…")
        self._v2_refresh_after_id: str | None = None
        self._v2_inbox_reset_button = None
        self.history_retry_button = None
        self.v2_supervisor: ResilientSupervisorRuntime | None = None

        try:
            self.v2_openrouter_key_var.set(load_openrouter_api_key())
        except Exception:
            self.v2_openrouter_key_var.set("")

        super().__init__(root, database, config)
        # RC32: destinations of one operator-approved queue must not wait on
        # artificial inter-platform/catch-up sleeps. Platform APIs still provide
        # their own real rate-limit signals and those are respected by the worker.
        try:
            self.worker.inter_target_delay_seconds = 0.0
            self.worker.CATCHUP_GAP_SECONDS = 0
            if hasattr(self.worker, "_catchup_not_before"):
                self.worker._catchup_not_before = 0.0
        except Exception:
            pass
        self._apply_v2_inbox_contract()
        self._install_v2_history_retry_button()
        self._build_v2_ai_tab()
        self._build_v2_supervisor_tab()
        self._apply_v2_labels()
        self.refresh_v2_ai_status()

        self.v2_supervisor = ResilientSupervisorRuntime(self, database, config, version=self.VERSION_LABEL)
        self.v2_supervisor.start()
        self._schedule_v2_status_refresh()
        self._autocollect_watchdog_id = None
        self._schedule_autocollect_watchdog()


    def _startup_queue_migration_gate(self) -> None:
        """RC32: legacy queue text migration must never disable collection/publishing.

        Old FIX28 treated any overdue/active package as a reason not to start *any*
        background service. That froze source collection and the publication worker
        together. Current V2 validates text at publication boundaries, so background
        services always start; old queue rows remain visible and can finish normally.
        """
        if self.stop_event.is_set():
            return
        try:
            self._start_background_services()
            self.set_status("Готово. Джерела й публікаційний worker запущено; стара черга не блокує роботу.")
        except Exception as exc:
            self.status_var.set(f"Не вдалося запустити фонові сервіси: {exc}")
            raise

    def _schedule_autocollect_watchdog(self) -> None:
        try:
            if self.stop_event.is_set():
                return
            if getattr(self, "background_services_started", False):
                running = bool(getattr(self, "auto_collect_running", False))
                scheduled = getattr(self, "auto_collect_after_id", None)
                if not running and scheduled is None:
                    self._schedule_next_auto_collect()
            self._autocollect_watchdog_id = self.root.after(60000, self._schedule_autocollect_watchdog)
        except Exception:
            self._autocollect_watchdog_id = None

    def run_worker_once(self) -> None:
        """Run one due package now, then immediately wake the normal queue drain."""
        try:
            if hasattr(self.worker, "_catchup_not_before"):
                self.worker._catchup_not_before = 0.0
            self.worker.inter_target_delay_seconds = 0.0
        except Exception:
            pass

        def work():
            result = self.worker.run_once()
            # Continue the overdue queue immediately after the operator-requested
            # package. The background worker is the single normal owner of the rest.
            try:
                self.worker.wake()
            except Exception:
                pass
            return result

        self.run_async(
            work,
            self._show_worker_result,
            label="Черга: виконую одну публікацію",
            done_label="Перевірку черги завершено",
        )

    def _media_name_context(self) -> tuple[int, str]:
        group_id = int(getattr(self, "current_group_id", 0) or 0)
        title = ""
        headline_var = getattr(self, "headline_var", None)
        if headline_var is not None:
            try:
                title = str(headline_var.get() or "").strip()
            except Exception:
                title = ""
        if not title and group_id:
            try:
                group = self.db.get_group(group_id)
                title = str(group.headline or group.canonical_title or "").strip()
            except Exception:
                title = ""
        return group_id, title

    def _managed_drive_client(self) -> ManagedGoogleDriveClient:
        if not self.config.platform_ready("google_drive"):
            raise GoogleDriveError("Спочатку підключіть Google Drive у налаштуваннях.")
        group_id, title = self._media_name_context()
        return ReadableMediaDriveClient(
            self.config.google_client_id, self.config.google_client_secret, self.config.google_refresh_token,
            post_title=title, group_id=group_id,
        )

    def load_group(self, group_id: int) -> None:
        super().load_group(group_id)
        try:
            group = self.db.get_group(group_id)
        except Exception:
            return
        if not group.media_file_id or not group.media_mime:
            return
        desired = readable_post_media_filename(str(group.headline or group.canonical_title or ""), group_id, group.media_mime)
        if str(group.media_name or "") == desired or not self.config.platform_ready("google_drive"):
            return
        file_id = str(group.media_file_id)

        def action() -> object:
            client = self._managed_drive_client()
            if not isinstance(client, ReadableMediaDriveClient):
                raise GoogleDriveError("Не вдалося підготувати кероване медіа Google Drive.")
            return client.rename_media_file(file_id, desired)

        def success(result: object) -> None:
            if not isinstance(result, DriveMediaInfo):
                return
            drive_url = f"https://drive.google.com/file/d/{result.file_id}/view"
            self.db.set_group_media(group_id, drive_url=drive_url, file_id=result.file_id, name=result.name, kind=result.kind, mime=result.mime_type, size=result.size)
            if getattr(self, "current_group_id", None) != group_id:
                return
            self.media_url_var.set(drive_url)
            self.media_status_var.set(f"Медіа готове ✓ {result.name} · {result.kind.upper()} · {format_media_size(result.size)} · Google Drive: перевірено ✓")

        self.run_async(action, success, label="Надаю медіафайлу зрозумілу назву", done_label="Назву медіафайлу оновлено")

    def _apply_v2_labels(self) -> None:
        self.root.title(f"UA FREE Content Tool — v{self.VERSION_LABEL}")

    def _apply_language(self, refresh: bool = True) -> None:
        super()._apply_language(refresh=refresh)
        self._apply_v2_labels()
        if hasattr(self, "groups_tree"):
            self._apply_v2_inbox_contract()

    def _inbox_headings(self) -> dict[str, str]:
        labels = dict(super()._inbox_headings())
        language = str(getattr(self.config, "ui_language", "uk"))
        labels["sources"] = "Sources" if language == "en" else "Джерел"
        labels["published"] = "Time" if language == "en" else "Час"
        return labels

    def _apply_v2_inbox_contract(self) -> None:
        tree = getattr(self, "groups_tree", None)
        if tree is None:
            return
        columns = tuple(str(item) for item in tree.cget("columns"))
        desired = tuple(item for item in ("title", "topic", "sources", "published") if item in columns)
        tree.configure(displaycolumns=desired)
        tree.column("sources", width=max(90, int(tree.column("sources", "width") or 0)), minwidth=75, stretch=False, anchor="center")
        tree.column("published", width=max(110, min(145, int(tree.column("published", "width") or 110))), minwidth=90, stretch=False, anchor="center")
        labels = self._inbox_headings()
        if hasattr(self, "_install_inbox_multisort_headings"):
            self._install_inbox_multisort_headings(tree)
        for column in ("sources", "published"):
            try:
                base = labels[column]
                state = getattr(self, "_inbox_sort_state", [])
                match = next((item for item in state if item[0] == column), None)
                if match:
                    index = [x[0] for x in state].index(column) + 1
                    base += f" {index}{'▼' if match[1] else '▲'}"
                tree.heading(column, text=base)
            except Exception:
                pass

    @staticmethod
    def _v2_time_only(value: object) -> str:
        text = str(value or "").strip()
        if not text or text == "—":
            return "—"
        matches = re.findall(r"(?<!\d)(\d{1,2}:\d{2}(?::\d{2})?)(?!\d)", text)
        if not matches:
            return text
        value = matches[-1]
        if len(value.split(":")) == 2:
            value += ":00"
        hh, mm, ss = value.split(":")
        return f"{int(hh):02d}:{int(mm):02d}:{int(ss):02d}"

    @staticmethod
    def _v2_time_sort_key(value: object) -> tuple[int, int]:
        text = MainWindow._v2_time_only(value)
        if text == "—":
            return (1, 0)
        try:
            hh, mm, ss = (int(part) for part in text.split(":"))
            return (0, hh * 3600 + mm * 60 + ss)
        except Exception:
            return (1, 0)

    def refresh_groups(self) -> None:
        super().refresh_groups()
        tree = getattr(self, "groups_tree", None)
        if tree is None or "published" not in tuple(str(x) for x in tree.cget("columns")):
            return
        for item_id in tree.get_children(""):
            tree.set(item_id, "published", self._v2_time_only(tree.set(item_id, "published")))
        if getattr(self, "_inbox_sort_state", None):
            self._apply_inbox_sort()

    def _apply_inbox_sort(self) -> None:
        tree = getattr(self, "groups_tree", None)
        if tree is None:
            return
        ordered = list(tree.get_children(""))
        if not getattr(self, "_inbox_sort_state", None):
            return
        from ...ui.main_window_enhancements import tree_sort_key
        for column, descending in reversed(self._inbox_sort_state):
            nonempty = []
            empty = []
            for item_id in ordered:
                raw = tree.set(item_id, column)
                if column == "published":
                    key = self._v2_time_sort_key(raw)
                    if key[0] == 1:
                        empty.append(item_id)
                    else:
                        nonempty.append((key, item_id))
                else:
                    key = tree_sort_key(raw)
                    if key[0] == 3:
                        empty.append(item_id)
                    else:
                        nonempty.append((key, item_id))
            nonempty.sort(key=lambda item: item[0], reverse=descending)
            ordered = [item_id for _key, item_id in nonempty] + empty
        for position, item_id in enumerate(ordered):
            tree.move(item_id, "", position)
        self._update_inbox_sort_headings(tree)

    def _install_v2_history_retry_button(self) -> None:
        if self.history_retry_button is not None:
            return
        anchor = getattr(self, "history_refresh_selected_button", None)
        parent = getattr(anchor, "master", None)
        if parent is None:
            return
        self.history_retry_button = ttk.Button(
            parent,
            text="ВІДПРАВИТИ ЩЕ РАЗ",
            command=self.retry_failed_history_publication,
            state="disabled",
        )
        self.history_retry_button.pack(side="left", padx=(8, 0))
        detail = getattr(self, "history_detail_tree", None)
        if detail is not None:
            detail.bind("<<TreeviewSelect>>", lambda _event: self._update_v2_history_retry_button(), add="+")
        overview = getattr(self, "history_overview_tree", None)
        if overview is not None:
            overview.bind("<<TreeviewSelect>>", lambda _event: self._update_v2_history_retry_button(), add="+")
        self._update_v2_history_retry_button()

    def refresh_history(self) -> None:
        super().refresh_history()
        self._update_v2_history_retry_button()

    def _selected_history_group_id_v2(self) -> int | None:
        overview = getattr(self, "history_overview_tree", None)
        if overview is None:
            return None
        selected = overview.selection()
        if not selected:
            return None
        token = str(selected[0])
        if token.startswith("group:"):
            try:
                return int(token.split(":", 1)[1])
            except ValueError:
                return None
        return None

    def _retryable_history_summary(self, group_id: int) -> tuple[int, int, list[str]]:
        items = list(getattr(self, "_history_group_details", {}).get(int(group_id), []))
        retryable = 0
        failed = 0
        reasons: list[str] = []
        latest: dict[str, dict] = {}
        for item in items:
            target = (item.get("targets") or [{}])[0] if isinstance(item, dict) else {}
            if not isinstance(target, dict):
                continue
            platform = str(target.get("platform") or "")
            target_id = int(target.get("id") or 0)
            old = latest.get(platform)
            if old is None or int(old.get("id") or 0) < target_id:
                latest[platform] = {**target, "batch_status": str(item.get("batch_status") or "completed")}
        for platform, target in latest.items():
            if str(target.get("status") or "") != "failed":
                continue
            failed += 1
            assessment = assess_failed_target(target)
            if assessment.retryable:
                retryable += 1
            else:
                reasons.append(f"{platform}: {assessment.reason}")
        return retryable, failed, reasons

    def _update_v2_history_retry_button(self) -> None:
        button = getattr(self, "history_retry_button", None)
        if button is None:
            return
        group_id = self._selected_history_group_id_v2()
        if group_id is None:
            button.configure(state="disabled")
            return
        retryable, _failed, _reasons = self._retryable_history_summary(group_id)
        button.configure(state="normal" if retryable else "disabled")

    def retry_failed_history_publication(self) -> None:
        group_id = self._selected_history_group_id_v2()
        if group_id is None:
            self.msg.showinfo("Історія публікацій", "Оберіть матеріал зі статусом помилки.", parent=self.root)
            return
        retryable, failed, reasons = self._retryable_history_summary(group_id)
        if retryable <= 0:
            detail = "\n".join(reasons[:4]) if reasons else "Немає безпечної завершеної помилки для повтору."
            self.msg.showwarning(
                "Повтор публікації заблоковано",
                detail + "\n\nНевідомий або частковий результат не повторюється автоматично, щоб не створити дубль.",
                parent=self.root,
            )
            return
        if not self.msg.askyesno(
            "Відправити ще раз",
            f"Повторити {retryable} невдалу" + (" публікацію" if retryable == 1 else " публікації") +
            " цього матеріалу?\n\nУспішні мережі НЕ повторюються. AI і рерайт НЕ запускаються заново. "
            "Google Drive/медіа перевіряються перед першою зовнішньою публікацією.",
            parent=self.root,
        ):
            return
        try:
            result = self.db.retry_failed_publications(group_id)
            if result.created_batch_ids:
                try:
                    self.worker.clear_auth_blocks("google_drive", *result.created_platforms)
                except Exception:
                    pass
                try:
                    self.worker.wake()
                except Exception:
                    pass
                self.refresh_queue()
                self.refresh_history()
                names = ", ".join(self._destination_labels().get(key, key) for key in result.created_platforms)
                blocked = len(result.blocked)
                suffix = f" · заблоковано як небезпечні: {blocked}" if blocked else ""
                self.set_status(f"Повтор поставлено в негайну публікацію: {names}{suffix}.")
            else:
                detail = "\n".join(f"{key}: {value}" for key, value in result.blocked.items()) or "Безпечних помилок для повтору немає."
                self.msg.showwarning("Повтор не створено", detail, parent=self.root)
        except Exception as exc:
            self._show_error(exc)

    def _build_v2_ai_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="AI")

        selector = ttk.LabelFrame(tab, text="Активний AI backend · жорсткий перемикач", padding=10)
        selector.pack(fill="x", pady=(0, 8))
        ttk.Label(
            selector,
            text="Одночасно працює тільки один backend. Ніякого прихованого fallback між OpenRouter, нашим Router і Agent.",
            foreground="#555",
            wraplength=1250,
        ).pack(anchor="w", pady=(0, 6))
        row = ttk.Frame(selector)
        row.pack(fill="x")
        for label, value in (("OPENROUTER", BACKEND_OPENROUTER), ("AI ROUTER", BACKEND_ROUTER), ("AGENT", BACKEND_AGENT)):
            ttk.Radiobutton(
                row,
                text=label,
                value=value,
                variable=self.v2_backend_var,
                command=lambda selected=value: self._switch_v2_backend(selected),
            ).pack(side="left", padx=(0, 18))
        ttk.Label(row, textvariable=self.v2_ai_status_var, font="TkHeadingFont").pack(side="left", padx=(16, 0))

        openrouter = ttk.LabelFrame(tab, text="1. OpenRouter · автоматичний task routing", padding=10)
        openrouter.pack(fill="x", pady=(0, 8))
        openrouter.columnconfigure(1, weight=1)
        ttk.Label(openrouter, text="API key").grid(row=0, column=0, sticky="w")
        key_box = ttk.Frame(openrouter)
        key_entry = ttk.Entry(key_box, textvariable=self.v2_openrouter_key_var, show="•", width=58)
        key_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(key_box, text="👁", width=3, command=lambda: key_entry.configure(show="" if str(key_entry.cget("show") or "") else "•")).pack(side="left", padx=(3,2))
        ttk.Button(key_box, text="Копіювати", command=lambda: self._copy_secret_value(self.v2_openrouter_key_var, "OpenRouter API key")).pack(side="left")
        key_box.grid(row=0, column=1, sticky="ew", padx=(8, 8))
        ttk.Button(openrouter, text="Зберегти", command=self.save_v2_openrouter_settings).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(openrouter, text="Перевірити", command=self.test_v2_openrouter).grid(row=0, column=3)
        ttk.Label(openrouter, text="Місячний ліміт, $:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(openrouter, textvariable=self.v2_openrouter_budget_var, width=14).grid(row=1, column=1, sticky="w", padx=(8, 8), pady=(6, 0))
        ttk.Label(
            openrouter,
            text=(
                "Моделі не вибирає користувач. Програма сама визначає тип і складність задачі, обирає FAST_CHEAP / BALANCED / STRONG / PREMIUM, "
                "перевіряє QA і за потреби автоматично підсилює модель. OpenRouter маршрутизує хости за ціною та fallback усередині вибраної моделі."
            ),
            wraplength=1250,
            foreground="#555",
        ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(7, 4))
        ttk.Label(openrouter, textvariable=self.v2_openrouter_status_var, foreground="#155724", wraplength=1250).grid(
            row=3, column=0, columnspan=4, sticky="w", pady=(3, 0)
        )

        router = ttk.LabelFrame(tab, text="2. Наш AI Router · прямі провайдери", padding=10)
        router.pack(fill="x", pady=(0, 8))
        router.columnconfigure(1, weight=1)
        self.ai_provider_vars = {}
        secrets = load_provider_secrets()
        for index, (key, label) in enumerate((
            ("gemini_api_key", "Gemini API key"),
            ("nvidia_api_key", "NVIDIA API key"),
            ("groq_api_key", "Groq API key"),
            ("cloudflare_account_id", "Cloudflare Account ID"),
            ("cloudflare_api_token", "Cloudflare API token"),
        )):
            var = tk.StringVar(value=str(getattr(secrets, key)))
            self.ai_provider_vars[key] = var
            ttk.Label(router, text=label).grid(row=index, column=0, sticky="w", pady=2)
            entry_box = ttk.Frame(router)
            entry = ttk.Entry(entry_box, textvariable=var, show="•" if "key" in key or "token" in key else "", width=58)
            entry.pack(side="left", fill="x", expand=True)
            if "key" in key or "token" in key:
                ttk.Button(entry_box, text="👁", width=3, command=lambda widget=entry: widget.configure(show="" if str(widget.cget("show") or "") else "•")).pack(side="left", padx=(3,2))
            ttk.Button(entry_box, text="Копіювати", command=lambda secret_var=var, title=label: self._copy_secret_value(secret_var, title)).pack(side="left")
            entry_box.grid(row=index, column=1, sticky="ew", padx=(8, 8), pady=2)
        options_row = ttk.Frame(router)
        options_row.grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 2))
        self.codex_enabled_var = tk.BooleanVar(value=secrets.codex_enabled)
        self.local_enabled_var = tk.BooleanVar(value=secrets.local_enabled)
        ttk.Checkbutton(options_row, text="Codex/ChatGPT увімкнено", variable=self.codex_enabled_var).pack(side="left", padx=(0, 16))
        ttk.Checkbutton(options_row, text="Локальний AI увімкнено", variable=self.local_enabled_var).pack(side="left")
        ttk.Button(router, text="Зберегти прямі провайдери", command=self.save_ai_provider_keys).grid(row=6, column=0, sticky="w", pady=(6, 0))
        ttk.Button(router, text="Перевірити Router", command=self.test_ai_router_ui).grid(row=6, column=1, sticky="w", padx=(8, 0), pady=(6, 0))
        ttk.Label(router, textvariable=self.v2_router_status_var, wraplength=1250).grid(row=7, column=0, columnspan=2, sticky="w", pady=(4, 0))

        agent = ttk.LabelFrame(tab, text="3. Agent · Codex / ChatGPT", padding=10)
        agent.pack(fill="x", pady=(0, 8))
        ttk.Label(
            agent,
            text=(
                "Окремий backend для Codex. Працює через штатний sign-in; якщо Codex недоступний або вперся в ліміт, "
                "Agent повертає помилку і НЕ переходить самовільно на Router/OpenRouter."
            ),
            foreground="#555",
            wraplength=1250,
        ).pack(anchor="w", pady=(0, 5))
        agent_buttons = ttk.Frame(agent)
        agent_buttons.pack(fill="x")
        ttk.Button(agent_buttons, text="ПЕРЕВІРИТИ CODEX", command=self.test_v2_agent).pack(side="left")
        if hasattr(self, "ensure_codex_ready_ui"):
            ttk.Button(agent_buttons, text="ВСТАНОВИТИ / ОНОВИТИ CODEX", command=self.ensure_codex_ready_ui).pack(side="left", padx=(6, 0))
        if hasattr(self, "start_codex_login_ui"):
            ttk.Button(agent_buttons, text="УВІЙТИ", command=self.start_codex_login_ui).pack(side="left", padx=(6, 0))
        ttk.Label(agent, textvariable=self.v2_agent_status_var, wraplength=1250).pack(anchor="w", pady=(5, 0))

        ttk.Label(tab, text="Використання OpenRouter:", font="TkHeadingFont").pack(anchor="w", pady=(4, 2))
        self.v2_usage_var = tk.StringVar(value="")
        ttk.Label(tab, textvariable=self.v2_usage_var, wraplength=1250).pack(anchor="w")

    def _copy_secret_value(self, variable: tk.StringVar, title: str) -> None:
        value = str(variable.get() or "").strip()
        if not value:
            self.msg.showinfo(title, "Поле порожнє.", parent=self.root)
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(value)
        self.root.update_idletasks()
        self.set_status(f"{title}: скопійовано в буфер обміну.")

    def _switch_v2_backend(self, value: str) -> None:
        self.v2_backend_settings.active_backend = value
        self.v2_backend_settings = save_backend_settings(self.v2_backend_settings)
        self.v2_ai_status_var.set(backend_status(self.v2_backend_settings.active_backend))
        self.set_status(f"AI backend: {self.v2_backend_settings.active_backend}.")

    def save_v2_openrouter_settings(self) -> None:
        try:
            budget = float(str(self.v2_openrouter_budget_var.get()).replace(",", "."))
            save_openrouter_api_key(self.v2_openrouter_key_var.get())
            self.v2_backend_settings.openrouter_monthly_budget_usd = budget
            self.v2_backend_settings = save_backend_settings(self.v2_backend_settings)
            self.refresh_v2_ai_status()
            self.set_status("OpenRouter: ключ і бюджет збережено.")
        except Exception as exc:
            self._show_error(exc)

    def test_v2_openrouter(self) -> None:
        try:
            self.save_v2_openrouter_settings()
        except Exception:
            return
        def action() -> object:
            backend = OpenRouterBackend(load_backend_settings())
            return backend.test_connection()
        def success(result: object) -> None:
            self.v2_openrouter_status_var.set(str(result))
            self.refresh_v2_ai_status()
        self.run_async(action, success, label="Перевіряю OpenRouter", done_label="OpenRouter перевірено")

    def test_v2_agent(self) -> None:
        self.run_async(
            lambda: test_active_backend(BACKEND_AGENT, timeout_seconds=45),
            lambda result: self.v2_agent_status_var.set(str(result)),
            label="Перевіряю Agent / Codex",
            done_label="Agent перевірено",
        )

    def refresh_v2_ai_status(self) -> None:
        settings = load_backend_settings()
        self.v2_backend_settings = settings
        self.v2_backend_var.set(settings.active_backend)
        self.v2_ai_status_var.set(backend_status(settings.active_backend))
        self.v2_openrouter_status_var.set(backend_status(BACKEND_OPENROUTER, openrouter_key=self.v2_openrouter_key_var.get()))
        try:
            self.v2_router_status_var.set(provider_health_text())
        except Exception as exc:
            self.v2_router_status_var.set(f"AI Router: помилка стану · {exc}")
        try:
            agent = inspect_codex_cached()
            cached = peek_codex_status_cache()
            if cached is None:
                self.v2_agent_status_var.set("Agent / Codex: стан ще не перевірено; натисніть «ПЕРЕВІРИТИ CODEX».")
            else:
                self.v2_agent_status_var.set(f"Agent / Codex: {agent.detail}")
        except Exception as exc:
            self.v2_agent_status_var.set(f"Agent / Codex: {exc}")
        summary = usage_summary(settings.openrouter_monthly_budget_usd)
        self.v2_usage_var.set(
            f"Сьогодні: {summary['today_requests']} запитів · ${summary['today_cost']:.4f} · "
            f"місяць: {summary['month_requests']} запитів · ${summary['month_cost']:.4f} / ${summary['budget']:.2f} · "
            f"залишок: ${summary['remaining']:.2f}"
        )

    def _schedule_v2_status_refresh(self) -> None:
        try:
            if self.stop_event.is_set():
                return
            self.refresh_v2_ai_status()
            if self.v2_supervisor is not None:
                self.v2_supervisor_status_var.set(self.v2_supervisor.status_text())
            self._v2_refresh_after_id = self.root.after(30000, self._schedule_v2_status_refresh)
        except Exception:
            self._v2_refresh_after_id = None

    def _build_v2_supervisor_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Supervisor")
        identity = instance_identity()
        ttk.Label(tab, text="TECH SUPERVISOR · локальний діагност і окремий контур телеметрії", font="TkHeadingFont").pack(anchor="w")
        ttk.Label(
            tab,
            text=(
                "Supervisor читає статус локально, відрізняє збій програми від зовнішньої помилки, формує Markdown-звіт через OpenRouter "
                "і синхронізує status/incident/diagnostics у Google Drive. Це окремий сервісний контур, не частина звичайного публікаційного worker-а."
            ),
            wraplength=1250,
            foreground="#555",
        ).pack(anchor="w", pady=(6, 10))
        ttk.Label(tab, text=f"Instance: {identity.instance_name}\nID: {identity.instance_id}\nКомп'ютер: {identity.hostname}").pack(anchor="w")
        ttk.Label(tab, textvariable=self.v2_supervisor_status_var, foreground="#155724", wraplength=1250).pack(anchor="w", pady=(10, 8))
        settings = load_backend_settings()
        ttk.Label(tab, text=f"Drive root: {settings.supervisor_drive_root} / RESUME").pack(anchor="w")
        ttk.Label(tab, text="Локально: Data\\supervisor\\status.json, incident.json, diagnostics та Markdown-звіти.", foreground="#666").pack(anchor="w", pady=(4, 8))
        ttk.Button(tab, text="Зробити діагностичний звіт зараз", command=self.run_v2_supervisor_report).pack(anchor="w")

    def run_v2_supervisor_report(self) -> None:
        if self.v2_supervisor is None:
            self.msg.showwarning("Supervisor", "Supervisor ще не запущено.", parent=self.root)
            return
        def action() -> object:
            return self.v2_supervisor.run_once(force_report=True)
        def success(_result: object) -> None:
            self.v2_supervisor_status_var.set(self.v2_supervisor.status_text())
            self.set_status("Supervisor: діагностичний звіт сформовано.")
        self.run_async(
            action,
            success,
            label="Supervisor формує діагностику",
            done_label="Supervisor завершив звіт",
            timeout_seconds=150,
            timeout_message="Supervisor не завершив ручний звіт за 150 секунд.",
            modal_errors=False,
            modal_timeout=False,
            timeout_is_error=False,
        )

    def _finish_v2_close_when_publication_safe(self) -> None:
        worker = getattr(self, "worker", None)
        active = worker.active_batch_id() if worker is not None and hasattr(worker, "active_batch_id") else None
        if active is not None:
            self.set_status(
                f"Закриття: пакет #{active} завершує поточний зовнішній запис. "
                "Новий target не буде розпочато."
            )
            self._v2_close_wait_after_id = self.root.after(250, self._finish_v2_close_when_publication_safe)
            return
        self._v2_close_wait_after_id = None
        self.settings_dirty = False
        super().close()

    def close(self) -> None:
        if getattr(self, "_v2_graceful_closing", False):
            return
        if getattr(self, "_closing", False):
            return

        if getattr(self, "settings_dirty", False):
            answer = self.msg.askyesnocancel(
                "Незбережені налаштування",
                "У налаштуваннях є незбережені зміни. Зберегти їх перед закриттям?",
                parent=self.root,
            )
            if answer is None:
                return
            if answer and not self.save_settings(show_confirmation=False):
                return
            self.settings_dirty = False

        self._v2_graceful_closing = True
        if self._v2_refresh_after_id is not None:
            try:
                self.root.after_cancel(self._v2_refresh_after_id)
            except tk.TclError:
                pass
            self._v2_refresh_after_id = None
        if getattr(self, "_autocollect_watchdog_id", None) is not None:
            try:
                self.root.after_cancel(self._autocollect_watchdog_id)
            except tk.TclError:
                pass
            self._autocollect_watchdog_id = None

        worker = getattr(self, "worker", None)
        active = worker.active_batch_id() if worker is not None and hasattr(worker, "active_batch_id") else None
        if active is None:
            self._finish_v2_close_when_publication_safe()
            return

        self.stop_event.set()
        try:
            worker.request_cancel(active, reason="application_close")
            worker.wake()
        except Exception:
            pass
        self.set_status(
            f"Закриття: чекаю безпечного завершення публікації #{active}. "
            "Не вимикайте процес примусово, щоб не отримати невідомий результат."
        )
        self._v2_close_wait_after_id = self.root.after(250, self._finish_v2_close_when_publication_safe)
