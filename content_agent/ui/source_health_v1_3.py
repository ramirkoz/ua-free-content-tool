from __future__ import annotations

from ..collectors import collect_source
from ..source_health import (
    ensure_source_health,
    record_source_error,
    record_source_success,
    source_health_map,
)


class SourceHealthV13Mixin:
    """Add persistent source diagnostics without changing the v1.2.2 DB schema."""

    def _build_sources_tab(self) -> None:
        ensure_source_health(self.db)  # type: ignore[attr-defined]
        super()._build_sources_tab()  # type: ignore[misc]
        tree = self.sources_tree  # type: ignore[attr-defined]
        columns = ("id", "kind", "name", "health", "yield", "last_new", "errors", "checked", "url")
        tree.configure(columns=columns)
        labels = {
            "id": "ID",
            "kind": "Тип",
            "name": "Назва",
            "health": "Стан джерела",
            "yield": "Нових",
            "last_new": "Останній новий",
            "errors": "Помилок",
            "checked": "Остання перевірка",
            "url": "Адреса",
        }
        widths = {
            "id": 55,
            "kind": 80,
            "name": 190,
            "health": 220,
            "yield": 65,
            "last_new": 165,
            "errors": 70,
            "checked": 165,
            "url": 400,
        }
        for column in columns:
            tree.heading(column, text=labels[column])
            tree.column(column, width=widths[column], anchor="w")

    @staticmethod
    def _health_label(health: object | None) -> str:
        if health is None:
            return "— немає даних"
        state = str(getattr(health, "state", "— немає даних"))
        error = str(getattr(health, "last_error", "") or "").strip()
        if state.startswith("🔴") and error:
            compact = " ".join(error.split())
            if len(compact) > 90:
                compact = compact[:87].rstrip() + "…"
            return f"{state}: {compact}"
        return state

    def refresh_sources(self) -> None:
        ensure_source_health(self.db)  # type: ignore[attr-defined]
        health_by_id = source_health_map(self.db)  # type: ignore[attr-defined]
        tree = self.sources_tree  # type: ignore[attr-defined]
        tree.delete(*tree.get_children())
        for source in self.db.list_sources():  # type: ignore[attr-defined]
            source_id = int(source.id)
            health = health_by_id.get(source_id)
            tree.insert(
                "",
                "end",
                iid=str(source_id),
                values=(
                    source_id,
                    source.kind,
                    source.name,
                    self._health_label(health),
                    getattr(health, "last_inserted_count", 0) if health else 0,
                    (getattr(health, "last_new_at", "") or "—") if health else "—",
                    getattr(health, "total_errors", 0) if health else 0,
                    source.last_checked_at or "—",
                    source.url,
                ),
            )

    def _collect(self, source_ids: set[int] | None) -> tuple[int, list[str]]:
        total = 0
        errors: list[str] = []
        ensure_source_health(self.db)  # type: ignore[attr-defined]
        for source in self.db.list_sources(enabled_only=True):  # type: ignore[attr-defined]
            if source_ids is not None and source.id not in source_ids:
                continue
            try:
                items = collect_source(source)
                inserted = self.db.insert_collected(int(source.id), items)  # type: ignore[attr-defined]
                record_source_success(self.db, int(source.id), inserted)  # type: ignore[attr-defined]
                total += inserted
            except Exception as exc:
                record_source_error(self.db, int(source.id), exc)  # type: ignore[attr-defined]
                errors.append(f"{source.name}: {exc}")
        return total, errors
