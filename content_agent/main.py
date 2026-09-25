from __future__ import annotations

import faulthandler
import os
import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

from .config import AppConfig, ConfigError, load_config
from .v2.storage.reliable import Database
from .instance_lock import AlreadyRunning, InstanceLock
from .logging_setup import configure_logging
from .paths import data_dir, portable_mode
from .readable_media_names import install_runtime as install_readable_media_names_runtime
from .clean_import import clean_import_from_old_data, first_run_marker, mark_first_run_choice, target_has_user_data
from .version import APP_VERSION
from .v2.ui.window import MainWindow


def _raise_windows_stdio_limit(logger: object | None = None) -> int:
    """Raise the MSVCRT stdio descriptor ceiling on Windows.

    This is containment, not permission to leak descriptors. RC6 also bounds
    resolver threads and stops a collection cycle on EMFILE. Raising the CRT
    ceiling gives the long-running portable app more headroom for legitimate
    simultaneous SQLite/log/media/network activity while live telemetry makes
    a growing handle count visible.
    """
    if os.name != "nt":
        return -1
    try:
        import ctypes
        msvcrt = ctypes.CDLL("msvcrt")
        getmax = msvcrt._getmaxstdio
        getmax.restype = ctypes.c_int
        setmax = msvcrt._setmaxstdio
        setmax.argtypes = [ctypes.c_int]
        setmax.restype = ctypes.c_int
        current = int(getmax())
        if current < 8192:
            updated = int(setmax(8192))
            if updated > 0:
                current = updated
        if logger is not None:
            logger.info("Windows CRT stdio limit=%s", current)  # type: ignore[attr-defined]
        return current
    except Exception as exc:
        if logger is not None:
            try:
                logger.warning("Could not raise Windows CRT stdio limit: %s", exc)  # type: ignore[attr-defined]
            except Exception:
                pass
        return -1


def _show_startup_error(root: tk.Tk, message: str) -> None:
    try:
        messagebox.showerror("UA FREE Content Tool", message, parent=root)
    except tk.TclError:
        pass


def _run_ui_startup(root: tk.Tk, logger: object) -> int:
    root.title(f"UA FREE Content Tool — v{APP_VERSION} · запуск")
    root.geometry("560x150")
    root.minsize(520, 140)

    frame = ttk.Frame(root, padding=18)
    frame.pack(fill="both", expand=True)
    status_var = tk.StringVar(value="Запуск: підготовка…")
    ttk.Label(frame, text=f"UA FREE Content Tool v{APP_VERSION}", font="TkHeadingFont").pack(anchor="w")
    ttk.Label(frame, textvariable=status_var, wraplength=500).pack(anchor="w", pady=(10, 8))
    progress = ttk.Progressbar(frame, mode="indeterminate")
    progress.pack(fill="x")
    progress.start(12)

    result_queue: queue.Queue[tuple[str, object]] = queue.Queue()
    progress_queue: queue.Queue[str] = queue.Queue()

    selected_import_path = ""
    if not first_run_marker().exists() and not target_has_user_data():
        wants_import = messagebox.askyesno(
            "UA FREE Content Tool · перший запуск",
            "Імпортувати потрібні дані зі старої версії?\n\n"
            "Перенесемо джерела, групи, матеріали, чергу публікацій, редакційну пам’ять, "
            "налаштування соцмереж та AI Router/OpenRouter credentials. "
            "Логи, кеш, cooldown/state, supervisor/recovery, старі backups, Codex/runtime і Tools не копіюються.",
            parent=root,
        )
        if wants_import:
            selected_import_path = filedialog.askdirectory(
                title="Оберіть стару папку Content Tool або її Data",
                parent=root,
                mustexist=True,
            ) or ""
            if not selected_import_path:
                mark_first_run_choice("cancelled")
        else:
            mark_first_run_choice("fresh")
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
            set_stage("database_init")
            database_started = time.monotonic()
            database = Database()
            logger.info("STARTUP stage=database_init end duration=%.3fs", time.monotonic() - database_started)

            migration = None
            if selected_import_path:
                set_stage("clean_import")
                migration_started = time.monotonic()
                migration = clean_import_from_old_data(selected_import_path)
                mark_first_run_choice("imported", selected_import_path)
                logger.info(
                    "STARTUP stage=clean_import end duration=%.3fs source=%s tables=%s",
                    time.monotonic() - migration_started,
                    migration.source,
                    migration.tables,
                )

            set_stage("config")
            config_started = time.monotonic()
            try:
                config = load_config()
            except ConfigError as exc:
                logger.error("Configuration could not be opened: %s", exc)
                if portable_mode():
                    raise
                config = AppConfig()
            logger.info("STARTUP stage=config end duration=%.3fs", time.monotonic() - config_started)

            set_stage("database_quick_check")
            check_started = time.monotonic()
            database.quick_check()
            logger.info("STARTUP stage=database_quick_check end duration=%.3fs", time.monotonic() - check_started)
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
            logger.error("Application startup failed: %s", error)
            status_var.set("Запуск не завершено.")
            _show_startup_error(root, str(error))
            root.destroy()
            return

        database, config, migration = payload
        if migration is not None:
            logger.info(
                "Clean portable data import completed from %s; config=%s files=%s warnings=%s.",
                migration.source, migration.config_imported, migration.imported_files, migration.warnings,
            )
            table_rows = sum(int(value or 0) for value in migration.tables.values())
            summary = (
                "Чистий імпорт завершено.\n\n"
                f"Записів у робочих таблицях: {table_rows}\n"
                f"Основні налаштування: {'перенесено' if migration.config_imported else 'не знайдено'}\n"
                f"Додаткові налаштування/credentials: {len(migration.imported_files)} файлів\n"
                "Codex runtime: не переносився; за потреби встановіть його у вкладці AI.\n"
                "Стара Data не змінювалась."
            )
            if migration.warnings:
                summary += "\n\nПопередження:\n- " + "\n- ".join(migration.warnings[:6])
            messagebox.showinfo("UA FREE Content Tool · імпорт", summary, parent=root)
        progress.stop()
        frame.destroy()
        with pulse_lock:
            pulse["stage"] = "build_main_window"
        build_started = time.monotonic()
        try:
            root.withdraw()
            MainWindow(root, database, config)
            root.title(f"UA FREE Content Tool — v{APP_VERSION}")
            root.deiconify()
        except Exception as exc:
            stop_watchdog.set()
            logger.error("Application UI startup failed: %s", exc)
            _show_startup_error(root, str(exc))
            root.destroy()
            return
        logger.info("STARTUP stage=build_main_window end duration=%.3fs", time.monotonic() - build_started)
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
    install_readable_media_names_runtime()
    _raise_windows_stdio_limit(logger)
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
