from __future__ import annotations

import ctypes
import os


def enable_process_dpi_awareness() -> bool:
    """Enable per-monitor/system DPI awareness before the first Tk root exists."""
    if os.name != "nt":
        return False
    try:
        shcore = ctypes.windll.shcore
        # PROCESS_PER_MONITOR_DPI_AWARE = 2. Windows 8.1+.
        result = int(shcore.SetProcessDpiAwareness(2))
        return result in {0, -2147024891}  # S_OK or E_ACCESSDENIED when already set.
    except Exception:
        try:
            return bool(ctypes.windll.user32.SetProcessDPIAware())
        except Exception:
            return False


__all__ = ["enable_process_dpi_awareness"]
