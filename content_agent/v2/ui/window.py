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
from ...codex_runtime import inspect_codex_cached
from ...inbox_layout_v1_3_1_rc8 import inbox_layout_path, save_widths
from ...ui.v1_4_rc30_window import MainWindow as Rc30MainWindow
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
from ..supervisor.runtime import SupervisorRuntime
from ..publishing.retry import assess_failed_target


class MainWindow(Rc30MainWindow):
    """V2 compatibility shell: RC30 behavior plus isolated V2 services.

    The old UI/runtime remains the functional baseline in rc1. New functionality
    is attached only through explicit V2 modules so the legacy chain can be retired
    incrementally instead of rewritten in one risky step.
    """

    VERSION_LABEL = "2.0.0-rc2"

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
        self.v2_supervisor: SupervisorRuntime | None = None

        try:
            self.v2_openrouter_key_var.set(load_openrouter_api_key())
        except Exception:
            self.v2_openrouter_key_var.set("")

        super().__init__(root, database, config)
        self._apply_v2_inbox_contract()
        self._install_v2_inbox_reset_button()
        self._install_v2_history_retry_button()
        self._build_v2_ai_tab()
        self._build_v2_supervisor_tab()
        self._apply_v2_labels()
        self.refresh_v2_ai_status()

        self.v2_supervisor = SupervisorRuntime(self, database, config, version=self.VERSION_LABEL)
        self.v2_supervisor.start()
        self._schedule_v2_status_refresh()

    def _apply_v2_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v2.0.0-rc2")

    def _apply_language(self, refresh: bool = True) -> None:
        super()._apply_language(refresh=refresh)
        self._apply_v2_labels()
        if hasattr(self, "groups_tree"):
            self._apply_v2_inbox_contract()

    # ------------------------------------------------------------------
    # Inbox contract: source count and current-day time are independent columns.
    # ------------------------------------------------------------------
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
        desired = tuple(item for item in ("id", "status", "title", "topic", "sources", "published", "score", "history") if item in columns)
        tree.configure(displaycolumns=desired)
        tree.column("sources", width=max(90, int(tree.column("sources", "width") or 0)), minwidth=75, stretch=False, anchor="center")
        tree.column("published", width=max(110, min(145, int(tree.column("published", "width") or 110))), minwidth=90, stretch=False, anchor="center")
        labels = self._inbox_headings()
        # Re-install the inherited multi-sort callbacks after fixing labels.
        if hasattr(self, "_install_inbox_multisort_headings"):
            self._install_inbox_multisort_headings(tree)
        for column in ("sources", "published"):
            try:
                base = labels[column]
                # _update_inbox_sort_headings may append an arrow immediately.
                state = getattr(self, "_inbox_sort_state", [])
                match = next((item for item in state if item[0] == column), None)
                if match:
                    index = [x[0] for x in state].index(column) + 1
                    base += f" {index}{'▼' if match[1] else '▲'}"
                tree.heading(column, text=base)
            except Exception:
                pass

    def _install_v2_inbox_reset_button(self) -> None:
        if self._v2_inbox_reset_button is not None:
            return
        bar = getattr(self, "_rc14_inbox_tools_frame", None)
        if bar is None:
            return
        button = ttk.Button(bar, text="Відновити стандартні колонки", command=self.reset_v2_inbox_columns)
        button.pack(side="right", padx=(8, 0))
        self._v2_inbox_reset_button = button

    def reset_v2_inbox_columns(self) -> None:
        widths = {
            "id": 72,
            "status": 82,
            "title": 520,
            "topic": 130,
            "sources": 90,
            "published": 115,
            "score": 150,
            "history": 180,
        }
        try:
            save_widths(widths, inbox_layout_path())
        except Exception:
            pass
        tree = getattr(self, "groups_tree", None)
        if tree is not None:
            for column, width in widths.items():
                if column in tuple(tree.cget("columns")):
                    minwidth = 90 if column == "published" else 75 if column == "sources" else 45
                    tree.column(column, width=width, minwidth=minwidth, stretch=False)
            self._apply_v2_inbox_contract()
        self.set_status("Колонки Вхідних відновлено. «Джерел» і «Час» незалежні.")

    @staticmethod
    def _v2_time_only(value: object) -> str:
        """Render Inbox publication time only; the Inbox contains current-day news."""
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
        """Keep inherited multi-sort, but sort the current-day Time column by seconds."""
        tree = getattr(self, "groups_tree", None)
        if tree is None:
            return
        ordered = list(tree.get_children(""))
        if not getattr(self, "_inbox_sort_state", None):
            return
        # Import locally to avoid coupling V2 UI startup to the legacy sorter.
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

    # ------------------------------------------------------------------
    # Publication history recovery: retry only known failed destinations.
    # ------------------------------------------------------------------
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
                # A manual retry means the operator has had a chance to repair
                # credentials. Clear process-local auth breakers before wake-up;
                # the normal preflight will validate Drive/platform credentials.
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

    # ------------------------------------------------------------------
    # AI tab: one hard backend switch, three isolated backends.
    # ------------------------------------------------------------------
    def _build_v2_ai_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Нейронки")

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
        ttk.Entry(openrouter, textvariable=self.v2_openrouter_key_var, show="•", width=72).grid(row=0, column=1, sticky="ew", padx=(8, 8))
        ttk.Button(openrouter, text="Зберегти", command=self.save_v2_openrouter_settings).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(openrouter, text="Тест OpenRouter", command=self.test_v2_openrouter).grid(row=0, column=3)
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

        router = ttk.LabelFrame(tab, text="2. Наш AI Router · прямі провайдери / локальний резерв", padding=10)
        router.pack(fill="x", pady=(0, 8))
        ttk.Label(
            router,
            text="NVIDIA, Gemini, Groq, Cloudflare, Local та Codex використовуються тільки коли активний режим AI ROUTER.",
            foreground="#555",
        ).pack(anchor="w")
        ttk.Label(router, textvariable=self.v2_router_status_var, wraplength=1250).pack(anchor="w", pady=(5, 5))
        actions = ttk.Frame(router)
        actions.pack(fill="x")
        ttk.Button(actions, text="Зберегти ключі Router", command=self.save_ai_provider_settings).pack(side="left")
        ttk.Button(actions, text="Тест AI Router", command=self.test_ai_router_ui).pack(side="left", padx=(6, 0))
        ttk.Button(actions, text="Скинути cooldown", command=self.clear_ai_router_cooldowns_ui).pack(side="left", padx=(6, 0))
        ttk.Label(actions, text="Ключі редагуються також у старому блоці Налаштувань RC30; це один і той самий secure store.", foreground="#666").pack(side="left", padx=(12, 0))

        agent = ttk.LabelFrame(tab, text="3. Agent · ChatGPT/Codex account backend", padding=10)
        agent.pack(fill="x", pady=(0, 8))
        ttk.Label(
            agent,
            text="У цьому режимі токенові провайдери не використовуються. RC1 Agent backend = локально авторизований Codex/ChatGPT runtime.",
            foreground="#555",
        ).pack(anchor="w")
        ttk.Label(agent, textvariable=self.v2_agent_status_var, wraplength=1250).pack(anchor="w", pady=(5, 5))
        row2 = ttk.Frame(agent)
        row2.pack(fill="x")
        ttk.Button(row2, text="Перевірити Codex", command=self.check_codex_ui).pack(side="left")
        ttk.Button(row2, text="Встановити / відновити Codex", command=self.install_codex_ui).pack(side="left", padx=(6, 0))
        ttk.Button(row2, text="Увійти через ChatGPT", command=self.login_codex_ui).pack(side="left", padx=(6, 0))
        ttk.Button(row2, text="Тест активного backend", command=self.test_v2_active_backend).pack(side="left", padx=(16, 0))

    def check_codex_ui(self) -> None:
        # A live Codex probe is an AI execution. Under the hard-switch contract
        # OpenRouter mode must not touch Codex at all. We still allow a local
        # install/authentication inspection because it consumes no model request.
        if load_backend_settings().active_backend == BACKEND_OPENROUTER:
            try:
                codex = inspect_codex_cached(max_age_seconds=1.0, force=True)
                if not codex.installed:
                    text = "Agent/Codex: не встановлено"
                elif not codex.authenticated:
                    text = f"Agent/Codex {codex.version}: встановлено, потрібен вхід через ChatGPT"
                else:
                    account = f" · {codex.account_label}" if codex.account_label else ""
                    text = f"Agent/Codex {codex.version}: авторизований{account}; живий AI-запит не виконувався, бо активний OPENROUTER"
                self.v2_agent_status_var.set(text)
                self.set_status(text)
            except Exception as exc:
                self._show_error(exc)
            return
        return super().check_codex_ui()

    def test_ai_router_ui(self) -> None:
        if load_backend_settings().active_backend != BACKEND_ROUTER:
            self.msg.showwarning(
                "Жорсткий AI backend",
                "AI Router зараз не активний. Для живого тесту спочатку перемкніть активний backend на AI ROUTER.",
                parent=self.root,
            )
            return
        return super().test_ai_router_ui()

    def test_local_ai_ui(self) -> None:
        if load_backend_settings().active_backend != BACKEND_ROUTER:
            self.msg.showwarning(
                "Жорсткий AI backend",
                "Локальний AI є частиною AI Router і не запускається, поки активний інший backend.",
                parent=self.root,
            )
            return
        return super().test_local_ai_ui()

    def _switch_v2_backend(self, selected: str) -> None:
        current = load_backend_settings()
        if selected == BACKEND_OPENROUTER and not self.v2_openrouter_key_var.get().strip():
            self.v2_backend_var.set(current.active_backend)
            self.msg.showwarning("OpenRouter", "Спочатку введіть і збережіть OpenRouter API key.", parent=self.root)
            return
        try:
            budget = float(self.v2_openrouter_budget_var.get().replace(",", "."))
        except Exception:
            budget = current.openrouter_monthly_budget_usd
        saved = save_backend_settings(AIBackendSettings(
            active_backend=selected,
            openrouter_strategy=current.openrouter_strategy,
            openrouter_monthly_budget_usd=budget,
            supervisor_enabled=current.supervisor_enabled,
            supervisor_interval_seconds=current.supervisor_interval_seconds,
            supervisor_summary_interval_minutes=current.supervisor_summary_interval_minutes,
            supervisor_drive_root=current.supervisor_drive_root,
        ))
        self.v2_backend_settings = saved
        self.v2_backend_var.set(saved.active_backend)
        self.refresh_v2_ai_status()
        self.set_status(f"AI backend перемкнено жорстко: {saved.active_backend.upper()}.")

    def save_v2_openrouter_settings(self) -> None:
        try:
            save_openrouter_api_key(self.v2_openrouter_key_var.get())
            current = load_backend_settings()
            budget = float(self.v2_openrouter_budget_var.get().replace(",", "."))
            save_backend_settings(AIBackendSettings(
                active_backend=current.active_backend,
                openrouter_strategy=current.openrouter_strategy,
                openrouter_monthly_budget_usd=budget,
                supervisor_enabled=current.supervisor_enabled,
                supervisor_interval_seconds=current.supervisor_interval_seconds,
                supervisor_summary_interval_minutes=current.supervisor_summary_interval_minutes,
                supervisor_drive_root=current.supervisor_drive_root,
            ))
            self.refresh_v2_ai_status()
            self.set_status("OpenRouter налаштування збережено.")
        except Exception as exc:
            self._show_error(exc)

    def test_v2_openrouter(self) -> None:
        self.save_v2_openrouter_settings()
        settings = load_backend_settings()
        backend = OpenRouterBackend(settings)

        def success(result: object) -> None:
            self.refresh_v2_ai_status()
            self.set_status(str(result))

        self.run_async(
            backend.probe,
            success,
            label="OpenRouter: живий тест і автоматичний вибір моделі",
            done_label="OpenRouter перевірено",
            timeout_seconds=60,
            timeout_message="OpenRouter не завершив тест за 60 секунд.",
            modal_errors=True,
            modal_timeout=True,
            timeout_is_error=True,
        )

    def test_v2_active_backend(self) -> None:
        def success(result: object) -> None:
            self.refresh_v2_ai_status()
            self.set_status(str(result))
        self.run_async(
            test_active_backend,
            success,
            label="Перевіряю активний AI backend",
            done_label="Активний AI backend перевірено",
            timeout_seconds=90,
            timeout_message="Активний backend не завершив тест за 90 секунд.",
            modal_errors=True,
            modal_timeout=True,
            timeout_is_error=True,
        )

    def refresh_v2_ai_status(self) -> None:
        try:
            status = backend_status()
            active = str(status.get("active_backend") or "router").upper()
            self.v2_ai_status_var.set(f"АКТИВНИЙ: {active}")
            usage = usage_summary(backend="openrouter")
            configured = bool(status.get("openrouter_configured"))
            self.v2_openrouter_status_var.set(
                f"OpenRouter: {'налаштовано' if configured else 'ключ не задано'} · "
                f"сьогодні ${float(usage.get('today_cost') or 0):.4f} / {int(usage.get('today_requests') or 0)} запитів · "
                f"місяць ${float(usage.get('month_cost') or 0):.4f} · "
                f"tokens in/out {int(usage.get('month_prompt_tokens') or 0):,}/{int(usage.get('month_completion_tokens') or 0):,}"
            )
        except Exception as exc:
            self.v2_openrouter_status_var.set(f"OpenRouter status: {exc}")
        try:
            self.v2_router_status_var.set(provider_health_text())
        except Exception as exc:
            self.v2_router_status_var.set(f"AI Router status: {exc}")
        try:
            codex = inspect_codex_cached(max_age_seconds=30.0, force=False)
            if not codex.installed:
                text = "Agent/Codex: не встановлено"
            elif not codex.authenticated:
                text = f"Agent/Codex {codex.version}: потрібен вхід через ChatGPT"
            else:
                account = f" · {codex.account_label}" if codex.account_label else ""
                text = f"Agent/Codex {codex.version}: авторизований{account}"
            self.v2_agent_status_var.set(text)
        except Exception as exc:
            self.v2_agent_status_var.set(f"Agent status: {exc}")

    def _schedule_v2_status_refresh(self) -> None:
        if getattr(self, "_closing", False):
            return
        self.refresh_v2_ai_status()
        if self.v2_supervisor is not None:
            self.v2_supervisor_status_var.set(self.v2_supervisor.status_text())
        try:
            self._v2_refresh_after_id = self.root.after(10000, self._schedule_v2_status_refresh)
        except tk.TclError:
            self._v2_refresh_after_id = None

    # ------------------------------------------------------------------
    # Supervisor UI. Monitoring logic lives in supervisor/, never here.
    # ------------------------------------------------------------------
    def _build_v2_supervisor_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Нагляд")
        identity = instance_identity()
        ttk.Label(tab, text="Автоматичний Supervisor V2", font="TkHeadingFont").pack(anchor="w")
        ttk.Label(
            tab,
            text=(
                "Локально збирає health/помилки/чергу/джерела/AI/UI/БД. OpenRouter використовується лише як незалежний аналізатор діагностики. "
                "Звіти двох Content Tool розділяються стабільним instance ID і вивантажуються в спільну папку RESUME на Google Drive."
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

    def close(self) -> None:
        if self._v2_refresh_after_id is not None:
            try:
                self.root.after_cancel(self._v2_refresh_after_id)
            except tk.TclError:
                pass
            self._v2_refresh_after_id = None
        super().close()
