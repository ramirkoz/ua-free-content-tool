from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..ai_router import install_runtime as install_router_runtime
from ..codex_runtime import install_codex as install_codex_safe
from ..destinations_v1_4 import load_instagram_catalog
from ..restart_helper_v1_4_rc29 import schedule_delayed_restart
from ..rewrite_pipeline_v1_4_rc27 import install_runtime as install_rewrite_runtime
from ..version import APP_VERSION
from .v1_4_rc29_window import MainWindow as Rc29MainWindow


class MainWindow(Rc29MainWindow):
    """Current legacy compatibility window with canonical AI and RC42 Instagram UX."""

    VERSION_LABEL = APP_VERSION

    def __init__(self, root, database, config) -> None:
        install_router_runtime()
        install_rewrite_runtime()
        super().__init__(root, database, config)
        install_router_runtime()
        install_rewrite_runtime()
        self._apply_v14_labels()
        self.refresh_ai_component_status()

    def _apply_v14_labels(self) -> None:
        self.root.title(f"UA FREE Content Tool — v{APP_VERSION}")

    def _apply_language(self, refresh: bool = True) -> None:
        super()._apply_language(refresh=refresh)
        self._apply_v14_labels()

    # ------------------------------------------------------------------
    # RC42 Instagram settings: compact by default, multi-account aware.
    # The actual account catalog and per-account destination routing already
    # live in destinations_v1_4 / instagram_accounts_v1_4; this only fixes the
    # settings UX that was still consuming permanent vertical space.
    # ------------------------------------------------------------------
    def _rebuild_instagram_section_rc6(self) -> None:
        old = self._find_platform_frame("Instagram")
        facebook = self._find_platform_frame("Meta / Facebook Pages") or self._find_platform_frame("Facebook Pages")
        if facebook is None:
            return
        parent = facebook.master
        if old is not None:
            old.destroy()

        # Retain legacy encrypted fields for compatibility with old Data. The UI
        # does not force one global Instagram ID/token anymore.
        self.settings_vars.setdefault("instagram_user_id", tk.StringVar(value=self.config.instagram_user_id))
        self.settings_vars.setdefault("instagram_token", tk.StringVar(value=self.config.instagram_token))
        self.instagram_status_var = tk.StringVar(value="")
        self._instagram_details_open = False

        frame = ttk.LabelFrame(parent, text="Instagram", padding=8)
        frame.pack(fill="x", pady=4, after=facebook)
        self.instagram_settings_frame = frame

        header = ttk.Frame(frame)
        header.pack(fill="x")
        ttk.Button(
            header,
            text="Знайти / оновити всі акаунти",
            command=self.connect_instagram,
        ).pack(side="left")
        self.instagram_details_button = ttk.Button(
            header,
            text="Показати акаунти ▾",
            command=self._toggle_instagram_details_rc42,
        )
        self.instagram_details_button.pack(side="left", padx=(6, 0))
        ttk.Button(
            header,
            text="Вимкнути",
            command=lambda: self._disconnect_social("instagram"),
        ).pack(side="left", padx=(6, 0))
        ttk.Label(header, textvariable=self.instagram_status_var, foreground="#555").pack(
            side="left", padx=(10, 0)
        )

        ttk.Label(
            frame,
            text=(
                "Кожен знайдений Instagram-профіль є окремим призначенням. "
                "Перед публікацією можна вибрати один або кілька профілів окремими прапорцями."
            ),
            foreground="#666",
            wraplength=1200,
        ).pack(anchor="w", pady=(5, 0))

        details = ttk.Frame(frame)
        self.instagram_details_frame = details
        columns = ("account", "page", "type")
        self.instagram_accounts_tree = ttk.Treeview(details, columns=columns, show="headings", height=4)
        self.instagram_accounts_tree.heading("account", text="Instagram")
        self.instagram_accounts_tree.heading("page", text="Пов’язана Facebook Page")
        self.instagram_accounts_tree.heading("type", text="Тип")
        self.instagram_accounts_tree.column("account", width=260, anchor="w")
        self.instagram_accounts_tree.column("page", width=420, anchor="w")
        self.instagram_accounts_tree.column("type", width=130, anchor="w")
        self.instagram_accounts_tree.pack(fill="x", pady=(7, 3))
        ttk.Label(
            details,
            text=(
                "Окремі Instagram-токени тут не дублюються. Для профілів, пов’язаних із Facebook Pages, "
                "використовується вже збережений зашифрований Page Access Token відповідної сторінки."
            ),
            foreground="#666",
            wraplength=1200,
        ).pack(anchor="w")

        # The list must not permanently shrink the rest of Settings.
        details.pack_forget()
        self._refresh_instagram_accounts_view()

    def _toggle_instagram_details_rc42(self) -> None:
        frame = getattr(self, "instagram_details_frame", None)
        button = getattr(self, "instagram_details_button", None)
        if frame is None:
            return
        self._instagram_details_open = not bool(getattr(self, "_instagram_details_open", False))
        if self._instagram_details_open:
            frame.pack(fill="x", pady=(2, 0))
        else:
            frame.pack_forget()
        if button is not None:
            self._refresh_instagram_details_button_rc42()

    def _refresh_instagram_details_button_rc42(self) -> None:
        button = getattr(self, "instagram_details_button", None)
        if button is None:
            return
        count = len(load_instagram_catalog())
        suffix = f" ({count})" if count else ""
        if bool(getattr(self, "_instagram_details_open", False)):
            button.configure(text=f"Сховати акаунти ▴{suffix}")
        else:
            button.configure(text=f"Показати акаунти ▾{suffix}")

    def _refresh_instagram_accounts_view(self) -> None:
        super()._refresh_instagram_accounts_view()
        self._refresh_instagram_details_button_rc42()

    def install_codex_ui(self) -> None:
        def success(_result: object) -> None:
            from ..ai_router import clear_router_cooldowns

            clear_router_cooldowns()
            self.set_status("Codex runtime встановлено. Автоматично перезапускаю програму…")
            try:
                schedule_delayed_restart()
            except Exception as exc:
                self._show_error(RuntimeError(
                    "Codex runtime встановлено, але автоматичний перезапуск не вдався. "
                    f"Закрийте й відкрийте програму вручну. Деталі: {exc}"
                ))
                return
            self.root.after(250, self.root.destroy)

        self.run_async(
            install_codex_safe,
            success,
            label="Встановлюю Codex у новий runtime",
            done_label="Codex runtime підготовлено до перезапуску",
            timeout_seconds=660,
            timeout_message="Встановлення Codex не завершилося за 11 хвилин.",
            modal_errors=True,
            modal_timeout=True,
            timeout_is_error=True,
        )