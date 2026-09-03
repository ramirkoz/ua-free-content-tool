from __future__ import annotations

import faulthandler
import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from .config import AppConfig, ConfigError, load_config
from .database_v1_4_rc11 import Database
from .instance_lock import AlreadyRunning, InstanceLock
from .logging_setup import configure_logging
from .paths import data_dir, portable_mode
from .portable import PortableMigrationError, ensure_portable_data_migrated
from .ui.v1_4_rc12_window import MainWindow


def _show_startup_error(root: tk.Tk, message: str) -> None:
    try:
        messagebox.showerror("UA FREE Content Tool", message, parent=root)
    except tk.TclError:
        pass


def _run_ui_startup(root: tk.Tk, logger: object) -> int:
    root.title("UA FREE Content Tool — v1.4.0-rc12 · запуск")
    root.geometry("560x150")
    root.minsize(520, 140)

    frame = ttk.Frame(root, padding=18)
    frame.pack(fill="both", expand=True)
    status_var = tk.StringVar(value="Запуск: підготовка…")
    ttk.Label(frame, text="UA FREE Content Tool v1.4.0-rc12", font="TkHeadingFont").pack(anchor="w")
    ttk.Label(frame, textvariable=status_var, wraplength=500).pack(anchor="w", pady=(10, 8))
    progress = ttk.Progressbar(frame, mode="indeterminate")
    progress.pack(fill="x")
    progress.start(12)

    result_queue: queue.Queue[tuple[str, object]] = queue.Queue()
    progress_queue: queue.Queue[str] = queue.Queue()
    stop_watchdog = threading.Event()
    pulse_lock = threading.Lock()
    pulse = {"last": time.monotonic(), "stage": "create_window", "dumped": 0.0}

    def set_stage(stage: str) -> None:
        with pulse_lock:
            pulse["stage"] = stage
        progress_queue.put(stage)
        logger.info("STARTUP stage=%s begin", stage)  # type: ignore[attr-defined]

    def startup_worker() -> None:
        try:
            set_stage("portable_migration")
            migration_started = time.monotonic()
            migration = ensure_portable_data_migrated()
            logger.info(  # type: ignore[attr-defined]
                "STARTUP stage=portable_migration end duration=%.3fs migrated=%s",
                time.monotonic() - migration_started,
                migration.migrated,
            )

            set_stage("config")
            config_started = time.monotonic()
            try:
                config = load_config()
            except ConfigError as exc:
                logger.error("Configuration could not be opened: %s", exc)  # type: ignore[attr-defined]
                if portable_mode():
                    raise
                config = AppConfig()
            logger.info(  # type: ignore[attr-defined]
                "STARTUP stage=config end duration=%.3fs", time.monotonic() - config_started
            )

            set_stage("database_init")
            database_started = time.monotonic()
            database = Database()
            logger.info(  # type: ignore[attr-defined]
                "STARTUP stage=database_init end duration=%.3fs", time.monotonic() - database_started
            )

            set_stage("database_quick_check")
            check_started = time.monotonic()
            database.quick_check()
            logger.info(  # type: ignore[attr-defined]
                "STARTUP stage=database_quick_check end duration=%.3fs", time.monotonic() - check_started
            )
            result_queue.put(("ok", (database, config, migration)))
        except Exception as exc:
            result_queue.put(("error", exc))

    def pulse_ui() -> None:
        if stop_watchdog.is_set():
            return
        with pulse_lock:
            pulse["last"] = time.monotonic()
        try:
            root.after(200, pulse_ui)
        except tk.TclError:
            return

    def watchdog() -> None:
        while not stop_watchdog.wait(2.0):
            now = time.monotonic()
            with pulse_lock:
                lag = now - float(pulse["last"])
                stage = str(pulse["stage"])
                dumped = float(pulse["dumped"])
            if lag < 8.0 or now - dumped < 30.0:
                continue
            with pulse_lock:
                pulse["dumped"] = now
            try:
                path = data_dir() / "ui_startup_freeze_trace.log"
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(
                        f"\n=== STARTUP UI FREEZE {datetime.now().isoformat(timespec='seconds')} "
                        f"stage={stage} lag={lag:.1f}s ===\n"
                    )
                    handle.flush()
                    faulthandler.dump_traceback(file=handle, all_threads=True)
            except Exception:
                pass

    def poll_result() -> None:
        latest_stage = None
        while True:
            try:
                latest_stage = progress_queue.get_nowait()
            except queue.Empty:
                break
        if latest_stage:
            status_var.set("Запуск: " + latest_stage.replace("_", " ") + "…")
        try:
            kind, payload = result_queue.get_nowait()
        except queue.Empty:
            try:
                root.after(100, poll_result)
            except tk.TclError:
                pass
            return

        if kind != "ok":
            stop_watchdog.set()
            progress.stop()
            error = payload if isinstance(payload, Exception) else RuntimeError(str(payload))
            logger.error("Application startup failed: %s", error)  # type: ignore[attr-defined]
            status_var.set("Запуск не завершено.")
            _show_startup_error(root, str(error))
            root.destroy()
            return

        database, config, migration = payload  # type: ignore[misc]
        if migration.migrated:
            logger.info("Portable data imported from the previous local installation.")  # type: ignore[attr-defined]
        progress.stop()
        frame.destroy()
        with pulse_lock:
            pulse["stage"] = "build_main_window"
        build_started = time.monotonic()
        try:
            MainWindow(root, database, config)
        except Exception as exc:
            stop_watchdog.set()
            logger.error("Application UI startup failed: %s", exc)
            _show_startup_error(root, str(exc))
            root.destroy()
            return
        logger.info(  # type: ignore[attr-defined]
            "STARTUP stage=build_main_window end duration=%.3fs", time.monotonic() - build_started
        )
        stop_watchdog.set()

    root.after(100, pulse_ui)
    root.after(100, poll_result)
    threading.Thread(target=watchdog, name="startup-ui-watchdog", daemon=True).start()
    threading.Thread(target=startup_worker, name="startup-database", daemon=True).start()
    root.mainloop()
    stop_watchdog.set()
    return 0


def main() -> int:
    logger = configure_logging()
    try:
        with InstanceLock():
            try:
                root = tk.Tk()
            except tk.TclError as exc:
                logger.error("Application startup failed: %s", exc)
                return 1
            return _run_ui_startup(root, logger)
    except AlreadyRunning as exc:
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showwarning("UA FREE Content Tool", str(exc), parent=root)
            root.destroy()
        except tk.TclError:
            pass
        return 2
    except PortableMigrationError as exc:
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("UA FREE Content Tool", str(exc), parent=root)
            root.destroy()
        except tk.TclError:
            pass
        return 1
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
