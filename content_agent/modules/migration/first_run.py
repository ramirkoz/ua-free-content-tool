from __future__ import annotations

import os
from pathlib import Path
from tkinter import filedialog, messagebox

from ...paths import database_path, data_dir


def maybe_choose_legacy_data(root) -> str | None:
    if database_path().exists() or (data_dir() / "first_run_import.json").exists():
        return None
    try:
        answer = messagebox.askyesno(
            "UA FREE Content Tool",
            "Імпортувати робочі дані з попередньої версії?\n\n"
            "Буде перенесено лише база та налаштування. Логи, кеш, backups, temp, старі Tools і службові дампи не переносяться.",
            parent=root,
        )
    except Exception:
        answer = False
    if not answer:
        (data_dir()/"first_run_import.json").write_text('{"imported": false, "skipped": true}', encoding="utf-8")
        return None
    selected = filedialog.askdirectory(title="Виберіть стару папку Data Content Tool", parent=root)
    if not selected:
        return None
    source = Path(selected).expanduser().resolve()
    if not (source / "content_agent.sqlite3").exists():
        messagebox.showerror("Імпорт", "У вибраній папці немає content_agent.sqlite3.", parent=root)
        return None
    os.environ["UA_FREE_LEGACY_DATA_ROOT"] = str(source)
    return str(source)
