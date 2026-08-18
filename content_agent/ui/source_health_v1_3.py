from __future__ import annotations

from ..collectors import collect_source
from ..source_health import (
    ensure_source_health,
    record_source_error,
    record_source_success,
    source_health_map,
)


_COLUMNS = ("id", "kind", "name", "health", "yield", "last_new", "errors", "checked", "url")
_WIDTHS = {
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
_LABELS = {
    "uk": {
        "id": "ID",
        "kind": "Тип",
        "name": "Назва",
        "health": "Стан джерела",
        "yield": "Нових",
        "last_new": "Останній новий",
        "errors": "Помилок",
        "checked": "Остання перевірка",
        "url": "Адреса",
    },
    "en": {
        "id": "ID",
        "kind": "Type",
        "name": "Name",
        "health": "Source health",
        "yield": "New",
        "last_new": "Last new item",
        "errors": "Errors",
        "checked": "Last check",
        "url": "Address",
    },
}


class SourceHealthV13Mixin:
    """Add persistent source diagnostics without changing the v1.2.2 DB schema."""

    def _source_health_language(self) -> str:
        value = str(getattr(getattr(self, "config", None), "ui_language", "uk") or "uk").casefold()
        return "en" if value.startswith("en") else "uk"

    def _apply_source_health_labels(self) -> None:
        tree = getattr(self, "sources_tree", None)
        if tree is None:
            return
        labels = _LABELS[self._source_health_language()]
        for column in _COLUMNS:
            tree.heading(column, text=labels[column])

    def _build_sources_tab(self) -> None:
        ensure_source_health(self.db)  # type: ignore[attr-defined]
        super()._build_sources_tab()  # type: ignore[misc]
        tree = self.sources_tree  # type: ignore[attr-defined]
        tree.configure(columns=_COLUMNS)
        for column in _COLUMNS:
            tree.column(column, width=_WIDTHS[column], anchor="w")
        self._apply_source_health_labels()

    def _apply_language(self, refresh: bool = True) -> None:
        super()._apply_language(refresh=refresh)  # type: ignore[misc]
        self._apply_source_health_labels()

    def _health_label(self, health: object | None) -> str:
        language = self._source_health_language()
        if health is None:
            return "— no data" if language == "en" else "— немає даних"

        last_error_at = str(getattr(health, "last_error_at", "") or "")
        last_success_at = str(getattr(health, "last_success_at", "") or "")
        has_current_error = bool(last_error_at and (not last_success_at or last_error_at >= last_success_at))
        if has_current_error:
            state = "🔴 error" if language == "en" else "🔴 помилка"
        elif last_success_at:
            state = "🟢 working" if language == "en" else "🟢 працює"
        else:
            state = "— no data" if language == "en" else "— немає даних"

        error = str(getattr(health, "last_error", "") or "").strip()
        if has_current_error and error:
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
