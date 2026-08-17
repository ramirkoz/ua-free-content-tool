from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..ai_provider_diagnostics_v1_2_1 import ProviderDiagnostic, test_configured_providers
from ..ai_router_v1_2_1 import save_provider_secrets, test_ai_router
from .v1_2_rc9_window import MainWindow as RC9Window


_PROVIDER_LABEL_TEXTS: dict[str, tuple[str, ...]] = {
    "nvidia": ("NVIDIA NIM API Key",),
    "gemini": ("Google Gemini API Key",),
    "groq": ("Groq API Key",),
    "cloudflare": ("Cloudflare Account ID", "Cloudflare API Token"),
}

_REMOVED_PROVIDER_LABELS = (
    "SambaNova API Key",
    "Cerebras API Key",
    "OpenRouter API Key",
)

_STATUS_MARKS: dict[str, tuple[str, str]] = {
    "ok": ("✓", "#1a7f37"),
    "error": ("✗", "#b42318"),
    "warning": ("⚠", "#9a6700"),
    "testing": ("…", "#0969da"),
    "unconfigured": ("—", "#6b7280"),
}


class MainWindow(RC9Window):
    """Final v1.2.1 window with production AI providers and unified diagnostics."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        self._provider_indicator_widgets: dict[str, list[tuple[ttk.Label, str]]] = {}
        self._provider_diagnostics: dict[str, ProviderDiagnostic] = {}
        super().__init__(*args, **kwargs)
        self._compact_ai_provider_panel()
        self._install_provider_diagnostics_ui()
        self.root.title("UA FREE Content Tool — v1.2.1 · AI Router + Rowboat")

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

    @staticmethod
    def _grid_entry_next_to(label: ttk.Label) -> ttk.Entry | None:
        try:
            info = label.grid_info()
            row = int(info.get("row", -1))
            column = int(info.get("column", -1))
        except (tk.TclError, TypeError, ValueError):
            return None
        for widget in label.master.winfo_children():
            if not isinstance(widget, ttk.Entry):
                continue
            try:
                other = widget.grid_info()
                if int(other.get("row", -2)) == row and int(other.get("column", -2)) == column + 1:
                    return widget
            except (tk.TclError, TypeError, ValueError):
                continue
        return None

    def _compact_ai_provider_panel(self) -> None:
        frame = self._find_ai_router_frame()
        if frame is None:
            return

        labels: dict[str, ttk.Label] = {}
        for widget in frame.winfo_children():
            if not isinstance(widget, ttk.Label):
                continue
            try:
                text = str(widget.cget("text"))
            except tk.TclError:
                continue
            if text:
                labels[text] = widget

        entries = {text: self._grid_entry_next_to(label) for text, label in labels.items()}

        for text in _REMOVED_PROVIDER_LABELS:
            label = labels.get(text)
            entry = entries.get(text)
            if entry is not None:
                entry.destroy()
            if label is not None:
                label.destroy()

        def move_pair(text: str, row: int, column: int) -> None:
            label = labels.get(text)
            entry = entries.get(text)
            if label is not None and label.winfo_exists():
                label.grid_configure(row=row, column=column)
            if entry is not None and entry.winfo_exists():
                entry.grid_configure(row=row, column=column + 1)

        move_pair("NVIDIA NIM API Key", 2, 0)
        move_pair("Groq API Key", 2, 2)
        move_pair("Google Gemini API Key", 3, 0)
        move_pair("Cloudflare Account ID", 3, 2)
        move_pair("Cloudflare API Token", 4, 0)

        # Local fallback occupied row 6 in the inherited panel. Move its whole row to 5.
        for widget in frame.winfo_children():
            try:
                info = widget.grid_info()
                row = int(info.get("row", -1))
            except (tk.TclError, TypeError, ValueError):
                continue
            if row == 6:
                widget.grid_configure(row=5)

        # Everything below the provider section moves up by one row.
        for widget in frame.winfo_children():
            try:
                info = widget.grid_info()
                row = int(info.get("row", -1))
            except (tk.TclError, TypeError, ValueError):
                continue
            if row >= 7:
                widget.grid_configure(row=row - 1)

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
                    if str(widget.cget("text")).startswith("Локальний аварійний AI"):
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
        self._local_diagnostic_base_text = "Локальний аварійний AI · Ollama автоматично"

        if test_button is not None:
            test_button.configure(command=self.test_ai_router_ui)

        self._reset_provider_indicators()

    def _provider_secrets_from_ui(self):
        values = super()._provider_secrets_from_ui()
        # Removed providers stay readable for migration compatibility but are cleared
        # on the next settings save/test and never enter the production model chain.
        values.sambanova_api_key = ""
        values.cerebras_api_key = ""
        values.openrouter_api_key = ""
        return values

    def _provider_is_configured_in_ui(self, provider: str) -> bool:
        try:
            values = self._provider_secrets_from_ui().normalized()
        except Exception:
            return False
        if provider == "nvidia":
            return bool(values.nvidia_api_key)
        if provider == "gemini":
            return bool(values.gemini_api_key)
        if provider == "groq":
            return bool(values.groq_api_key)
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

    @staticmethod
    def _strip_health_prefix(value: str) -> str:
        text = str(value or "")
        for prefix in ("✓ ", "✗ ", "⚠ ", "— ", "… "):
            if text.startswith(prefix):
                return text[len(prefix):]
        return text

    def refresh_ai_component_status(self) -> None:
        super().refresh_ai_component_status()
        if not self._provider_diagnostics:
            return
        rows = list(self._provider_diagnostics.values())
        ok_count = sum(row.status == "ok" for row in rows)
        error_count = sum(row.status == "error" for row in rows)
        warning_count = sum(row.status == "warning" for row in rows)
        current = self.ai_router_status_var.get().split(" · ключі:", 1)[0]
        self.ai_router_status_var.set(
            f"{current} · ключі: ✓ {ok_count}"
            + (f" · ✗ {error_count}" if error_count else "")
            + (f" · ⚠ {warning_count}" if warning_count else "")
        )
        codex = self._provider_diagnostics.get("codex")
        if codex is not None:
            mark, _color = _STATUS_MARKS.get(codex.status, _STATUS_MARKS["unconfigured"])
            base = self._strip_health_prefix(self.codex_status_var.get())
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
