from __future__ import annotations

import faulthandler
import os
import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

from .app.container import build_services
from .clean_import import clean_import_from_old_data, first_run_marker, mark_first_run_choice, target_has_user_data
from .config import AppConfig, ConfigError, load_config
from .instance_lock import AlreadyRunning, InstanceLock
from .logging_setup import configure_logging
from .paths import data_dir, portable_mode
from .readable_media_names import install_runtime as install_readable_media_names_runtime
from .v2.storage.factory import create_database
from .v2.ui.active_window import MainWindow
from .version import APP_VERSION


_STARTUP_STAGE_LABELS = {
    "database_init": "перевіряю базу даних",
    "clean_import": "імпортую дані зі старої версії",
    "config": "завантажую налаштування",
    "compose_services": "підключаю служби програми",
    "database_quick_check": "перевіряю цілісність даних",
    "build_main_window": "відкриваю робоче вікно",
}


def _raise_windows_stdio_limit(logger: object | None = None) -> int:
    """Raise the MSVCRT stdio descriptor ceiling on Windows."""
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


def _choose_first_run_action(root: tk.Tk) -> str:
    """Return import/fresh/later using explicit operator-facing choices."""
    choice = {"value": "later"}
    dialog = tk.Toplevel(root)
    dialog.title("UA FREE Content Tool · перший запуск")
    dialog.transient(root)
    dialog.resizable(False, False)
    dialog.grab_set()

    body = ttk.Frame(dialog, padding=18)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text="Що зробити з даними попередньої версії?", font="TkHeadingFont").pack(anchor="w")
    ttk.Label(
        body,
        text=(
            "Імпорт переносить робочі дані й налаштування зі старої папки Content Tool.\n"
            "«Почати з чистого» створює нову Data. «Вирішити пізніше» нічого не змінює\n"
            "і покаже цей вибір знову під час наступного запуску."
        ),
        justify="left",
        wraplength=560,
    ).pack(anchor="w", pady=(10, 16))

    buttons = ttk.Frame(body)
    buttons.pack(fill="x")

    def finish(value: str) -> None:
        choice["value"] = value
        try:
            dialog.grab_release()
        except tk.TclError:
            pass
        dialog.destroy()

    ttk.Button(buttons, text="Імпортувати", command=lambda: finish("import")).pack(side="left")
    ttk.Button(buttons, text="Почати з чистого", command=lambda: finish("fresh")).pack(side="left", padx=8)
    ttk.Button(buttons, text="Вирішити пізніше", command=lambda: finish("later")).pack(side="right")
    dialog.protocol("WM_DELETE_WINDOW", lambda: finish("later"))

    dialog.update_idletasks()
    try:
        x = root.winfo_rootx() + max(0, (root.winfo_width() - dialog.winfo_reqwidth()) // 2)
        y = root.winfo_rooty() + max(0, (root.winfo_height() - dialog.winfo_reqheight()) // 2)
        dialog.geometry(f"+{x}+{y}")
    except tk.TclError:
        pass
    root.wait_window(dialog)
    return str(choice["value"])


def _run_ui_startup(root: tk.Tk, logger: object) -> int:
    root.title(f"UA FREE Content Tool — v{APP_VERSION} · запуск")
    root.geometry("620x180")
    root.minsize(560, 160)

    frame = ttk.Frame(root, padding=18)
    frame.pack(fill="both", expand=True)
    status_var = tk.StringVar(value="Запуск: підготовка…")
    ttk.Label(frame, text=f"UA FREE Content Tool v{APP_VERSION}", font="TkHeadingFont").pack(anchor="w")
    ttk.Label(frame, textvariable=status_var, wraplength=560).pack(anchor="w", pady=(10, 8))
    progress = ttk.Progressbar(frame, mode="indeterminate")
    progress.pack(fill="x")
    progress.start(12)

    result_queue: queue.Queue[tuple[str, object]] = queue.Queue()
    progress_queue: queue.Queue[str] = queue.Queue()

    selected_import_path = ""
    if not first_run_marker().exists() and not target_has_user_data():
        action = _choose_first_run_action(root)
        if action == "import":
            selected_import_path = filedialog.askdirectory(
                title="Оберіть стару папку Content Tool, UA_FREE_Content_Tool або Data",
                parent=root,
                mustexist=True,
            ) or ""
            if not selected_import_path:
                status_var.set("Імпорт не вибрано. Під час наступного запуску запитаємо знову.")
        elif action == "fresh":
            mark_first_run_choice("fresh")
        else:
            status_var.set("Дані не змінюємо. Під час наступного запуску запитаємо знову.")

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
            database = create_database()
            logger.info("STARTUP stage=database_init end duration=%.3fs", time.monotonic() - database_started)

            migration = None
            if selected_import_path:
                set_stage("clean_import")
                migration_started = time.monotonic()
                migration = clean_import_from_old_data(selected_import_path)
                try:
                    database = create_database()
                    with database.connect() as db:
                        fk_rows = db.execute("PRAGMA foreign_key_check").fetchall()
                    if fk_rows:
                        raise RuntimeError(
                            f"Імпортована база не пройшла foreign_key_check: {len(fk_rows)} помилок."
                        )
                except Exception:
                    logger.exception("Clean import post-migration validation failed")
                    raise
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

            set_stage("compose_services")
            services = build_services(config=config, database=database)

            set_stage("database_quick_check")
            check_started = time.monotonic()
            services.db.quick_check()
            logger.info("STARTUP stage=database_quick_check end duration=%.3fs", time.monotonic() - check_started)
            result_queue.put(("ok", (services, migration)))
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
            status_var.set("Запуск: " + _STARTUP_STAGE_LABELS.get(latest_stage, latest_stage.replace("_", " ")) + "…")
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

        services, migration = payload
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
            window = MainWindow(root, services)
            # RC49 readiness contract: the inner V2 constructor may create the
            # Supervisor object, but SupervisorRuntime.start() is required to defer
            # all DB/Drive/AI work until the *outermost* Source/Topic shell has also
            # finished.  This prevents startup quick_check from blocking Tk on the
            # global database maintenance lock.
            window._ui_ready = True
            root.title(f"UA FREE Content Tool — v{APP_VERSION}")
            root.deiconify()
            supervisor = getattr(window, "v2_supervisor", None)
            if supervisor is not None:
                root.after_idle(supervisor.start)
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
