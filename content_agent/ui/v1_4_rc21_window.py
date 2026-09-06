from __future__ import annotations

from datetime import datetime
import tkinter as tk
from tkinter import ttk

from ..collector_daily_coverage_v1_4_rc21 import (
    collect_source_rc21,
    coverage_summary,
    load_coverage_state,
    recovery_not_before,
    save_coverage_state,
    source_coverage_complete,
    update_source_coverage,
    working_day_start,
)
from ..source_health import ensure_source_health, record_source_error, record_source_success
from .v1_4_rc20_window import MainWindow as Rc20MainWindow


class MainWindow(Rc20MainWindow):
    """v1.4.0-rc21: proven current-day source coverage and visible daily flow size."""

    VERSION_LABEL = "1.4.0-rc21"

    def __init__(self, root, database, config) -> None:
        self.today_flow_var = tk.StringVar(master=root, value="Новин сьогодні: …")
        self._rc21_flow_label: ttk.Label | None = None
        super().__init__(root, database, config)
        self._install_daily_flow_label()
        self._apply_v14_labels()
        self._refresh_daily_flow_status()

    def _apply_v14_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v1.4.0-rc21")

    def _apply_language(self, refresh: bool = True) -> None:
        super()._apply_language(refresh=refresh)
        self._apply_v14_labels()
        self._refresh_daily_flow_status()

    def _install_daily_flow_label(self) -> None:
        if self._rc21_flow_label is not None:
            return
        bar = getattr(self, "_rc14_inbox_tools_frame", None)
        if bar is None:
            return
        ttk.Separator(bar, orient="vertical").pack(side="right", fill="y", padx=(10, 8))
        label = ttk.Label(bar, textvariable=self.today_flow_var, font="TkHeadingFont")
        label.pack(side="right", padx=(8, 0))
        self._rc21_flow_label = label

    def _eligible_coverage_source_ids(self) -> set[int]:
        return {
            int(source.id)
            for source in self.db.list_sources(enabled_only=True)
            if source.id is not None and source.kind in {"telegram", "rss"}
        }

    def _refresh_daily_flow_status(self) -> None:
        variable = getattr(self, "today_flow_var", None)
        zone = getattr(self, "_working_timezone", None)
        if variable is None or zone is None:
            return
        try:
            now = datetime.now(zone)
            count = int(self.db.count_today_articles(now=now))
            day = now.date().isoformat()
            coverage = load_coverage_state(working_date=day)
            complete, total = coverage_summary(coverage, self._eligible_coverage_source_ids())
        except Exception:
            return

        count_text = f"{count:,}".replace(",", " ")
        english = bool(getattr(self, "_is_english", lambda: False)())
        if total:
            mark = "✓" if complete == total else "⚠"
            if english:
                variable.set(f"News today: {count_text} · source coverage: {complete}/{total} {mark}")
            else:
                variable.set(f"Новин сьогодні: {count_text} · покриття джерел: {complete}/{total} {mark}")
        else:
            variable.set(("News today: " if english else "Новин сьогодні: ") + count_text)

    def refresh_groups(self) -> None:
        super().refresh_groups()
        self._refresh_daily_flow_status()

    def _collect(self, source_ids: set[int] | None) -> tuple[int, list[str]]:
        """Collect without ever mistaking a partial Telegram tail for a full day.

        Each working date has its own per-source coverage state. Telegram coverage
        becomes complete only after pagination actually crosses the local midnight
        boundary. RSS coverage means the entire currently exposed feed was exhausted.
        Until that proof exists, every automatic cycle retries full-day recovery.
        """
        total_inserted = 0
        errors: list[str] = []
        ensure_source_health(self.db)

        enabled_sources = list(self.db.list_sources(enabled_only=True))
        selected_ids = {int(item) for item in source_ids} if source_ids is not None else None
        manual = selected_ids is not None
        zone = self._working_timezone
        now = datetime.now(zone)
        day_start = working_day_start(now=now, zone=zone)
        coverage = load_coverage_state(working_date=day_start.date().isoformat())

        for source in enabled_sources:
            if source.id is None:
                continue
            source_id = int(source.id)
            if selected_ids is not None and source_id not in selected_ids:
                continue

            coverage_eligible = source.kind in {"telegram", "rss"}
            baseline_required = coverage_eligible and not source_coverage_complete(coverage, source_id)
            require_full_day = bool(baseline_required or (manual and coverage_eligible))
            if require_full_day:
                not_before = day_start
            else:
                not_before = recovery_not_before(
                    source.last_checked_at,
                    now=now,
                    zone=zone,
                    force_full_day=False,
                    manual=False,
                )

            try:
                result = collect_source_rc21(
                    source,
                    zone=zone,
                    not_before=not_before,
                    require_full_day=require_full_day,
                )
                inserted = self.db.insert_collected(source_id, result.items)
                record_source_success(self.db, source_id, inserted)
                total_inserted += inserted

                if require_full_day:
                    update_source_coverage(
                        coverage,
                        source=source,
                        result=result,
                        checked_at=now,
                    )
                    save_coverage_state(coverage)
                    if not result.complete:
                        errors.append(
                            f"{source.name}: неповне покриття поточної доби — {result.detail}"
                        )
            except Exception as exc:
                record_source_error(self.db, source_id, exc)
                errors.append(f"{source.name}: {exc}")

        try:
            save_coverage_state(coverage)
        except Exception as exc:
            errors.append(f"Не вдалося зберегти стан покриття джерел: {exc}")

        return total_inserted, errors
