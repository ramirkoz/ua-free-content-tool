from __future__ import annotations

from datetime import datetime

from ..collector_backfill_v1_4_rc20 import (
    collect_source_rc20,
    mark_rc20_upgrade_backfill_done,
    rc20_upgrade_backfill_done,
    recovery_not_before,
)
from ..source_health import (
    ensure_source_health,
    record_source_error,
    record_source_success,
)
from .v1_4_rc19_window import MainWindow as Rc19MainWindow


class MainWindow(Rc19MainWindow):
    """v1.4.0-rc20: recover same-day source gaps instead of seeing only the latest page."""

    VERSION_LABEL = "1.4.0-rc20"

    def __init__(self, root, database, config) -> None:
        # The marker is deliberately release-specific. Existing RC19 Data may
        # have a recent last_checked_at even though earlier same-day Telegram
        # posts were never fetched because the legacy preview stopped at 30.
        self._rc20_upgrade_pending_source_ids: set[int] = set()
        super().__init__(root, database, config)
        if not rc20_upgrade_backfill_done():
            self._rc20_upgrade_pending_source_ids = {
                int(source.id)
                for source in self.db.list_sources(enabled_only=True)
                if source.id is not None
            }
            if not self._rc20_upgrade_pending_source_ids:
                mark_rc20_upgrade_backfill_done()
        self._apply_v14_labels()

    def _apply_v14_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v1.4.0-rc20")

    def _apply_source_health_labels(self) -> None:
        super()._apply_source_health_labels()
        tree = getattr(self, "sources_tree", None)
        if tree is None or "errors" not in tuple(tree.cget("columns")):
            return
        language = self._source_health_language()
        tree.heading(
            "errors",
            text="Errors (total)" if language == "en" else "Помилок (всього)",
        )

    def _collect(self, source_ids: set[int] | None) -> tuple[int, list[str]]:
        """Collect with bounded recovery while preserving persistent source health.

        * First RC20 run: every enabled source is recovered from working-day 00:00.
        * Later automatic runs: the ordinary cheap poll is used when checks are
          continuous; a detected gap is recovered with a small overlap.
        * Explicit source collection, if invoked by an inherited/manual action,
          re-reads the current working day for the selected sources.
        """

        total = 0
        errors: list[str] = []
        ensure_source_health(self.db)
        enabled_sources = list(self.db.list_sources(enabled_only=True))
        enabled_ids = {
            int(source.id)
            for source in enabled_sources
            if source.id is not None
        }
        self._rc20_upgrade_pending_source_ids.intersection_update(enabled_ids)

        manual = source_ids is not None
        selected_ids = {int(item) for item in source_ids} if source_ids is not None else None
        zone = self._working_timezone
        now = datetime.now(zone)

        for source in enabled_sources:
            if source.id is None:
                continue
            source_id = int(source.id)
            if selected_ids is not None and source_id not in selected_ids:
                continue
            forced_upgrade_recovery = source_id in self._rc20_upgrade_pending_source_ids
            not_before = recovery_not_before(
                source.last_checked_at,
                now=now,
                zone=zone,
                force_full_day=forced_upgrade_recovery,
                manual=manual,
            )
            try:
                items = collect_source_rc20(
                    source,
                    zone=zone,
                    not_before=not_before,
                )
                inserted = self.db.insert_collected(source_id, items)
                record_source_success(self.db, source_id, inserted)
                total += inserted
                if forced_upgrade_recovery:
                    self._rc20_upgrade_pending_source_ids.discard(source_id)
            except Exception as exc:
                record_source_error(self.db, source_id, exc)
                errors.append(f"{source.name}: {exc}")

        # Only mark the one-time RC19->RC20 repair complete after every enabled
        # source has completed a successful full-day recovery. Failed sources
        # remain pending and are retried next cycle. Re-reading is harmless because
        # the database already deduplicates by source/external-id and content hash.
        if not self._rc20_upgrade_pending_source_ids and not rc20_upgrade_backfill_done():
            mark_rc20_upgrade_backfill_done()

        return total, errors
