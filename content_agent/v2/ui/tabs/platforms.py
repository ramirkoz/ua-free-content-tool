from __future__ import annotations

from datetime import datetime, timezone
import tkinter as tk
from tkinter import ttk


class PlatformsTabController:
    """Single operator view of publication/media account readiness."""

    def __init__(self, host) -> None:
        self.host = host
        self.config = host.config
        self.notebook = host.notebook
        self.frame = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.frame, text="Платформи")

        top = ttk.Frame(self.frame)
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="Підключення платформ", font="TkHeadingFont").pack(side="left")
        ttk.Button(top, text="Оновити статус", command=self.refresh).pack(side="right")

        self.tree = ttk.Treeview(
            self.frame,
            columns=("platform", "account", "status", "details"),
            show="headings",
            height=12,
        )
        self.tree.heading("platform", text="Платформа")
        self.tree.heading("account", text="Акаунт / профіль")
        self.tree.heading("status", text="Стан")
        self.tree.heading("details", text="Деталі")
        self.tree.column("platform", width=150, minwidth=110, anchor="w")
        self.tree.column("account", width=260, minwidth=150, anchor="w")
        self.tree.column("status", width=130, minwidth=105, anchor="center")
        self.tree.column("details", width=430, minwidth=180, anchor="w")
        self.tree.pack(fill="both", expand=True)
        self.tree.tag_configure("connected", foreground="#1f7a1f")
        self.tree.tag_configure("expired", foreground="#9a6400")
        self.tree.tag_configure("error", foreground="#a00000")
        self.tree.tag_configure("not_configured", foreground="#666666")
        self.refresh()

    @staticmethod
    def _expired(value: object) -> bool:
        raw = str(value or "").strip()
        if not raw:
            return False
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc) <= datetime.now(timezone.utc)
        except Exception:
            return False

    def _state(self, *, ready: bool, expires_at: object = "") -> tuple[str, str]:
        if self._expired(expires_at):
            return "expired", "Прострочено"
        if ready:
            return "connected", "Підключено"
        return "not_configured", "Не налаштовано"

    def _add(self, platform: str, account: str, state: str, label: str, details: str = "") -> None:
        self.tree.insert("", "end", values=(platform, account or "—", label, details), tags=(state,))

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        cfg = self.config
        try:
            state, label = self._state(ready=cfg.platform_ready("telegram"))
            self._add("Telegram", str(getattr(cfg, "telegram_chat_id", "") or "—"), state, label, "бот + чат")

            pages = [row for row in getattr(cfg, "facebook_pages", []) if isinstance(row, dict)]
            if pages:
                for row in pages:
                    page_id = str(row.get("id") or "")
                    ready = bool(page_id and cfg.platform_ready(f"facebook:{page_id}"))
                    state, label = self._state(ready=ready)
                    self._add("Facebook", str(row.get("name") or page_id), state, label, page_id)
            else:
                self._add("Facebook", "—", "not_configured", "Не налаштовано", "сторінок немає")

            state, label = self._state(
                ready=cfg.platform_ready("instagram"),
                expires_at=getattr(cfg, "instagram_token_expires_at", ""),
            )
            self._add("Instagram", str(getattr(cfg, "instagram_profile_name", "") or getattr(cfg, "instagram_user_id", "") or "—"), state, label)

            state, label = self._state(
                ready=cfg.platform_ready("threads"),
                expires_at=getattr(cfg, "threads_token_expires_at", ""),
            )
            self._add("Threads", str(getattr(cfg, "threads_profile_name", "") or getattr(cfg, "threads_user_id", "") or "—"), state, label)

            state, label = self._state(ready=cfg.platform_ready("linkedin"))
            self._add("LinkedIn", str(getattr(cfg, "linkedin_profile_name", "") or getattr(cfg, "linkedin_author_urn", "") or "—"), state, label)

            drive_ready = bool(getattr(self.host.services, "media", None) and self.host.services.media.ready())
            state, label = self._state(ready=drive_ready)
            self._add("Google Drive", str(getattr(cfg, "google_account_email", "") or "—"), state, label, "медіа / сховище")
        except Exception as exc:
            self._add("Система", "—", "error", "Помилка", str(exc))

    def focus_primary(self) -> None:
        self.tree.focus_set()

    def reset(self) -> None:
        self.refresh()


__all__ = ["PlatformsTabController"]
