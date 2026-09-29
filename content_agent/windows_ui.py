from __future__ import annotations

import os


def enable_dpi_awareness() -> bool:
    """Enable best available Windows DPI awareness before Tk creates a window."""
    if os.name != "nt":
        return False
    try:
        import ctypes

        user32 = ctypes.windll.user32
        setter = getattr(user32, "SetProcessDpiAwarenessContext", None)
        if setter is not None:
            # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 == -4
            if bool(setter(ctypes.c_void_p(-4))):
                return True
        legacy = getattr(user32, "SetProcessDPIAware", None)
        if legacy is not None:
            return bool(legacy())
    except Exception:
        return False
    return False


__all__ = ["enable_dpi_awareness"]
