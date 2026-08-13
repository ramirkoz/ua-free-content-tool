from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

from ..instagram_api_v1_2_rc4 import inspect_instagram_profile


class InstagramSettingsMixin:
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[misc]
        self._upgrade_instagram_settings()

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
        self.instagram_status_var = tk.StringVar(value="")
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
        self._instagram_control_widgets = (user_entry, token_entry, check_button)
        self._toggle_instagram_controls()
