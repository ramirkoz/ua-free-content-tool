from __future__ import annotations
from contextlib import contextmanager

@contextmanager
def suppress_legacy_titles(root, current_title: str):
    original = root.title
    def guarded(value=None):
        if value is None:
            return original()
        text = str(value)
        # Legacy compatibility layers may still set historical RC titles while
        # they construct. Keep those internal implementation details invisible.
        if "UA FREE Content Tool" in text and "rc" in text.casefold() and current_title not in text:
            return None
        return original(value)
    root.title = guarded
    try:
        yield
    finally:
        root.title = original
        original(current_title)
