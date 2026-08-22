from __future__ import annotations

import logging
import tkinter as tk
from tkinter import messagebox

from .config import AppConfig, ConfigError, load_config
from .database import Database
from .instance_lock import AlreadyRunning, InstanceLock
from .logging_setup import configure_logging
from .paths import portable_mode
from .portable import PortableMigrationError, ensure_portable_data_migrated
from .ui.v1_3_window import MainWindow


def main() -> int:
    try:
        migration = ensure_portable_data_migrated()
    except PortableMigrationError as exc:
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("UA FREE Content Tool", str(exc), parent=root)
            root.destroy()
        except tk.TclError:
            pass
        return 1

    logger = configure_logging()
    if migration.migrated:
        logger.info("Portable data imported from the previous local installation.")
    try:
        with InstanceLock():
            try:
                config = load_config()
            except ConfigError as exc:
                logger.error("Configuration could not be opened: %s", exc)
                if portable_mode():
                    raise
                config = AppConfig()
            database = Database()
            database.quick_check()
            root = tk.Tk()
            MainWindow(root, database, config)
            root.mainloop()
            return 0
    except AlreadyRunning as exc:
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showwarning("UA FREE Content Tool", str(exc), parent=root)
            root.destroy()
        except tk.TclError:
            pass
        return 2
    except Exception as exc:
        logger.error("Application startup failed: %s", exc)
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("UA FREE Content Tool", str(exc), parent=root)
            root.destroy()
        except tk.TclError:
            pass
        return 1
