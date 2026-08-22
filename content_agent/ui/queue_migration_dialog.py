from __future__ import annotations

import threading
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Callable

from ..backup import create_backup
from ..config import AppConfig
from ..database import Database
from ..i18n import LocalizedMessageBox, localize_widget_tree, normalize_language, tr
from ..ollama_client import OllamaClient
from ..queue_migration import (
    QUEUE_900_MIGRATION_KEY,
    QueueMigrationCandidate,
    QueueMigrationError,
    build_target_payloads,
    compress_approved_text,
    critical_fact_warnings,
)
from ..scheduling import KYIV


class QueueMigrationDialog:
    """Modal one-time editor for future queue texts that exceed the new limit."""

    def __init__(
        self,
        parent: tk.Tk,
        database: Database,
        config: AppConfig,
        candidates: list[QueueMigrationCandidate],
        *,
        on_complete: Callable[[], None],
        on_abort: Callable[[], None],
    ):
        self.parent = parent
        self.db = database
        self.config = config
        self.language = normalize_language(config.ui_language)
        self.msg = LocalizedMessageBox(lambda: self.language)
        self.candidates = {item.batch_id: item for item in candidates}
        self.order = [item.batch_id for item in candidates]
        self.on_complete = on_complete
        self.on_abort = on_abort
        self.drafts: dict[int, str] = {item.batch_id: "" for item in candidates}
        self.errors: dict[int, str] = {}
        self.models: dict[int, str] = {}
        self.current_batch_id: int | None = None
        self.busy = False

        window = self.window = tk.Toplevel(parent)
        window.title(self.t("Разове оновлення завтрашньої черги до 900 символів"))
        window.geometry("1180x820")
        window.minsize(900, 650)
        window.transient(parent)
        window.grab_set()
        window.protocol("WM_DELETE_WINDOW", self._abort)

        outer = ttk.Frame(window, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        ttk.Label(
            outer,
            text="Публікацію тимчасово вимкнено. Переробляються лише майбутні неопубліковані тексти; "
                 "час, медіа, платформи, токени й статуси черги не змінюються.",
            wraplength=1080,
            font="TkHeadingFont",
        ).grid(row=0, column=0, sticky="ew")

        self.status_var = tk.StringVar(
            value=f"Знайдено пакетів для перевірки: {len(candidates)}. Спочатку створіть скорочені тексти."
        )
        ttk.Label(outer, textvariable=self.status_var, foreground="#555", wraplength=1080).grid(
            row=1, column=0, sticky="ew", pady=(4, 10)
        )

        body = ttk.Panedwindow(outer, orient="horizontal")
        body.grid(row=2, column=0, sticky="nsew")

        left = ttk.Frame(body, padding=(0, 0, 8, 0))
        right = ttk.Frame(body, padding=(8, 0, 0, 0))
        body.add(left, weight=2)
        body.add(right, weight=3)
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        right.rowconfigure(4, weight=1)
        right.columnconfigure(0, weight=1)

        columns = ("batch", "schedule", "old", "limit", "new", "state")
        self.tree = ttk.Treeview(left, columns=columns, show="headings", selectmode="browse")
        headings = {
            "batch": "Пакет",
            "schedule": "Час",
            "old": "Було",
            "limit": "Ліміт",
            "new": "Стало",
            "state": "Стан",
        }
        widths = {"batch": 75, "schedule": 145, "old": 75, "limit": 75, "new": 75, "state": 210}
        for key in columns:
            self.tree.heading(key, text=headings[key])
            self.tree.column(key, width=widths[key], anchor="center" if key != "state" else "w")
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        for candidate in candidates:
            self.tree.insert(
                "",
                "end",
                iid=str(candidate.batch_id),
                values=(
                    f"#{candidate.batch_id}",
                    self._format_schedule(candidate.scheduled_at),
                    len(candidate.old_text),
                    candidate.limit,
                    "—",
                    self.t("очікує"),
                ),
            )

        ttk.Label(right, text="Схвалений текст у чинній черзі").grid(row=0, column=0, sticky="w")
        self.old_text = ScrolledText(right, wrap="word", height=11)
        self.old_text.grid(row=1, column=0, sticky="nsew", pady=(3, 8))
        self.old_text.configure(state="disabled")

        top_new = ttk.Frame(right)
        top_new.grid(row=2, column=0, sticky="ew")
        top_new.columnconfigure(0, weight=1)
        ttk.Label(top_new, text="Новий текст для черги, можна виправити вручну").grid(row=0, column=0, sticky="w")
        self.count_var = tk.StringVar(value="0 / 0")
        ttk.Label(top_new, textvariable=self.count_var).grid(row=0, column=1, sticky="e")

        self.warning_var = tk.StringVar(value="")
        ttk.Label(right, textvariable=self.warning_var, foreground="#8a5a00", wraplength=650).grid(
            row=3, column=0, sticky="ew", pady=(2, 3)
        )
        self.new_text = ScrolledText(right, wrap="word", height=11)
        self.new_text.grid(row=4, column=0, sticky="nsew")
        self.new_text.bind("<KeyRelease>", self._on_text_changed)

        actions = ttk.Frame(outer)
        actions.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        actions.columnconfigure(1, weight=1)
        self.generate_button = ttk.Button(
            actions,
            text="Переробити всі через Ollama",
            command=self._generate_all,
        )
        self.generate_button.grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(actions, mode="indeterminate", length=240)
        self.progress.grid(row=0, column=1, padx=12, sticky="w")
        self.apply_button = ttk.Button(
            actions,
            text="Застосувати готові тексти до черги",
            command=self._apply,
            state="disabled",
        )
        self.apply_button.grid(row=0, column=2, padx=(8, 0))
        self.abort_button = ttk.Button(
            actions,
            text="Закрити програму без змін",
            command=self._abort,
        )
        self.abort_button.grid(row=0, column=3, padx=(8, 0))

        localize_widget_tree(window, self.language)
        if self.order:
            self.tree.selection_set(str(self.order[0]))
            self.tree.focus(str(self.order[0]))
            self._load_candidate(self.order[0])

    def t(self, text: str) -> str:
        return tr(text, self.language)

    @staticmethod
    def _format_schedule(value: str) -> str:
        try:
            parsed = datetime.fromisoformat(str(value))
            return parsed.astimezone(KYIV).strftime("%d.%m.%Y %H:%M")
        except (TypeError, ValueError):
            return str(value)

    def _set_busy(self, busy: bool, text: str = "") -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.generate_button.configure(state=state)
        self.abort_button.configure(state=state)
        self.new_text.configure(state="disabled" if busy else "normal")
        if busy:
            self.apply_button.configure(state="disabled")
            self.progress.start(12)
        else:
            self.progress.stop()
            self._refresh_apply_state()
        if text:
            self.status_var.set(text)

    def _save_current(self) -> None:
        if self.current_batch_id is None or self.busy:
            return
        self.drafts[self.current_batch_id] = self.new_text.get("1.0", "end-1c").strip()
        self._refresh_row(self.current_batch_id)

    def _load_candidate(self, batch_id: int) -> None:
        self.current_batch_id = batch_id
        candidate = self.candidates[batch_id]
        self.old_text.configure(state="normal")
        self.old_text.delete("1.0", "end")
        self.old_text.insert("1.0", candidate.old_text)
        self.old_text.configure(state="disabled")
        self.new_text.configure(state="normal")
        self.new_text.delete("1.0", "end")
        self.new_text.insert("1.0", self.drafts.get(batch_id, ""))
        if self.busy:
            self.new_text.configure(state="disabled")
        self._update_metrics()

    def _on_select(self, _event: object = None) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        new_id = int(selected[0])
        if self.current_batch_id is not None and self.current_batch_id != new_id:
            self._save_current()
        self._load_candidate(new_id)

    def _on_text_changed(self, _event: object = None) -> None:
        if self.current_batch_id is None or self.busy:
            return
        self.drafts[self.current_batch_id] = self.new_text.get("1.0", "end-1c").strip()
        self.errors.pop(self.current_batch_id, None)
        self._refresh_row(self.current_batch_id)
        self._update_metrics()
        self._refresh_apply_state()

    def _update_metrics(self) -> None:
        if self.current_batch_id is None:
            self.count_var.set("0 / 0")
            self.warning_var.set("")
            return
        candidate = self.candidates[self.current_batch_id]
        draft = self.new_text.get("1.0", "end-1c").strip()
        self.count_var.set(f"{len(draft)} / {candidate.limit}")
        warnings = critical_fact_warnings(candidate.old_text, draft, language=self.language) if draft else []
        error = self.errors.get(self.current_batch_id, "")
        self.warning_var.set(error or "; ".join(warnings))

    def _refresh_row(self, batch_id: int) -> None:
        candidate = self.candidates[batch_id]
        draft = self.drafts.get(batch_id, "").strip()
        error = self.errors.get(batch_id, "")
        if error:
            state = "помилка, можна виправити вручну"
        elif not draft:
            state = "очікує"
        elif len(draft) > candidate.limit:
            state = "перевищено ліміт"
        else:
            warnings = critical_fact_warnings(candidate.old_text, draft, language=self.language)
            state = "готово, перевірте факти" if warnings else "готово"
        values = list(self.tree.item(str(batch_id), "values"))
        values[4] = len(draft) if draft else "—"
        values[5] = state
        values[5] = self.t(str(values[5]))
        self.tree.item(str(batch_id), values=values)

    def _refresh_apply_state(self) -> None:
        valid = bool(self.order) and all(
            self.drafts.get(batch_id, "").strip()
            and len(self.drafts[batch_id].strip()) <= self.candidates[batch_id].limit
            for batch_id in self.order
        )
        self.apply_button.configure(state="normal" if valid and not self.busy else "disabled")

    def _generate_all(self) -> None:
        self._save_current()
        if not self.config.ollama_model.strip():
            self.msg.showerror(
                "Ollama не налаштована",
                "У чинних налаштуваннях не вибрана основна модель Ollama. "
                "Тексти можна скоротити вручну або спочатку повернутися до FIX26 і зберегти модель.",
                parent=self.window,
            )
            return
        self._set_busy(True, "Ollama послідовно стискає тексти. Черга та планувальник залишаються вимкненими.")

        def runner() -> None:
            results: dict[int, tuple[str, str, bool]] = {}
            errors: dict[int, str] = {}
            primary = OllamaClient(self.config.ollama_base_url, timeout=240, load_timeout=120)
            fallback = OllamaClient(self.config.ollama_base_url, timeout=180, load_timeout=120)
            for index, batch_id in enumerate(self.order, start=1):
                candidate = self.candidates[batch_id]
                try:
                    results[batch_id] = compress_approved_text(
                        candidate.old_text,
                        candidate.limit,
                        primary_client=primary,
                        primary_model=self.config.ollama_model,
                        fallback_client=fallback,
                        fallback_model=self.config.ollama_fallback_model,
                        language=self.language,
                    )
                except QueueMigrationError as exc:
                    errors[batch_id] = str(exc)
                self.parent.after(
                    0,
                    lambda i=index, total=len(self.order), bid=batch_id: self.status_var.set(
                        self.t(f"Оброблено {i}/{total}: пакет #{bid}.")
                    ),
                )

            def finish() -> None:
                for batch_id, (text, model, used_fallback) in results.items():
                    self.drafts[batch_id] = text
                    self.models[batch_id] = model + (" (запасна)" if used_fallback else "")
                    self.errors.pop(batch_id, None)
                    self._refresh_row(batch_id)
                for batch_id, error in errors.items():
                    self.errors[batch_id] = error
                    self._refresh_row(batch_id)
                if self.current_batch_id is not None:
                    self._load_candidate(self.current_batch_id)
                self._set_busy(
                    False,
                    "Автоматичне стискання завершено. Перегляньте кожен текст і за потреби виправте вручну.",
                )

            self.parent.after(0, finish)

        threading.Thread(target=runner, name="queue-900-migration-ollama", daemon=True).start()

    def _apply(self) -> None:
        self._save_current()
        invalid = [
            batch_id
            for batch_id in self.order
            if not self.drafts.get(batch_id, "").strip()
            or len(self.drafts[batch_id].strip()) > self.candidates[batch_id].limit
        ]
        if invalid:
            self.msg.showerror(
                "Не всі тексти готові",
                "Виправте пакети: " + ", ".join(f"#{item}" for item in invalid),
                parent=self.window,
            )
            return
        if not self.msg.askyesno(
            "Застосувати до черги",
            "Програма спочатку створить повний backup Data, а потім однією транзакцією "
            "замінить лише тексти неопублікованих цілей. Продовжити?",
            parent=self.window,
        ):
            return
        self._set_busy(True, "Створюється backup і атомарно оновлюються тексти черги…")

        def runner() -> None:
            try:
                updates: list[dict[str, object]] = []
                for batch_id in self.order:
                    candidate = self.candidates[batch_id]
                    new_text = self.drafts[batch_id].strip()
                    updates.append(
                        {
                            "batch_id": batch_id,
                            "group_id": candidate.group_id,
                            "scheduled_at": candidate.scheduled_at,
                            "old_text": candidate.old_text,
                            "new_text": new_text,
                            "limit": candidate.limit,
                            "platforms": candidate.platforms,
                            "expected_payloads": {
                                target_id: row[2] for target_id, row in candidate.targets.items() if row[1] != "sent"
                            },
                            "payloads": build_target_payloads(candidate, new_text),
                        }
                    )
                backup = create_backup()
                count = self.db.apply_queue_text_migration(
                    QUEUE_900_MIGRATION_KEY,
                    updates,
                    backup_path=str(backup),
                )
            except Exception as exc:  # shown verbatim only locally, no secrets are expected in these errors
                self.parent.after(0, lambda: self._apply_failed(str(exc)))
                return
            self.parent.after(0, lambda: self._apply_succeeded(count, str(backup)))

        threading.Thread(target=runner, name="queue-900-migration-apply", daemon=True).start()

    def _apply_failed(self, error: str) -> None:
        self._set_busy(False, "Оновлення не застосовано. Чинна черга залишилася без змін.")
        self.msg.showerror("Не вдалося оновити чергу", error, parent=self.window)

    def _apply_succeeded(self, count: int, backup: str) -> None:
        self._set_busy(False, f"Оновлено пакетів: {count}. Backup: {backup}")
        self.msg.showinfo(
            "Чергу оновлено",
            f"Оновлено пакетів: {count}.\n\nПовний backup створено тут:\n{backup}\n\n"
            "Планувальник буде увімкнений після закриття цього вікна.",
            parent=self.window,
        )
        self.window.grab_release()
        self.window.destroy()
        self.on_complete()

    def _abort(self) -> None:
        if self.busy:
            return
        if not self.msg.askyesno(
            "Закрити без змін",
            "Програма закриється, публікація не запускатиметься, а черга залишиться без змін. Продовжити?",
            parent=self.window,
        ):
            return
        self.window.grab_release()
        self.window.destroy()
        self.on_abort()
