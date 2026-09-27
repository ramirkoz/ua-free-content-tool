from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .window import MainWindow as V2MainWindow
from ...destinations_v1_4 import load_instagram_catalog


class MainWindow(V2MainWindow):
    """RC42: compact Instagram settings while keeping per-account destinations.

    The multi-account destination model already lives in destinations_v1_4. This
    window only fixes the settings UX: the account table is collapsed by default,
    and discovery remains the single source of truth for all Instagram profiles
    reachable through the connected Facebook Pages.
    """

    def _rebuild_instagram_section_rc6(self) -> None:
        old = self._find_platform_frame("Instagram")
        facebook = self._find_platform_frame("Facebook Pages") or self._find_platform_frame("Meta / Facebook Pages")
        if facebook is None:
            return
        parent = facebook.master
        if old is not None:
            old.destroy()

        # Keep the encrypted legacy fields alive for backward compatibility. They
        # are intentionally not exposed as the primary UI anymore because the
        # current destination catalog supports many Instagram profiles.
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
                "програма використовує вже збережений зашифрований Page Access Token відповідної сторінки."
            ),
            foreground="#666",
            wraplength=1200,
        ).pack(anchor="w")

        # Critical UX contract: the large account table is not part of the normal
        # Settings height until the operator explicitly opens it.
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
            if button is not None:
                button.configure(text="Сховати акаунти ▴")
        else:
            frame.pack_forget()
            if button is not None:
                button.configure(text="Показати акаунти ▾")

    def _refresh_instagram_accounts_view(self) -> None:
        super()._refresh_instagram_accounts_view()
        rows = load_instagram_catalog()
        button = getattr(self, "instagram_details_button", None)
        if button is not None:
            suffix = f" ({len(rows)})" if rows else ""
            button.configure(
                text=("Сховати акаунти ▴" if getattr(self, "_instagram_details_open", False) else "Показати акаунти ▾")
                + suffix
            )
