from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"RC50 patch anchor missing: {label}")
    return text.replace(old, new, 1)


# 1. Align the real Tk AI tab with the stable V2 AI service API.
path = Path("content_agent/v2/ui/window.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from ..ai.service import backend_status, test_active_backend",
    "from ..ai.service import backend_status_text, test_active_backend",
    "AI service import",
)
text = text.replace(
    "self.v2_ai_status_var.set(backend_status(self.v2_backend_settings.active_backend))",
    "self.v2_ai_status_var.set(backend_status_text(self.v2_backend_settings.active_backend))",
)
text = text.replace("return backend.test_connection()", "return backend.probe()")
text = text.replace(
    "lambda: test_active_backend(BACKEND_AGENT, timeout_seconds=45)",
    "lambda: test_active_backend(BACKEND_AGENT, timeout_seconds=45)",
)
text = text.replace(
    "self.v2_ai_status_var.set(backend_status(settings.active_backend))",
    "self.v2_ai_status_var.set(backend_status_text(settings.active_backend))",
)
text = text.replace(
    "self.v2_openrouter_status_var.set(backend_status(BACKEND_OPENROUTER, openrouter_key=self.v2_openrouter_key_var.get()))",
    "self.v2_openrouter_status_var.set(backend_status_text(BACKEND_OPENROUTER, openrouter_key=self.v2_openrouter_key_var.get()))",
)
text = replace_once(
    text,
    "summary = usage_summary(settings.openrouter_monthly_budget_usd)\n        self.v2_usage_var.set(\n            f\"Сьогодні: {summary['today_requests']} запитів · ${summary['today_cost']:.4f} · \"\n            f\"місяць: {summary['month_requests']} запитів · ${summary['month_cost']:.4f} / ${summary['budget']:.2f} · \"\n            f\"залишок: ${summary['remaining']:.2f}\"\n        )",
    "summary = usage_summary(backend=\"openrouter\")\n        budget = max(0.0, float(settings.openrouter_monthly_budget_usd or 0.0))\n        remaining = max(0.0, budget - float(summary['month_cost']))\n        self.v2_usage_var.set(\n            f\"Сьогодні: {summary['today_requests']} запитів · ${summary['today_cost']:.4f} · \"\n            f\"місяць: {summary['month_requests']} запитів · ${summary['month_cost']:.4f} / ${budget:.2f} · \"\n            f\"залишок: ${remaining:.2f}\"\n        )",
    "OpenRouter usage summary",
)
text = text.replace('self.notebook.add(tab, text="Supervisor")', 'self.notebook.add(tab, text="Стан системи")')
path.write_text(text, encoding="utf-8")


# 2. Wire the RC50 controller boundaries into the real active window, without another MainWindow layer.
path = Path("content_agent/v2/ui/manual_topics_window_rc44.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from .manual_topics_window import ALL_SOURCES, ALL_TOPICS, MainWindow as Rc43MainWindow",
    "from .data_tab import DataTabController\nfrom .inbox_controller import InboxTabController\nfrom .platforms_tab import PlatformsTabController\nfrom .manual_topics_window import ALL_SOURCES, ALL_TOPICS, MainWindow as Rc43MainWindow",
    "controller imports",
)
text = replace_once(
    text,
    "        self._install_rc48_keyboard_shortcuts()\n",
    "        self._install_rc48_keyboard_shortcuts()\n\n        # RC50: behavior moves into controllers/components, not another versioned window.\n        self.inbox_controller = InboxTabController(self)\n        self.data_tab_controller = DataTabController(self)\n        self.data_tab_controller.build()\n        self.platforms_tab_controller = PlatformsTabController(self, self.services.destinations)\n        self.platforms_tab_controller.build()\n",
    "controller initialization",
)

# Restore uses MaintenanceService schema dispatch, including password-protected migration backups.
old = '''    def import_backup_ui(self) -> None:\n        \"\"\"Restore through the same reliable database composition as startup.\"\"\"\n        selected = self.files.askopenfilename(\n            parent=self.root,\n            title=\"Оберіть backup\",\n            filetypes=[(\"UA FREE backup\", \"*.zip\")],\n        )\n        if not selected:\n            return\n        if not self.msg.askyesno(\n            \"Імпорт\",\n            \"Поточні дані спочатку буде збережено в safety backup. Продовжити?\",\n            parent=self.root,\n        ):\n            return\n\n        def success(result: object) -> None:\n            try:\n                self.config = load_config()\n            except ConfigError:\n                self.config = AppConfig()\n            self.publisher_factory.config = self.config\n            self.db = create_database()\n            self.services = build_services(config=self.config, database=self.db)\n            self.worker.database = self.db\n            self.refresh_sources()\n            self.refresh_groups()\n            self.refresh_queue()\n            self.refresh_history()\n            self._update_target_availability()\n            self.ui_language_var.set(language_label(self.config.ui_language))\n            self._apply_language()\n            self.refresh_learning_stats()\n            self.msg.showinfo(\n                \"Імпорт\",\n                f\"Імпорт завершено. Safety backup: {getattr(result, 'safety_backup', '')}\",\n                parent=self.root,\n            )\n\n        self.run_async(\n            lambda: import_backup(Path(selected)),\n            success,\n            label=\"Імпортую резервну копію\",\n            done_label=\"Імпорт завершено\",\n        )\n'''
new = '''    def create_migration_backup_ui(self) -> None:\n        password = self.data_tab_controller.choose_password(confirm=True)\n        if not password:\n            return\n        selected = self.files.askdirectory(parent=self.root, title=\"Куди зберегти migration backup\")\n        destination = Path(selected) if selected else None\n\n        def success(result: object) -> None:\n            self.data_tab_controller.status_var.set(f\"Migration backup створено: {result}\")\n            self.set_status(\"Migration backup створено.\")\n\n        self.run_async(\n            lambda: self.services.maintenance.create_migration_backup(password, destination),\n            success,\n            label=\"Створюю захищений migration backup\",\n            done_label=\"Migration backup створено\",\n        )\n\n    def import_backup_ui(self) -> None:\n        \"\"\"Stage and validate restore through the RC50 maintenance boundary.\"\"\"\n        selected = self.files.askopenfilename(\n            parent=self.root, title=\"Оберіть backup\", filetypes=[(\"UA FREE backup\", \"*.zip\")]\n        )\n        if not selected:\n            return\n        archive = Path(selected)\n        password = None\n        try:\n            if self.services.maintenance.backup_requires_password(archive):\n                password = self.data_tab_controller.choose_password(confirm=False)\n                if not password:\n                    return\n        except Exception as exc:\n            self._show_error(exc)\n            return\n        if not self.msg.askyesno(\n            \"Імпорт\",\n            \"Поточні дані буде збережено у safety backup. Після успішного restore програму треба перезапустити. Продовжити?\",\n            parent=self.root,\n        ):\n            return\n\n        def success(result: object) -> None:\n            self.msg.showinfo(\n                \"Імпорт завершено\",\n                f\"Backup перевірено й відновлено. Safety backup: {getattr(result, 'safety_backup', '')}\\n\\nЗакрийте й запустіть Content Tool знову.\",\n                parent=self.root,\n            )\n            self.set_status(\"Restore завершено. Потрібен перезапуск програми.\")\n\n        self.run_async(\n            lambda: self.services.maintenance.import_backup(archive, credential_password=password),\n            success, label=\"Перевіряю й відновлюю backup\", done_label=\"Restore завершено\",\n        )\n'''
text = replace_once(text, old, new, "RC50 restore UI")
path.write_text(text, encoding="utf-8")


# 3. Make Windows Tk DPI-aware before creating the first root window.
path = Path("content_agent/main.py")
text = path.read_text(encoding="utf-8")
anchor = '''def _show_startup_error(root: tk.Tk, message: str) -> None:\n'''
helper = '''def _enable_windows_dpi_awareness(logger: object | None = None) -> None:\n    if os.name != \"nt\":\n        return\n    try:\n        import ctypes\n        try:\n            ctypes.windll.shcore.SetProcessDpiAwareness(2)\n        except Exception:\n            ctypes.windll.user32.SetProcessDPIAware()\n    except Exception as exc:\n        if logger is not None:\n            try:\n                logger.warning(\"Could not enable Windows DPI awareness: %s\", exc)\n            except Exception:\n                pass\n\n\n'''
if "def _enable_windows_dpi_awareness" not in text:
    text = replace_once(text, anchor, helper + anchor, "DPI helper")
text = replace_once(
    text,
    "    _raise_windows_stdio_limit(logger)\n    try:\n",
    "    _raise_windows_stdio_limit(logger)\n    _enable_windows_dpi_awareness(logger)\n    try:\n",
    "DPI startup call",
)
path.write_text(text, encoding="utf-8")


# 4. Remove the active V2 runtime monkey-patch module after service.py stopped depending on it.
legacy = Path("content_agent/v2/ai/direct_router_runtime.py")
if legacy.exists():
    legacy.unlink()

print("RC50 checkpoint 2 patch applied")
