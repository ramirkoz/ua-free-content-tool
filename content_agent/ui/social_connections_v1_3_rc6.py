from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..instagram_api_v1_2_rc4 import inspect_instagram_profile


class SocialConnectionsRC6Mixin:
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[misc]
        self._upgrade_social_connections_rc6()

    def _find_platform_frame(self, title: str) -> ttk.LabelFrame | None:
        stack = [self.root]  # type: ignore[attr-defined]
        while stack:
            parent = stack.pop()
            for child in parent.winfo_children():
                stack.append(child)
                if isinstance(child, ttk.LabelFrame) and str(child.cget("text")) == title:
                    return child
        return None

    def _add_disconnect_button(self, title: str, command) -> None:
        frame = self._find_platform_frame(title)
        if frame is None:
            return
        for child in frame.winfo_children():
            if isinstance(child, ttk.Button) and str(child.cget("text")) == "Вимкнути":
                return
        ttk.Button(frame, text="Вимкнути", command=command).grid(
            row=1,
            column=2,
            sticky="w",
            padx=(8, 0),
        )

    def _upgrade_social_connections_rc6(self) -> None:
        self._add_disconnect_button("Facebook Pages", lambda: self._disconnect_social("facebook"))
        self._add_disconnect_button("Threads", lambda: self._disconnect_social("threads"))
        self._add_disconnect_button("LinkedIn", lambda: self._disconnect_social("linkedin"))
        self._add_disconnect_button("Telegram", lambda: self._disconnect_social("telegram"))
        self._rebuild_instagram_section_rc6()

    def _rebuild_instagram_section_rc6(self) -> None:
        old = self._find_platform_frame("Instagram")
        facebook = self._find_platform_frame("Facebook Pages")
        if facebook is None:
            return
        parent = facebook.master
        if old is not None:
            old.destroy()
        if hasattr(self, "instagram_enabled_var"):
            try:
                delattr(self, "instagram_enabled_var")
            except AttributeError:
                pass
        self.settings_vars.setdefault("instagram_user_id", tk.StringVar(value=self.config.instagram_user_id))  # type: ignore[attr-defined]
        self.settings_vars.setdefault("instagram_token", tk.StringVar(value=self.config.instagram_token))  # type: ignore[attr-defined]
        self.instagram_status_var = tk.StringVar(value=self._instagram_status_rc6())

        frame = ttk.LabelFrame(parent, text="Instagram", padding=8)
        frame.pack(fill="x", pady=4, after=facebook)
        ttk.Label(frame, text="Instagram User ID").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.settings_vars["instagram_user_id"], width=32).grid(  # type: ignore[attr-defined]
            row=1, column=0, sticky="ew", padx=(0, 8)
        )
        ttk.Label(frame, text="Instagram Access Token").grid(row=0, column=1, sticky="w")
        ttk.Entry(frame, textvariable=self.settings_vars["instagram_token"], show="•", width=56).grid(  # type: ignore[attr-defined]
            row=1, column=1, sticky="ew", padx=(0, 8)
        )
        actions = ttk.Frame(frame)
        actions.grid(row=1, column=2, sticky="w")
        ttk.Button(actions, text="Підключити / перевірити", command=self.connect_instagram).pack(side="left")
        ttk.Button(actions, text="Вимкнути", command=lambda: self._disconnect_social("instagram")).pack(
            side="left", padx=(6, 0)
        )
        ttk.Label(frame, textvariable=self.instagram_status_var, foreground="#555").grid(
            row=2, column=0, columnspan=3, sticky="ew", pady=(5, 2)
        )
        ttk.Label(
            frame,
            text="Окремого прапорця немає: успішна перевірка підключає Instagram, «Вимкнути» стирає токен і відключає його.",
            foreground="#666",
        ).grid(row=3, column=0, columnspan=3, sticky="ew")
        frame.columnconfigure(1, weight=1)

    def _instagram_status_rc6(self) -> str:
        if self.config.platform_ready("instagram"):  # type: ignore[attr-defined]
            name = self.config.instagram_profile_name or self.config.instagram_user_id  # type: ignore[attr-defined]
            return f"Підключено: {name}"
        return "Відключено"

    def connect_meta(self) -> None:
        self.config.facebook_enabled = True  # type: ignore[attr-defined]
        return super().connect_meta()  # type: ignore[misc]

    def connect_threads(self) -> None:
        self.config.threads_enabled = True  # type: ignore[attr-defined]
        return super().connect_threads()  # type: ignore[misc]

    def connect_linkedin(self) -> None:
        self.config.linkedin_enabled = True  # type: ignore[attr-defined]
        return super().connect_linkedin()  # type: ignore[misc]

    def connect_telegram(self) -> None:
        self.config.telegram_enabled = True  # type: ignore[attr-defined]
        return super().connect_telegram()  # type: ignore[misc]

    def connect_instagram(self) -> None:
        user_id = self.settings_vars["instagram_user_id"].get().strip()  # type: ignore[attr-defined]
        token = self.settings_vars["instagram_token"].get().strip()  # type: ignore[attr-defined]
        if not user_id or not token:
            self.msg.showinfo(  # type: ignore[attr-defined]
                "Instagram",
                "Вкажіть Instagram User ID і Access Token.",
                parent=self.root,  # type: ignore[attr-defined]
            )
            return
        self.instagram_status_var.set("Перевіряю Instagram…")

        def success(result: object) -> None:
            profile = result
            self.config.instagram_enabled = True  # type: ignore[attr-defined]
            self.config.instagram_user_id = profile.user_id  # type: ignore[attr-defined]
            self.config.instagram_profile_name = profile.username  # type: ignore[attr-defined]
            self.config.instagram_token = token  # type: ignore[attr-defined]
            self.settings_vars["instagram_user_id"].set(profile.user_id)  # type: ignore[attr-defined]
            self.instagram_status_var.set(f"Підключено: @{profile.username}")
            self._persist_connected_config("Instagram підключено і збережено")  # type: ignore[attr-defined]
            self._rebuild_target_controls()  # type: ignore[attr-defined]

        self.run_async(  # type: ignore[attr-defined]
            lambda: inspect_instagram_profile(user_id, token, self.config.meta_graph_version),  # type: ignore[attr-defined]
            success,
            label="Instagram: перевіряю професійний акаунт",
            done_label="Instagram перевірено",
        )

    def _disconnect_social(self, platform: str) -> None:
        names = {
            "facebook": "Facebook",
            "threads": "Threads",
            "linkedin": "LinkedIn",
            "telegram": "Telegram",
            "instagram": "Instagram",
        }
        name = names[platform]
        if not self.msg.askyesno(  # type: ignore[attr-defined]
            f"Вимкнути {name}",
            f"Видалити збережені токени {name} і вимкнути мережу до наступного підключення?",
            parent=self.root,  # type: ignore[attr-defined]
        ):
            return
        if platform == "facebook":
            self.config.facebook_enabled = False  # type: ignore[attr-defined]
            self.config.meta_user_access_token = ""  # type: ignore[attr-defined]
            self.config.meta_user_token_expires_at = ""  # type: ignore[attr-defined]
            self.config.facebook_pages = []  # type: ignore[attr-defined]
            self.config.sync_legacy_facebook_slots()  # type: ignore[attr-defined]
            if "meta_user_access_token" in self.settings_vars:  # type: ignore[attr-defined]
                self.settings_vars["meta_user_access_token"].set("")  # type: ignore[attr-defined]
            self.meta_pages = []  # type: ignore[attr-defined]
            if hasattr(self, "_refresh_meta_pages_view"):
                self._refresh_meta_pages_view()  # type: ignore[attr-defined]
            if hasattr(self, "meta_status_var"):
                self.meta_status_var.set("Відключено")  # type: ignore[attr-defined]
        elif platform == "threads":
            self.config.threads_enabled = False  # type: ignore[attr-defined]
            self.config.threads_user_id = ""  # type: ignore[attr-defined]
            self.config.threads_profile_name = ""  # type: ignore[attr-defined]
            self.config.threads_token = ""  # type: ignore[attr-defined]
            self.config.threads_token_expires_at = ""  # type: ignore[attr-defined]
            self.config.threads_token_refreshed_at = ""  # type: ignore[attr-defined]
            self.settings_vars["threads_token"].set("")  # type: ignore[attr-defined]
            if hasattr(self, "threads_status_var"):
                self.threads_status_var.set("Відключено")  # type: ignore[attr-defined]
        elif platform == "linkedin":
            self.config.linkedin_enabled = False  # type: ignore[attr-defined]
            self.config.linkedin_author_urn = ""  # type: ignore[attr-defined]
            self.config.linkedin_profile_name = ""  # type: ignore[attr-defined]
            self.config.linkedin_token = ""  # type: ignore[attr-defined]
            self.settings_vars["linkedin_token"].set("")  # type: ignore[attr-defined]
            if hasattr(self, "linkedin_status_var"):
                self.linkedin_status_var.set("Відключено")  # type: ignore[attr-defined]
        elif platform == "telegram":
            self.config.telegram_enabled = False  # type: ignore[attr-defined]
            self.config.telegram_bot_token = ""  # type: ignore[attr-defined]
            self.config.telegram_chat_id = ""  # type: ignore[attr-defined]
            self.settings_vars["telegram_bot_token"].set("")  # type: ignore[attr-defined]
            self.settings_vars["telegram_chat_id"].set("")  # type: ignore[attr-defined]
            if hasattr(self, "telegram_status_var"):
                self.telegram_status_var.set("Відключено")  # type: ignore[attr-defined]
        else:
            self.config.instagram_enabled = False  # type: ignore[attr-defined]
            self.config.instagram_user_id = ""  # type: ignore[attr-defined]
            self.config.instagram_profile_name = ""  # type: ignore[attr-defined]
            self.config.instagram_token = ""  # type: ignore[attr-defined]
            self.config.instagram_token_expires_at = ""  # type: ignore[attr-defined]
            self.settings_vars["instagram_user_id"].set("")  # type: ignore[attr-defined]
            self.settings_vars["instagram_token"].set("")  # type: ignore[attr-defined]
            self.instagram_status_var.set("Відключено")
        if hasattr(self, "worker"):
            self.worker.clear_auth_blocks(platform)  # type: ignore[attr-defined]
        self._persist_connected_config(f"{name} відключено; токени видалено")  # type: ignore[attr-defined]
        self._rebuild_target_controls()  # type: ignore[attr-defined]

    def save_settings(self, *, show_confirmation: bool = True) -> bool:
        if "instagram_user_id" in self.settings_vars:  # type: ignore[attr-defined]
            self.config.instagram_user_id = self.settings_vars["instagram_user_id"].get().strip()  # type: ignore[attr-defined]
            self.config.instagram_token = self.settings_vars["instagram_token"].get().strip()  # type: ignore[attr-defined]
        saved = super().save_settings(show_confirmation=show_confirmation)  # type: ignore[misc]
        if saved and hasattr(self, "instagram_status_var"):
            self.instagram_status_var.set(self._instagram_status_rc6())
        return saved
