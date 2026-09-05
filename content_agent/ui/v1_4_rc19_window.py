from __future__ import annotations

from datetime import timezone

from ..scheduling import KYIV, parse_iso
from .v1_4_rc18_window import MainWindow as Rc18MainWindow


def format_kyiv_ui_timestamp(value: object) -> str:
    """Render a stored ISO timestamp as Kyiv wall-clock time for the UI.

    Storage remains unchanged. Aware timestamps are converted to Europe/Kyiv;
    legacy naive ISO timestamps are treated as UTC because historical collector
    rows were persisted in UTC.
    """

    text = str(value or "").strip()
    if not text:
        return "—"
    if text == "—":
        return text
    parsed = parse_iso(text)
    if parsed is None:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(KYIV).strftime("%d.%m.%Y %H:%M:%S")


def _localize_tree_column(tree: object, column: str) -> None:
    """Convert ISO values in one Treeview column without touching stored data."""

    try:
        item_ids = tree.get_children()  # type: ignore[attr-defined]
    except Exception:
        return
    for item_id in item_ids:
        try:
            current = tree.set(item_id, column)  # type: ignore[attr-defined]
            rendered = format_kyiv_ui_timestamp(current)
            if rendered != current:
                tree.set(item_id, column, rendered)  # type: ignore[attr-defined]
        except Exception:
            continue


class MainWindow(Rc18MainWindow):
    """v1.4.0-rc19: one Kyiv-time presentation rule for visible timestamps."""

    VERSION_LABEL = "1.4.0-rc19"

    def _apply_v14_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v1.4.0-rc19")

    def refresh_sources(self) -> None:
        super().refresh_sources()
        _localize_tree_column(self.sources_tree, "checked")

    def refresh_groups(self) -> None:
        super().refresh_groups()
        _localize_tree_column(self.groups_tree, "published")

    def load_group(self, group_id: int) -> None:
        super().load_group(group_id)
        _localize_tree_column(self.group_sources_tree, "time")
