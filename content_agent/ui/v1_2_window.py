from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Any, Iterable, Mapping

from ..i18n import original_text
from .main_window_enhancements import MainWindow as EnhancedMainWindow


def editorial_memory_texts(language: str = "uk") -> dict[str, str]:
    """Return plain-language labels for the editorial-memory settings block."""

    if language == "en":
        return {
            "title": "Editorial memory",
            "explanation": (
                "The application does not retrain or modify Ollama. It stores texts you approved "
                "and adds the most similar previous examples to future rewrite prompts."
            ),
            "enabled": "Use previously approved texts as rewrite examples",
            "limit": "Maximum similar examples for one rewrite",
            "refresh": "Refresh statistics",
            "export": "Save a copy of editorial memory",
            "import": "Restore editorial memory from a copy",
            "clear": "Clear editorial memory",
            "exclusions": "Exclusion rules",
        }
    return {
        "title": "Редакційна пам’ять",
        "explanation": (
            "Програма не перенавчає і не змінює Ollama. Вона зберігає схвалені вами тексти "
            "й додає найбільш схожі попередні приклади до наступних запитів на рерайт."
        ),
        "enabled": "Використовувати попередні схвалені тексти як приклади для рерайту",
        "limit": "Максимум схожих прикладів для одного рерайту",
        "refresh": "Оновити статистику",
        "export": "Зберегти копію редакційної пам’яті",
        "import": "Відновити редакційну пам’ять із копії",
        "clear": "Очистити редакційну пам’ять",
        "exclusions": "Правила виключення",
    }


def format_editorial_memory_stats(stats: Mapping[str, object], language: str = "uk") -> str:
    """Format internal counters as a readable multi-line summary."""

    raw_examples = stats.get("editorial_examples")
    examples = raw_examples if isinstance(raw_examples, Mapping) else {}
    uk_count = int(examples.get("uk", 0) or 0)
    en_count = int(examples.get("en", 0) or 0)
    feedback = int(stats.get("topic_feedback", 0) or 0)
    events = int(stats.get("events", 0) or 0)
    exclusions = int(stats.get("active_exclusions", 0) or 0)
    if language == "en":
        return (
            f"Approved Ukrainian texts: {uk_count}\n"
            f"Approved English texts: {en_count}\n"
            f"Similarity and merge decisions: {feedback}\n"
            f"Journal records: {events}\n"
            f"Active exclusion rules: {exclusions}"
        )
    return (
        f"Схвалених текстів українською: {uk_count}\n"
        f"Схвалених текстів англійською: {en_count}\n"
        f"Рішень щодо схожості й об’єднання: {feedback}\n"
        f"Записів журналу: {events}\n"
        f"Активних правил виключення: {exclusions}"
    )


def editorial_memory_clear_prompt(stats: Mapping[str, object], language: str = "uk") -> str:
    """Describe exactly what clearing editorial memory deletes and preserves."""

    raw_examples = stats.get("editorial_examples")
    examples = raw_examples if isinstance(raw_examples, Mapping) else {}
    uk_count = int(examples.get("uk", 0) or 0)
    en_count = int(examples.get("en", 0) or 0)
    feedback = int(stats.get("topic_feedback", 0) or 0)
    events = int(stats.get("events", 0) or 0)
    exclusions = int(stats.get("active_exclusions", 0) or 0)
    if language == "en":
        return (
            "The following data will be deleted:\n"
            f"• approved texts: UK {uk_count}, EN {en_count}\n"
            f"• similarity and merge decisions: {feedback}\n"
            f"• journal records: {events}\n\n"
            "The following data will remain:\n"
            f"• active exclusion rules: {exclusions}\n\n"
            "Continue?"
        )
    return (
        "Буде видалено:\n"
        f"• схвалені тексти: UK {uk_count}, EN {en_count}\n"
        f"• рішення щодо схожості й об’єднання: {feedback}\n"
        f"• записи журналу: {events}\n\n"
        "Не буде видалено:\n"
        f"• активні правила виключення: {exclusions}\n\n"
        "Продовжити?"
    )


def _walk_widgets(widget: tk.Misc) -> Iterable[tk.Misc]:
    for child in widget.winfo_children():
        yield child
        yield from _walk_widgets(child)


class MainWindow(EnhancedMainWindow):
    """v1.2 user-facing improvements built on the verified v1.1.4 window."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._editorial_memory_widgets: dict[str, tk.Misc] = {}
        super().__init__(*args, **kwargs)

    def _build_settings_tab(self) -> None:
        super()._build_settings_tab()
        self._upgrade_editorial_memory_ui()

    def _apply_language(self, refresh: bool = True) -> None:
        super()._apply_language(refresh=refresh)
        self._refresh_editorial_memory_labels()

    def _upgrade_editorial_memory_ui(self) -> None:
        frame: ttk.LabelFrame | None = None
        for widget in _walk_widgets(self.root):
            if isinstance(widget, ttk.LabelFrame) and original_text(str(widget.cget("text"))) in {
                "Локальне навчання",
                "Local learning",
            }:
                frame = widget
                break
        if frame is None:
            return

        for child in frame.winfo_children():
            if child.winfo_manager() != "grid":
                continue
            info = child.grid_info()
            child.grid_configure(row=int(info.get("row", 0)) + 2)

        explanation = ttk.Label(
            frame,
            text="",
            foreground="#555",
            wraplength=1100,
            justify="left",
        )
        explanation.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        ttk.Separator(frame, orient="horizontal").grid(
            row=1,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=(0, 3),
        )
        frame.columnconfigure(0, weight=1)

        self._editorial_memory_widgets = {
            "frame": frame,
            "explanation": explanation,
        }
        text_keys = {
            "Використовувати навчальні приклади в промптах Ollama": "enabled",
            "Кількість прикладів у промпті": "limit",
            "Оновити статистику": "refresh",
            "Експортувати навчальні дані": "export",
            "Імпортувати навчальні дані": "import",
            "Очистити навчальну історію": "clear",
            "Керувати виключеннями": "exclusions",
        }
        for widget in _walk_widgets(frame):
            try:
                text = original_text(str(widget.cget("text")))
            except tk.TclError:
                continue
            key = text_keys.get(text)
            if key:
                self._editorial_memory_widgets[key] = widget
            if isinstance(widget, ttk.Label):
                try:
                    if str(widget.cget("textvariable")) == str(self.learning_stats_var):
                        widget.configure(justify="left", anchor="w", wraplength=1100)
                        self._editorial_memory_widgets["stats"] = widget
                except tk.TclError:
                    pass
        self._refresh_editorial_memory_labels()

    def _refresh_editorial_memory_labels(self) -> None:
        if not self._editorial_memory_widgets:
            return
        labels = editorial_memory_texts(self.config.ui_language)
        for key, text in labels.items():
            widget = self._editorial_memory_widgets.get(key)
            if widget is None:
                continue
            try:
                widget.configure(text=text)
            except tk.TclError:
                pass
        self.refresh_learning_stats()

    def refresh_learning_stats(self) -> None:
        if not hasattr(self, "learning_stats_var"):
            return
        stats = self.db.learning_stats()
        self.learning_stats_var.set(format_editorial_memory_stats(stats, self.config.ui_language))

    def export_learning_data_ui(self) -> None:
        labels = editorial_memory_texts(self.config.ui_language)
        selected = self.files.asksaveasfilename(
            parent=self.root,
            title=labels["export"],
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialfile="UA_FREE_editorial_memory.json",
        )
        if not selected:
            return
        try:
            path = self.db.export_learning_data(Path(selected))
        except Exception as exc:
            self._show_error(exc)
            return
        self.msg.showinfo(labels["title"], str(path), parent=self.root)

    def import_learning_data_ui(self) -> None:
        labels = editorial_memory_texts(self.config.ui_language)
        selected = self.files.askopenfilename(
            parent=self.root,
            title=labels["import"],
            filetypes=[("JSON", "*.json")],
        )
        if not selected:
            return
        try:
            counts = self.db.import_learning_data(Path(selected))
        except Exception as exc:
            self._show_error(exc)
            return
        self.refresh_learning_stats()
        self.msg.showinfo(labels["title"], str(counts), parent=self.root)

    def clear_learning_history_ui(self) -> None:
        labels = editorial_memory_texts(self.config.ui_language)
        stats = self.db.learning_stats()
        if not self.msg.askyesno(
            labels["clear"],
            editorial_memory_clear_prompt(stats, self.config.ui_language),
            parent=self.root,
        ):
            return
        self.db.clear_learning_history()
        self.refresh_learning_stats()
