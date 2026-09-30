from __future__ import annotations


class InboxTabController:
    """Controller boundary around the inherited Inbox widgets.

    RC50 keeps the proven Tk widgets but stops adding behavior through another
    MainWindow subclass. New Inbox actions are routed through this controller.
    """

    def __init__(self, owner) -> None:
        self.owner = owner

    def focus_search(self):
        entry = getattr(self.owner, "_rc14_keyword_entry", None)
        if entry is None:
            return None
        entry.focus_set()
        try:
            entry.selection_range(0, "end")
        except Exception:
            pass
        return "break"

    def clear_search(self):
        variable = getattr(self.owner, "keyword_search_var", None)
        if variable is not None:
            variable.set("")
        return "break"

    def reset_filters(self) -> None:
        self.owner.reset_manual_topic_filters()

    def refresh(self) -> None:
        self.owner.refresh_groups()
