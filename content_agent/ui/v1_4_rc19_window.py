from __future__ import annotations

import sys
import tkinter as tk
from datetime import datetime
from tkinter import ttk
from typing import Any

from ..timezone_settings_v1_4_rc19 import (
    SYSTEM_TIMEZONE,
    TimezoneSettingsError,
    choice_to_timezone_name,
    format_ui_timestamp,
    load_timezone_name,
    resolve_timezone,
    save_timezone_name,
    system_timezone_name,
    timezone_choices,
    timezone_display_name,
    timezone_name_to_choice,
)
from .v1_4_rc18_window import MainWindow as Rc18MainWindow


def _zone_key(zone: object) -> str:
    return str(getattr(zone, "key", "") or zone)


def _patch_runtime_timezone(zone: object) -> None:
    """Point legacy v1.4 modules at one runtime working timezone.

    Older releases imported the historical ``KYIV`` constant by value. RC19
    keeps those stable modules intact and patches their module-level reference
    before any date filtering, scheduling or rollover work starts. Newly loaded
    modules inherit the same value from ``content_agent.scheduling``.
    """

    from .. import scheduling

    scheduling.KYIV = zone  # type: ignore[assignment]
    for module in list(sys.modules.values()):
        name = str(getattr(module, "__name__", "") or "")
        if not name.startswith("content_agent"):
            continue
        if hasattr(module, "KYIV"):
            try:
                setattr(module, "KYIV", zone)
            except Exception:
                pass


def _localize_tree_column(tree: object, column: str, zone: object) -> None:
    """Convert one visible timestamp column without changing stored UTC data."""

    try:
        columns = tuple(tree.cget("columns"))  # type: ignore[attr-defined]
        if column not in columns:
            return
        item_ids = tree.get_children()  # type: ignore[attr-defined]
    except Exception:
        return
    for item_id in item_ids:
        try:
            current = tree.set(item_id, column)  # type: ignore[attr-defined]
            rendered = format_ui_timestamp(current, zone)  # type: ignore[arg-type]
            if rendered != current:
                tree.set(item_id, column, rendered)  # type: ignore[attr-defined]
        except Exception:
            continue


class MainWindow(Rc18MainWindow):
    """v1.4.0-rc19: one user-selected timezone for UI, schedule and daily Inbox."""

    VERSION_LABEL = "1.4.0-rc19"

    def __init__(self, root, database, config) -> None:
        self._timezone_name = load_timezone_name()
        self._working_timezone = resolve_timezone(self._timezone_name)
        self.timezone_choice_var: tk.StringVar | None = None
        self.timezone_status_var: tk.StringVar | None = None
        _patch_runtime_timezone(self._working_timezone)
        super().__init__(root, database, config)
        self._refresh_timezone_status()

    def _language_code(self) -> str:
        value = str(getattr(getattr(self, "config", None), "ui_language", "uk") or "uk").lower()
        return "en" if value.startswith("en") else "uk"

    def _is_english(self) -> bool:
        return self._language_code() == "en"

    def _apply_v14_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v1.4.0-rc19")

    def _build_settings_tab(self) -> None:
        before = set(self.notebook.tabs())
        super()._build_settings_tab()
        new_tabs = [item for item in self.notebook.tabs() if item not in before]
        tab_id = new_tabs[-1] if new_tabs else self.notebook.tabs()[-1]
        tab = self.root.nametowidget(tab_id)

        english = self._is_english()
        frame = ttk.LabelFrame(
            tab,
            text="Program timezone" if english else "Часовий пояс програми",
            padding=8,
        )
        children = tab.winfo_children()
        if children:
            frame.pack(fill="x", padx=4, pady=(0, 8), after=children[0])
        else:
            frame.pack(fill="x", padx=4, pady=(0, 8))

        row = ttk.Frame(frame)
        row.pack(fill="x")
        ttk.Label(row, text="Timezone:" if english else "Часовий пояс:").pack(side="left")
        self.timezone_choice_var = tk.StringVar(
            value=timezone_name_to_choice(self._timezone_name, language=self._language_code())
        )
        box = ttk.Combobox(
            row,
            textvariable=self.timezone_choice_var,
            values=timezone_choices(language=self._language_code()),
            width=42,
            state="normal",
        )
        box.pack(side="left", padx=(8, 8))
        self.timezone_status_var = tk.StringVar()
        ttk.Label(row, textvariable=self.timezone_status_var, foreground="#555").pack(side="left", fill="x", expand=True)

        explanation = (
            "System (automatic) uses the Windows timezone. UTC is kept in storage; this setting controls "
            "displayed times, publication scheduling and the midnight Inbox rollover."
            if english
            else "«Системний (автоматично)» використовує часовий пояс Windows. У сховищі час лишається UTC; "
            "це налаштування керує відображенням часу, розкладом публікацій і опівнічним очищенням Вхідних."
        )
        ttk.Label(frame, text=explanation, foreground="#555", wraplength=1280, justify="left").pack(
            anchor="w", pady=(5, 0)
        )
        self.timezone_choice_var.trace_add("write", self._timezone_choice_changed)
        self._refresh_timezone_status()

    def _timezone_choice_changed(self, *_args: Any) -> None:
        if not getattr(self, "_settings_loading", False):
            self._mark_settings_dirty()
        self._refresh_timezone_status(preview=True)

    def _refresh_timezone_status(self, *, preview: bool = False) -> None:
        variable = getattr(self, "timezone_status_var", None)
        if variable is None:
            return
        english = self._is_english()
        selected = self._timezone_name
        if preview and self.timezone_choice_var is not None:
            try:
                selected = choice_to_timezone_name(self.timezone_choice_var.get())
            except TimezoneSettingsError:
                variable.set("Unknown timezone" if english else "Невідомий часовий пояс")
                return
        if selected == SYSTEM_TIMEZONE:
            detected = system_timezone_name()
            variable.set(("Detected: " if english else "Виявлено: ") + detected)
        else:
            variable.set(("Selected: " if english else "Вибрано: ") + selected)

    def _working_zone_label(self) -> str:
        return timezone_display_name(self._timezone_name, language=self._language_code())

    def save_settings(self, show_confirmation: bool = True) -> bool:
        selected = self._timezone_name
        if self.timezone_choice_var is not None:
            try:
                selected = choice_to_timezone_name(self.timezone_choice_var.get())
                new_zone = resolve_timezone(selected)
            except TimezoneSettingsError as exc:
                self.msg.showerror(
                    "Settings" if self._is_english() else "Налаштування",
                    str(exc),
                )
                return False
        else:
            new_zone = self._working_timezone

        if not super().save_settings(show_confirmation=False):
            return False

        old_key = _zone_key(self._working_timezone)
        try:
            self._timezone_name = save_timezone_name(selected)
        except (OSError, TimezoneSettingsError) as exc:
            self.msg.showerror(
                "Settings" if self._is_english() else "Налаштування",
                ("Could not save timezone: " if self._is_english() else "Не вдалося зберегти часовий пояс: ") + str(exc),
            )
            return False

        self._working_timezone = new_zone
        _patch_runtime_timezone(new_zone)
        new_key = _zone_key(new_zone)

        # A timezone change changes both the wall-clock display and the definition
        # of the working day. Re-arm midnight and re-evaluate today's Inbox now.
        if getattr(self, "inbox_rollover_after_id", None) is not None:
            try:
                self.root.after_cancel(self.inbox_rollover_after_id)
            except Exception:
                pass
            self.inbox_rollover_after_id = None
        self._schedule_inbox_rollover()
        if old_key != new_key:
            try:
                self.db.rollover_inbox_day(now=datetime.now(new_zone))
            except Exception as exc:
                self.status_var.set(
                    ("Timezone saved, but Inbox rollover failed: " if self._is_english()
                     else "Часовий пояс збережено, але не вдалося оновити Вхідні: ") + str(exc)
                )

        if self.timezone_choice_var is not None:
            self.timezone_choice_var.set(
                timezone_name_to_choice(self._timezone_name, language=self._language_code())
            )
        self._refresh_timezone_status()
        self.refresh_sources()
        self.refresh_groups()
        self.refresh_queue()
        self.refresh_history()
        if getattr(self, "current_group_id", None):
            try:
                self.load_group(int(self.current_group_id))
            except Exception:
                pass

        self.settings_dirty = False
        self.settings_dirty_var.set("All changes saved" if self._is_english() else "Усі зміни збережено")
        if show_confirmation:
            self.msg.showinfo(
                "Settings" if self._is_english() else "Налаштування",
                (
                    f"Settings saved. Working timezone: {self._working_zone_label()}."
                    if self._is_english()
                    else f"Налаштування збережено. Робочий часовий пояс: {self._working_zone_label()}."
                ),
            )
        return True

    def refresh_sources(self) -> None:
        super().refresh_sources()
        _localize_tree_column(self.sources_tree, "last_new", self._working_timezone)
        _localize_tree_column(self.sources_tree, "checked", self._working_timezone)

    def refresh_groups(self) -> None:
        super().refresh_groups()
        _localize_tree_column(self.groups_tree, "published", self._working_timezone)

    def load_group(self, group_id: int) -> None:
        super().load_group(group_id)
        _localize_tree_column(self.group_sources_tree, "time", self._working_timezone)

    def refresh_queue(self) -> None:
        _patch_runtime_timezone(self._working_timezone)
        super().refresh_queue()

    def refresh_history(self) -> None:
        _patch_runtime_timezone(self._working_timezone)
        super().refresh_history()

    def _connection_diagnostics_completed(self, report, snapshot, automatic: bool) -> None:
        super()._connection_diagnostics_completed(report, snapshot, automatic)
        variable = getattr(self, "connection_diagnostics_status_var", None)
        if variable is None:
            return
        try:
            text = str(variable.get() or "")
        except Exception:
            return
        if "за Києвом" in text:
            variable.set(text.replace("за Києвом", f"({self._working_zone_label()})"))
