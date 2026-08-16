from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..ai_provider_diagnostics_v1_2_1 import ProviderDiagnostic, test_configured_providers
from ..ai_router_v1_2_1 import save_provider_secrets
from .v1_2_rc9_window import MainWindow as RC9Window


_PROVIDER_LABEL_TEXTS: dict[str, tuple[str, ...]] = {
    "nvidia": ("NVIDIA NIM API Key",),
    "gemini": ("Google Gemini API Key",),
    "sambanova": ("SambaNova API Key",),
    "cerebras": ("Cerebras API Key",),
    "groq": ("Groq API Key",),
    "openrouter": ("OpenRouter API Key",),
    "cloudflare": ("Cloudflare Account ID", "Cloudflare API Token"),
}

_STATUS_MARKS: dict[str, tuple[str, str]] = {
    "ok": ("✓", "#1a7f37"),
    "error": ("✗", "#b42318"),
    "warning": ("⚠", "#9a6700"),
    "testing": ("…", "#0969da"),
    "unconfigured": ("—", "#6b7280"),
}


class MainWindow(RC9Window):
    """v1.2.1 RC4 window with explicit health checks for every AI provider."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        self._provider_indicator_widgets: dict[str, list[tuple[ttk.Label, str]]] = {}
        self._provider_diagnostics: dict[str, ProviderDiagnostic] = {}
        super().__init__(*args, **kwargs)
        self._install_provider_diagnostics_ui()
        self.root.title("UA FREE Content Tool — v1.2.1 RC4 · AI Router diagnostics")

    def _find_ai_router_frame(self) -> ttk.LabelFrame | None:
        notebook = getattr(self, "notebook", None)
        if notebook is None:
            return None
        stack = list(notebook.winfo_children())
        while stack:
            widget = stack.pop()
            if isinstance(widget, ttk.LabelFrame):
                try:
                    text = str(widget.cget("text"))
                except tk.TclError:
                    text = ""
                if text.startswith("1. AI Router"):
                    return widget
            stack.extend(widget.winfo_children())
        return None

    def _install_provider_diagnostics_ui(self) -> None:
        frame = self._find_ai_router_frame()
        if frame is None:
            return

        label_lookup: dict[str, ttk.Label] = {}
        action_parent: tk.Misc | None = None
        local_checkbutton: ttk.Checkbutton | None = None
        stack = list(frame.winfo_children())
        while stack:
            widget = stack.pop()
            if isinstance(widget, ttk.Label):
                try:
                    text = str(widget.cget("text"))
                except tk.TclError:
                    text = ""
                if text:
                    label_lookup[text] = widget
            elif isinstance(widget, ttk.Button):
                try:
                    if str(widget.cget("text")) == "Тест AI Router":
                        action_parent = widget.master
                except tk.TclError:
                    pass
            elif isinstance(widget, ttk.Checkbutton):
                try:
                    if str(widget.cget("text")) == "Локальний аварійний AI":
                        local_checkbutton = widget
                except tk.TclError:
                    pass
            stack.extend(widget.winfo_children())

        for provider, texts in _PROVIDER_LABEL_TEXTS.items():
            items: list[tuple[ttk.Label, str]] = []
            for text in texts:
                widget = label_lookup.get(text)
                if widget is not None:
                    items.append((widget, text))
            if items:
                self._provider_indicator_widgets[provider] = items

        self._local_diagnostic_checkbutton = local_checkbutton
        self._local_diagnostic_base_text = "Локальний аварійний AI"

        if action_parent is not None:
            ttk.Button(
                action_parent,
                text="Перевірити всі AI-провайдери",
                command=self.test_all_ai_providers_ui,
            ).pack(side="left", padx=(16, 0))

        self._reset_provider_indicators()

    def _provider_is_configured_in_ui(self, provider: str) -> bool:
        try:
            values = self._provider_secrets_from_ui().normalized()
        except Exception:
            return False
        if provider == "nvidia":
            return bool(values.nvidia_api_key)
        if provider == "gemini":
            return bool(values.gemini_api_key)
        if provider == "sambanova":
            return bool(values.sambanova_api_key)
        if provider == "cerebras":
            return bool(values.cerebras_api_key)
        if provider == "groq":
            return bool(values.groq_api_key)
        if provider == "openrouter":
            return bool(values.openrouter_api_key)
        if provider == "cloudflare":
            return bool(values.cloudflare_account_id and values.cloudflare_api_token)
        if provider == "local":
            return bool(values.local_enabled and values.local_base_url and values.local_model)
        return False

    def _set_provider_indicator(self, provider: str, status: str) -> None:
        mark, color = _STATUS_MARKS.get(status, _STATUS_MARKS["unconfigured"])
        for widget, base_text in self._provider_indicator_widgets.get(provider, []):
            try:
                widget.configure(text=f"{mark} {base_text}", foreground=color)
            except tk.TclError:
                pass
        if provider == "local":
            widget = getattr(self, "_local_diagnostic_checkbutton", None)
            if widget is not None:
                try:
                    widget.configure(text=f"{mark} {self._local_diagnostic_base_text}")
                except tk.TclError:
                    pass

    def _reset_provider_indicators(self) -> None:
        self._provider_diagnostics = {}
        for provider in (*_PROVIDER_LABEL_TEXTS.keys(), "local"):
            self._set_provider_indicator(provider, "unconfigured")

    def save_ai_provider_settings(self) -> None:
        super().save_ai_provider_settings()
        self._reset_provider_indicators()

    def refresh_ai_component_status(self) -> None:
        super().refresh_ai_component_status()
        if not self._provider_diagnostics:
            return
        rows = list(self._provider_diagnostics.values())
        ok_count = sum(row.status == "ok" for row in rows)
        error_count = sum(row.status == "error" for row in rows)
        warning_count = sum(row.status == "warning" for row in rows)
        current = self.ai_router_status_var.get()
        self.ai_router_status_var.set(
            f"{current} · перевірка провайдерів: ✓ {ok_count}"
            + (f" · ✗ {error_count}" if error_count else "")
            + (f" · ⚠ {warning_count}" if warning_count else "")
        )
        codex = self._provider_diagnostics.get("codex")
        if codex is not None:
            mark, _color = _STATUS_MARKS.get(codex.status, _STATUS_MARKS["unconfigured"])
            base = self.codex_status_var.get()
            self.codex_status_var.set(f"{mark} {base}")

    def _apply_provider_diagnostics(self, rows: list[ProviderDiagnostic]) -> None:
        self._provider_diagnostics = {row.provider: row for row in rows}
        for row in rows:
            if row.provider in _PROVIDER_LABEL_TEXTS or row.provider == "local":
                self._set_provider_indicator(row.provider, row.status)
        self.refresh_ai_component_status()

        checked = [row for row in rows if row.status != "unconfigured"]
        problems = [row for row in checked if row.status in {"error", "warning"}]
        if not checked:
            self.set_status("AI-провайдери не налаштовані.")
            return
        summary = f"Перевірено AI-провайдерів: {len(checked)} · працює {sum(row.status == 'ok' for row in checked)}"
        if problems:
            first = problems[0]
            summary += f" · {first.label}: {first.detail}"
        self.set_status(summary)

    def test_all_ai_providers_ui(self) -> None:
        try:
            save_provider_secrets(self._provider_secrets_from_ui())
        except Exception as exc:
            self._show_error(exc)
            return

        self._provider_diagnostics = {}
        for provider in (*_PROVIDER_LABEL_TEXTS.keys(), "local"):
            self._set_provider_indicator(
                provider,
                "testing" if self._provider_is_configured_in_ui(provider) else "unconfigured",
            )
        self.set_status("Перевіряю кожен налаштований AI-провайдер окремо…")

        def success(result: object) -> None:
            rows = [row for row in list(result) if isinstance(row, ProviderDiagnostic)] if isinstance(result, list) else []
            self._apply_provider_diagnostics(rows)

        self.run_async(
            test_configured_providers,
            success,
            label="AI Router: перевіряю всі провайдери окремо",
            done_label="Перевірку AI-провайдерів завершено",
        )
