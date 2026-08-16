from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..ai_provider_diagnostics_v1_2_1 import ProviderDiagnostic, test_configured_providers
from ..ai_router_v1_2_1 import save_provider_secrets, test_ai_router
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
    """v1.2.1 RC5 window with one unambiguous AI Router test and provider health marks."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        self._provider_indicator_widgets: dict[str, list[tuple[ttk.Label, str]]] = {}
        self._provider_diagnostics: dict[str, ProviderDiagnostic] = {}
        super().__init__(*args, **kwargs)
        self._install_provider_diagnostics_ui()
        self.root.title("UA FREE Content Tool — v1.2.1 RC5 · AI Router diagnostics")

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
        test_button: ttk.Button | None = None
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
                        test_button = widget
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

        if test_button is not None:
            test_button.configure(command=self.test_ai_router_ui)

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

    def clear_ai_router_cooldowns_ui(self) -> None:
        super().clear_ai_router_cooldowns_ui()
        if self._provider_diagnostics:
            self.refresh_ai_component_status()

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
            f"{current} · ключі: ✓ {ok_count}"
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

    def _provider_diagnostic_summary(self, rows: list[ProviderDiagnostic]) -> str:
        checked = [row for row in rows if row.status != "unconfigured"]
        if not checked:
            return "AI-провайдери не налаштовані"
        ok_count = sum(row.status == "ok" for row in checked)
        problems = [row for row in checked if row.status in {"error", "warning"}]
        summary = f"Ключі перевірено: {len(checked)} · працює {ok_count}"
        if problems:
            details = "; ".join(f"{row.label}: {row.detail}" for row in problems[:3])
            summary += f" · проблеми: {details}"
        return summary

    def _provider_diagnostic_report(self, rows: list[ProviderDiagnostic], router_result: object, router_ok: bool) -> str:
        lines: list[str] = []
        for row in rows:
            mark, _color = _STATUS_MARKS.get(row.status, _STATUS_MARKS["unconfigured"])
            if row.status == "unconfigured":
                lines.append(f"{mark} {row.label} — не налаштовано")
            else:
                lines.append(f"{mark} {row.label} — {row.detail}")
        lines.append("")
        lines.append(("✓ " if router_ok else "✗ ") + str(router_result))
        return "\n".join(lines)

    def test_ai_router_ui(self) -> None:
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
        self.set_status("Перевіряю всі AI-провайдери, потім сам пріоритетний ланцюг…")

        def action() -> object:
            rows = test_configured_providers()
            try:
                router_result = test_ai_router()
                router_ok = True
            except Exception as exc:
                router_result = f"AI Router не пройшов контрольний виклик: {exc}"
                router_ok = False
            return rows, router_result, router_ok

        def success(result: object) -> None:
            try:
                rows_raw, router_result, router_ok = result  # type: ignore[misc]
            except Exception:
                self.set_status(f"Неправильний результат діагностики: {result}")
                return
            rows = [row for row in list(rows_raw) if isinstance(row, ProviderDiagnostic)]
            self._apply_provider_diagnostics(rows)
            summary = self._provider_diagnostic_summary(rows)
            route_mark = "✓" if bool(router_ok) else "✗"
            self.set_status(f"{summary} · {route_mark} {router_result}")
            self.msg.showinfo(
                "AI Router — результати перевірки",
                self._provider_diagnostic_report(rows, router_result, bool(router_ok)),
                parent=self.root,
            )

        self.run_async(
            action,
            success,
            label="AI Router: перевіряю всі ключі та failover",
            done_label="AI Router і ключі перевірено",
        )

    def test_all_ai_providers_ui(self) -> None:
        self.test_ai_router_ui()
