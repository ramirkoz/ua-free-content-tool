from __future__ import annotations

from datetime import datetime, timezone
import tkinter as tk
from tkinter import simpledialog, ttk

from ..paths import data_dir
from ..publication_policy_v1_2_rc4 import compose_publication_text_rc4
from ..scheduling import KYIV, next_publish_slot
from ..target_presets_v1_2_1 import (
    LAST_SELECTION_LABEL,
    TargetPresetState,
    load_target_preset_state,
    matching_preset_name,
    save_target_preset_state,
)
from . import main_window as legacy_ui
from .v1_2_rc6_window import MainWindow as RC7Window


MANUAL_SELECTION_LABEL = "Ручний вибір"


class MainWindow(RC7Window):
    """v1.2.x window: queue controls, media count and reusable social target sets."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        self._target_preset_path = data_dir() / "publication_target_sets.json"
        self._target_preset_state = load_target_preset_state(self._target_preset_path)
        self._target_preset_syncing = True
        super().__init__(*args, **kwargs)
        # Ancestor RC3 installs its historical composer during startup. The
        # current policy must win after the full MRO has initialized: Facebook
        # + Threads keep donation in comment/reply; LinkedIn + Telegram +
        # Instagram keep it inside the root post/caption.
        legacy_ui.compose_publication_text = compose_publication_text_rc4
        self._ensure_codex_rewrite_label()
        self._install_media_selection_counter()
        self._install_target_preset_controls()
        self._target_preset_syncing = False
        self._refresh_target_preset_controls()
        self.root.title("UA FREE Content Tool — v1.2.1 · Codex + Rowboat")

    def _build_queue_tab(self) -> None:
        super()._build_queue_tab()
        self._install_recalculate_queue_button()

    def _apply_language(self, refresh: bool = True) -> None:
        super()._apply_language(refresh=refresh)
        self._ensure_codex_rewrite_label()
        button = getattr(self, "recalculate_queue_button", None)
        if button is not None:
            button.configure(text="Перерахувати чергу")
        self._update_media_selection_counter()
        self._refresh_target_preset_labels()

    def _install_media_selection_counter(self) -> None:
        tree = getattr(self, "media_candidates_tree", None)
        if tree is None:
            return
        self.media_add_selected_button = None
        for child in tree.master.winfo_children():
            if not isinstance(child, ttk.Button):
                continue
            try:
                label = str(child.cget("text"))
            except Exception:
                continue
            if label in {"Додати вибране", "Використати вибране"}:
                self.media_add_selected_button = child
                break
        tree.bind(
            "<<TreeviewSelect>>",
            lambda _event: self._update_media_selection_counter(),
            add="+",
        )
        self._update_media_selection_counter()

    def _update_media_selection_counter(self) -> None:
        tree = getattr(self, "media_candidates_tree", None)
        button = getattr(self, "media_add_selected_button", None)
        if tree is None or button is None:
            return
        count = len(tree.selection())
        button.configure(text=f"Використати вибране · обрано: {count}")

    def _set_media_candidates(self, candidates):
        super()._set_media_candidates(candidates)
        self._update_media_selection_counter()

    def _ensure_codex_rewrite_label(self) -> None:
        button = getattr(self, "rewrite_button", None)
        if button is not None:
            button.configure(text="Рерайт через Codex / ChatGPT")

    # ------------------------------------------------------------------
    # Reusable social-network target sets.
    # ------------------------------------------------------------------
    def _install_target_preset_controls(self) -> None:
        canvas = getattr(self, "targets_canvas", None)
        if canvas is None:
            return
        parent = canvas.master
        self.target_preset_bar = ttk.Frame(parent)
        self.target_preset_bar.pack(side="top", fill="x", pady=(0, 6), before=canvas)

        self.target_preset_label = ttk.Label(self.target_preset_bar, text="Набір:")
        self.target_preset_label.pack(side="left")
        self.target_preset_var = tk.StringVar(value=LAST_SELECTION_LABEL)
        self.target_preset_combo = ttk.Combobox(
            self.target_preset_bar,
            textvariable=self.target_preset_var,
            state="readonly",
            width=28,
        )
        self.target_preset_combo.pack(side="left", padx=(6, 5))
        self.target_preset_combo.bind("<<ComboboxSelected>>", self._target_preset_selected, add="+")

        self.target_preset_apply_button = ttk.Button(
            self.target_preset_bar,
            text="Застосувати",
            command=self.apply_selected_target_preset,
        )
        self.target_preset_apply_button.pack(side="left", padx=2)
        self.target_preset_save_button = ttk.Button(
            self.target_preset_bar,
            text="Зберегти набір",
            command=self.save_current_target_preset,
        )
        self.target_preset_save_button.pack(side="left", padx=2)
        self.target_preset_rename_button = ttk.Button(
            self.target_preset_bar,
            text="Перейменувати",
            command=self.rename_selected_target_preset,
        )
        self.target_preset_rename_button.pack(side="left", padx=2)
        self.target_preset_delete_button = ttk.Button(
            self.target_preset_bar,
            text="Видалити",
            command=self.delete_selected_target_preset,
        )
        self.target_preset_delete_button.pack(side="left", padx=2)

        self.target_preset_status_var = tk.StringVar(value="")
        self.target_preset_status_label = ttk.Label(
            parent,
            textvariable=self.target_preset_status_var,
            foreground="#666",
        )
        self.target_preset_status_label.pack(side="top", fill="x", pady=(0, 4), before=canvas)

    def _refresh_target_preset_labels(self) -> None:
        if not hasattr(self, "target_preset_label"):
            return
        self.target_preset_label.configure(text="Набір:")
        self.target_preset_apply_button.configure(text="Застосувати")
        self.target_preset_save_button.configure(text="Зберегти набір")
        self.target_preset_rename_button.configure(text="Перейменувати")
        self.target_preset_delete_button.configure(text="Видалити")

    def _target_preset_values(self) -> list[str]:
        return [LAST_SELECTION_LABEL, *self._target_preset_state.presets.keys()]

    def _refresh_target_preset_controls(self, preferred: str | None = None) -> None:
        combo = getattr(self, "target_preset_combo", None)
        if combo is None:
            return
        values = self._target_preset_values()
        combo.configure(values=values)
        wanted = preferred or self._matching_current_target_preset_label()
        if wanted not in values and wanted != MANUAL_SELECTION_LABEL:
            wanted = LAST_SELECTION_LABEL
        self.target_preset_var.set(wanted)
        self._update_target_preset_status()

    def _selected_target_keys(self) -> list[str]:
        return [key for key, variable in self.target_vars.items() if variable.get()]

    def _matching_current_target_preset_label(self) -> str:
        selected = self._selected_target_keys()
        matched = matching_preset_name(self._target_preset_state, selected)
        if matched:
            return matched
        if set(selected) == set(self._target_preset_state.last_targets) and selected:
            return LAST_SELECTION_LABEL
        return MANUAL_SELECTION_LABEL

    def _target_display_name(self, key: str) -> str:
        labels = legacy_ui.target_labels(self.config)
        if key == "instagram":
            name = self.config.instagram_profile_name or self.config.instagram_user_id or "Instagram"
            return f"{name} (Instagram)"
        return labels.get(key, key)

    def _update_target_preset_status(self, intended: list[str] | None = None) -> None:
        status = getattr(self, "target_preset_status_var", None)
        if status is None:
            return
        keys = intended
        if keys is None:
            choice = self.target_preset_var.get().strip()
            if choice == LAST_SELECTION_LABEL:
                keys = list(self._target_preset_state.last_targets)
            elif choice in self._target_preset_state.presets:
                keys = list(self._target_preset_state.presets[choice])
            else:
                keys = self._selected_target_keys()
        unavailable = [
            key
            for key in keys
            if key not in self.target_vars or not self.config.platform_ready(key)
        ]
        if unavailable:
            names = ", ".join(self._target_display_name(key) for key in unavailable)
            status.set(f"У наборі зараз недоступні: {names}")
        elif keys:
            status.set(f"У наборі мереж: {len(keys)}")
        else:
            status.set("Набір ще не сформований")

    def _apply_target_keys(self, keys: list[str]) -> None:
        wanted = set(keys)
        self._target_preset_syncing = True
        try:
            for key, variable in self.target_vars.items():
                variable.set(key in wanted and self.config.platform_ready(key))
            super()._update_selected_targets_summary()
        finally:
            self._target_preset_syncing = False
        self._update_target_preset_status(keys)

    def _save_target_preset_state(self) -> None:
        save_target_preset_state(self._target_preset_path, self._target_preset_state)

    def _remember_last_target_selection(self, targets: list[str]) -> None:
        if not targets:
            return
        self._target_preset_state.last_targets = list(targets)
        self._target_preset_state = self._target_preset_state.normalized()
        self._save_target_preset_state()
        self._refresh_target_preset_controls(
            matching_preset_name(self._target_preset_state, targets) or LAST_SELECTION_LABEL
        )

    def _target_preset_selected(self, _event: object | None = None) -> None:
        self.apply_selected_target_preset()

    def apply_selected_target_preset(self) -> None:
        choice = self.target_preset_var.get().strip()
        if choice == LAST_SELECTION_LABEL:
            keys = list(self._target_preset_state.last_targets)
        else:
            keys = list(self._target_preset_state.presets.get(choice, []))
        if not keys:
            self.msg.showinfo(
                "Набори соцмереж",
                "Цей набір ще порожній. Виберіть мережі вручну та збережіть набір.",
                parent=self.root,
            )
            return
        self._apply_target_keys(keys)
        self._remember_last_target_selection(self._selected_target_keys())
        self._refresh_target_preset_controls(choice if choice in self._target_preset_state.presets else LAST_SELECTION_LABEL)

    def save_current_target_preset(self) -> None:
        targets = self._selected_target_keys()
        if not targets:
            self.msg.showwarning(
                "Набори соцмереж",
                "Спочатку виберіть хоча б одну доступну соцмережу.",
                parent=self.root,
            )
            return
        name = simpledialog.askstring(
            "Зберегти набір соцмереж",
            "Назва набору:",
            parent=self.root,
        )
        if name is None:
            return
        name = name.strip()
        if not name or name in {LAST_SELECTION_LABEL, MANUAL_SELECTION_LABEL}:
            self.msg.showwarning(
                "Набори соцмереж",
                "Вкажіть іншу коротку назву набору.",
                parent=self.root,
            )
            return
        if name in self._target_preset_state.presets and not self.msg.askyesno(
            "Замінити набір",
            f"Набір «{name}» уже існує. Замінити його поточним вибором?",
            parent=self.root,
        ):
            return
        self._target_preset_state.presets[name] = list(targets)
        self._target_preset_state.last_targets = list(targets)
        self._target_preset_state = self._target_preset_state.normalized()
        self._save_target_preset_state()
        self._refresh_target_preset_controls(name)
        self.set_status(f"Збережено набір соцмереж «{name}».")

    def rename_selected_target_preset(self) -> None:
        old_name = self.target_preset_var.get().strip()
        if old_name not in self._target_preset_state.presets:
            self.msg.showinfo(
                "Набори соцмереж",
                "Для перейменування виберіть збережений набір.",
                parent=self.root,
            )
            return
        new_name = simpledialog.askstring(
            "Перейменувати набір",
            "Нова назва:",
            initialvalue=old_name,
            parent=self.root,
        )
        if new_name is None:
            return
        new_name = new_name.strip()
        if not new_name or new_name in {LAST_SELECTION_LABEL, MANUAL_SELECTION_LABEL}:
            return
        if new_name != old_name and new_name in self._target_preset_state.presets:
            self.msg.showwarning(
                "Набори соцмереж",
                f"Набір «{new_name}» уже існує.",
                parent=self.root,
            )
            return
        targets = self._target_preset_state.presets.pop(old_name)
        self._target_preset_state.presets[new_name] = targets
        self._save_target_preset_state()
        self._refresh_target_preset_controls(new_name)
        self.set_status(f"Набір перейменовано на «{new_name}».")

    def delete_selected_target_preset(self) -> None:
        name = self.target_preset_var.get().strip()
        if name not in self._target_preset_state.presets:
            self.msg.showinfo(
                "Набори соцмереж",
                "Для видалення виберіть збережений набір.",
                parent=self.root,
            )
            return
        if not self.msg.askyesno(
            "Видалити набір",
            f"Видалити набір «{name}»? Поточний вибір соцмереж не зміниться.",
            parent=self.root,
        ):
            return
        del self._target_preset_state.presets[name]
        self._save_target_preset_state()
        self._refresh_target_preset_controls(LAST_SELECTION_LABEL)
        self.set_status(f"Набір «{name}» видалено.")

    def _update_selected_targets_summary(self) -> None:
        super()._update_selected_targets_summary()
        if getattr(self, "_target_preset_syncing", True):
            return
        combo = getattr(self, "target_preset_combo", None)
        if combo is None:
            return
        label = self._matching_current_target_preset_label()
        self.target_preset_var.set(label)
        self._update_target_preset_status(self._selected_target_keys())

    def apply_existing_targets(self, statuses: dict[str, str]) -> None:
        self._target_preset_syncing = True
        try:
            super().apply_existing_targets(statuses)
        finally:
            self._target_preset_syncing = False
        if hasattr(self, "target_preset_combo"):
            self._refresh_target_preset_controls(self._matching_current_target_preset_label())

    def apply_recommendations(self, recommendations: list[str]) -> None:
        # For a fresh block, the last actually used selection wins. Automated
        # recommendations are only the fallback when no previous selection was
        # ever stored.
        last = list(self._target_preset_state.last_targets)
        if last:
            self._apply_target_keys(last)
            preferred = matching_preset_name(self._target_preset_state, last) or LAST_SELECTION_LABEL
            if hasattr(self, "target_preset_combo"):
                self._refresh_target_preset_controls(preferred)
            return
        self._target_preset_syncing = True
        try:
            super().apply_recommendations(recommendations)
        finally:
            self._target_preset_syncing = False
        if hasattr(self, "target_preset_combo"):
            self._refresh_target_preset_controls(self._matching_current_target_preset_label())

    def approve_current(self) -> None:
        selected = self._selected_target_keys()
        if selected:
            self._remember_last_target_selection(selected)
        return super().approve_current()

    # ------------------------------------------------------------------
    # Queue recalculation.
    # ------------------------------------------------------------------
    def _install_recalculate_queue_button(self) -> None:
        if not hasattr(self, "queue_tab"):
            return
        children = self.queue_tab.winfo_children()
        if not children:
            return
        toolbar = children[0]
        self.recalculate_queue_button = ttk.Button(
            toolbar,
            text="Перерахувати чергу",
            command=self.recalculate_pending_queue,
        )
        self.recalculate_queue_button.pack(side="left", padx=3)

    def recalculate_pending_queue(self) -> None:
        """Reflow every pending package using the current hours and interval.

        Sent/completed/cancelled/paused packages are untouched. The operation is
        performed under one SQLite write transaction so the publication worker
        cannot claim a package halfway through the recalculation.
        """

        start_hour = int(self.config.publish_start_hour)
        end_hour = int(self.config.publish_end_hour)
        interval = int(self.config.publish_interval_minutes)
        now = datetime.now(KYIV)

        if not self.msg.askyesno(
            "Перерахувати чергу",
            "Перерахувати час усіх пакетів зі статусом «очікує» за поточними налаштуваннями?\n\n"
            f"Вікно: {start_hour:02d}:00–{end_hour:02d}:00. Інтервал: {interval} хв.\n"
            "Уже опубліковані, призупинені, скасовані та пакети, що зараз публікуються, не змінюються.",
            parent=self.root,
        ):
            return

        schedules: list[tuple[int, datetime]] = []
        try:
            with self.db.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                try:
                    active = db.execute(
                        "SELECT id FROM publication_batches WHERE status='in_progress' LIMIT 1"
                    ).fetchone()
                    if active is not None:
                        raise RuntimeError(
                            "Зараз публікується пакет. Дочекайтеся завершення і натисніть «Перерахувати чергу» ще раз."
                        )
                    rows = db.execute(
                        "SELECT id FROM publication_batches "
                        "WHERE status='pending' ORDER BY julianday(scheduled_at), id"
                    ).fetchall()
                    latest: datetime | None = None
                    for row in rows:
                        slot = next_publish_slot(
                            now=now,
                            latest_scheduled=latest,
                            start_hour=start_hour,
                            end_hour=end_hour,
                            interval_minutes=interval,
                        )
                        batch_id = int(row[0])
                        db.execute(
                            "UPDATE publication_batches "
                            "SET scheduled_at=?, updated_at=? "
                            "WHERE id=? AND status='pending'",
                            (
                                slot.astimezone(timezone.utc).isoformat(timespec="seconds"),
                                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                batch_id,
                            ),
                        )
                        schedules.append((batch_id, slot))
                        latest = slot
                    db.execute("COMMIT")
                except Exception:
                    db.execute("ROLLBACK")
                    raise
        except Exception as exc:
            self._show_error(exc)
            return

        self.refresh_queue()
        if hasattr(self, "worker"):
            self.worker.wake()
        if not schedules:
            self.msg.showinfo(
                "Перерахувати чергу",
                "Пакетів зі статусом «очікує» немає.",
                parent=self.root,
            )
            return

        first = schedules[0][1].astimezone(KYIV)
        last = schedules[-1][1].astimezone(KYIV)
        self.msg.showinfo(
            "Чергу перераховано",
            f"Перераховано пакетів: {len(schedules)}.\n"
            f"Перший: {first.strftime('%d.%m.%Y %H:%M')}.\n"
            f"Останній: {last.strftime('%d.%m.%Y %H:%M')} (Київ).",
            parent=self.root,
        )
