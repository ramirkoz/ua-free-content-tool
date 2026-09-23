from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

_ROOT = Path(sys.executable).resolve().parent
_RUNTIME = _ROOT / "_runtime"
os.environ.setdefault("UA_FREE_PORTABLE_ROOT", str(_ROOT))
os.environ.setdefault("PYTHONNOUSERSITE", "1")

_tcl_root = _RUNTIME / "tcl"
for _name in ("tcl8.6", "tcl8.7"):
    _p = _tcl_root / _name
    if _p.is_dir():
        os.environ.setdefault("TCL_LIBRARY", str(_p))
        break
for _name in ("tk8.6", "tk8.7"):
    _p = _tcl_root / _name
    if _p.is_dir():
        os.environ.setdefault("TK_LIBRARY", str(_p))
        break


def _report_bootstrap_error(exc: BaseException) -> None:
    detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    try:
        logs = _ROOT / "Data" / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "bootstrap_error.log").write_text(detail, encoding="utf-8")
    except Exception:
        pass
    try:
        import tkinter as tk
        from tkinter import messagebox
        ui = tk.Tk()
        ui.withdraw()
        messagebox.showerror(
            "UA FREE Content Tool",
            "Не вдалося запустити Content Tool.\n\n"
            "Деталі записані в Data\\logs\\bootstrap_error.log\n\n" + str(exc),
            parent=ui,
        )
        ui.destroy()
    except Exception:
        pass


if (
    Path(sys.executable).name.casefold() == "ua_free_content_tool.exe"
    and os.environ.get("UA_FREE_CHILD_PROCESS") != "1"
    and len(sys.argv) == 1
):
    try:
        from content_agent.main import main
        _code = int(main() or 0)
    except SystemExit:
        raise
    except BaseException as _exc:
        _report_bootstrap_error(_exc)
        raise SystemExit(1)
    raise SystemExit(_code)
