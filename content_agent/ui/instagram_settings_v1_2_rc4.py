from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

from ..instagram_api_v1_2_rc4 import inspect_instagram_profile


class InstagramSettingsMixin:
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[misc]
        self._upgrade_instagram_settings()
        if self.config.instagram_enabled:  # type: ignore[attr-defined]
            self.root.after(5000, self._auto_check_instagram)  # type: ignore[attr-defined]

    def _find_instagram_box(self) -> ttk.LabelFrame | None:
        stack = [self.root]  # type: ignore[attr-defined]
        found: ttk.LabelFrame | None = None
        while stack:
            parent = stack.pop()
            for child in parent.winfo_children():
                stack.append(child)
                if isinstance(child, ttk.LabelFrame) and str(child.cget("text")) == "Instagram":
                    found = child
        return found

    def _upgrade_instagram_settings(self) -> None:
        box = self._find_instagram_box()
        if box is None:
            return
        for child in box.winfo_children():
            child.destroy()
        self.instagram_enabled_var = tk.BooleanVar(value=self.config.instagram_enabled)  # type: ignore[attr-defined]
        self.settings_vars["instagram_user_id"] = tk.StringVar(value=self.config.instagram_user_id)  # type: ignore[attr-defined]
        self.settings_vars["instagram_token"] = tk.StringVar(value=self.config.instagram_token)  # type: ignore[attr-defined]
        self.instagram_status_var = tk.StringVar(value=self._instagram_status_text())
        ttk.Checkbutton(
            box,
            text="Увімкнути Instagram",
            variable=self.instagram_enabled_var,
            command=self._toggle_instagram_controls,
        ).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(box, text="Instagram User ID").grid(row=1, column=0, sticky="w", pady=(7, 0))
        user_entry = ttk.Entry(box, textvariable=self.settings_vars["instagram_user_id"], width=32)  # type: ignore[attr-defined]
        user_entry.grid(row=2, column=0, sticky="ew", padx=(0, 8))
        ttk.Label(box, text="Instagram Access Token").grid(row=1, column=1, sticky="w", pady=(7, 0))
        token_entry = ttk.Entry(box, textvariable=self.settings_vars["instagram_token"], show="•", width=56)  # type: ignore[attr-defined]
        token_entry.grid(row=2, column=1, sticky="ew", padx=(0, 8))
        check_button = ttk.Button(box, text="Перевірити Instagram", command=self.connect_instagram)
        check_button.grid(row=2, column=2, sticky="w")
        ttk.Label(box, textvariable=self.instagram_status_var, foreground="#555").grid(
            row=3, column=0, columnspan=3, sticky="ew", pady=(5, 2)
        )
        ttk.Label(
            box,
            text="Прапорець вимкнено — Instagram не використовується і токен не перевіряється.",
            foreground="#666",
        ).grid(row=4, column=0, columnspan=3, sticky="ew")
        self._instagram_control_widgets = (user_entry, token_entry, check_button)
        self.instagram_enabled_var.trace_add("write", self._mark_settings_dirty)  # type: ignore[attr-defined]
        self.settings_vars["instagram_user_id"].trace_add("write", self._mark_settings_dirty)  # type: ignore[attr-defined]
        self.settings_vars["instagram_token"].trace_add("write", self._mark_settings_dirty)  # type: ignore[attr-defined]
        self._toggle_instagram_controls()

    def _instagram_status_text(self) -> str:
        if not self.config.instagram_enabled:  # type: ignore[attr-defined]
            return "Вимкнено. Токен не перевіряється."
        if self.config.platform_ready("instagram"):  # type: ignore[attr-defined]
            name = self.config.instagram_profile_name or self.config.instagram_user_id  # type: ignore[attr-defined]
            return f"Підключено: {name}"
        return "Увімкнено, але підключення ще не перевірено."

    def _toggle_instagram_controls(self) -> None:
        enabled = bool(getattr(self, "instagram_enabled_var", None) and self.instagram_enabled_var.get())
        for widget in getattr(self, "_instagram_control_widgets", ()):
            try:
                widget.configure(state="normal" if enabled else "disabled")
            except tk.TclError:
                pass
        if hasattr(self, "instagram_status_var"):
            self.instagram_status_var.set(
                self._instagram_status_text() if enabled else "Вимкнено. Токен не перевіряється."
            )
        if hasattr(self, "_rebuild_target_controls"):
            self._rebuild_target_controls()  # type: ignore[attr-defined]

    def connect_instagram(self) -> None:
        if not self.instagram_enabled_var.get():
            self.instagram_status_var.set("Вимкнено. Токен не перевіряється.")
            return
        user_id = self.settings_vars["instagram_user_id"].get().strip()  # type: ignore[attr-defined]
        token = self.settings_vars["instagram_token"].get().strip()  # type: ignore[attr-defined]
        self.instagram_status_var.set("Перевіряю Instagram…")

        def success(result: object) -> None:
            profile = result
            self.config.instagram_enabled = True  # type: ignore[attr-defined]
            self.config.instagram_user_id = profile.user_id  # type: ignore[attr-defined]
            self.config.instagram_profile_name = profile.username  # type: ignore[attr-defined]
            self.config.instagram_token = token  # type: ignore[attr-defined]
            self.settings_vars["instagram_user_id"].set(profile.user_id)  # type: ignore[attr-defined]
            self.instagram_status_var.set(f"Підключено: @{profile.username}")  # type: ignore[attr-defined]
            self._persist_connected_config("Instagram підключено і збережено")  # type: ignore[attr-defined]
            self._rebuild_target_controls()  # type: ignore[attr-defined]

        self.run_async(  # type: ignore[attr-defined]
            lambda: inspect_instagram_profile(user_id, token, self.config.meta_graph_version),  # type: ignore[attr-defined]
            success,
            label="Instagram: перевіряю професійний акаунт",
            done_label="Instagram перевірено",
        )

    def _auto_check_instagram(self) -> None:
        if not self.config.instagram_enabled:  # type: ignore[attr-defined]
            return
        user_id = self.config.instagram_user_id  # type: ignore[attr-defined]
        token = self.config.instagram_token  # type: ignore[attr-defined]
        version = self.config.meta_graph_version  # type: ignore[attr-defined]

        def runner() -> None:
            try:
                profile = inspect_instagram_profile(user_id, token, version)
                text = f"Підключено: @{profile.username}"
            except Exception as exc:
                text = f"Instagram потребує уваги: {exc}"
            try:
                self._post_ui(lambda value=text: self.instagram_status_var.set(value))  # type: ignore[attr-defined]
            except tk.TclError:
                pass

        threading.Thread(target=runner, name="instagram-diagnostics", daemon=True).start()

    def save_settings(self, *, show_confirmation: bool = True) -> bool:
        if hasattr(self, "instagram_enabled_var"):
            self.config.instagram_enabled = self.instagram_enabled_var.get()  # type: ignore[attr-defined]
            self.config.instagram_user_id = self.settings_vars["instagram_user_id"].get().strip()  # type: ignore[attr-defined]
            self.config.instagram_token = self.settings_vars["instagram_token"].get().strip()  # type: ignore[attr-defined]
        saved = super().save_settings(show_confirmation=show_confirmation)  # type: ignore[misc]
        if saved:
            self._toggle_instagram_controls()
        return saved
