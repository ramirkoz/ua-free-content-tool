from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8", newline="\n")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one occurrence, found {count}: {old[:120]!r}")
    write(path, text.replace(old, new, 1))


# ---------------------------------------------------------------------------
# Shared localization infrastructure for widgets, dialogs and file pickers.
# ---------------------------------------------------------------------------
replace_once(
    "content_agent/i18n.py",
    "from tkinter import ttk\nfrom typing import Iterable\n",
    "from tkinter import filedialog, messagebox, ttk\nfrom typing import Callable, Iterable\n\n"
    "from .i18n_extra import EXTRA_EN, EXTRA_PATTERNS\n",
)
replace_once(
    "content_agent/i18n.py",
    "}\n\n_EN_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (\n",
    "}\n_EN.update(EXTRA_EN)\n\n_EN_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (\n",
)
replace_once(
    "content_agent/i18n.py",
    ")\n\n\ndef normalize_language(value: str | None) -> str:\n",
    ") + EXTRA_PATTERNS\n\n\ndef normalize_language(value: str | None) -> str:\n",
)
replace_once(
    "content_agent/i18n.py",
    "def output_language_name(language: str) -> str:\n",
    '''class LocalizedMessageBox:
    """Translate dialog titles and messages at the moment they are shown."""

    def __init__(self, language_getter: Callable[[], str]):
        self._language_getter = language_getter

    def __getattr__(self, name: str):
        target = getattr(messagebox, name)

        def invoke(*args: object, **kwargs: object):
            language = normalize_language(self._language_getter())
            translated = list(args)
            for index in range(min(2, len(translated))):
                if isinstance(translated[index], str):
                    translated[index] = tr(translated[index], language)
            if isinstance(kwargs.get("title"), str):
                kwargs["title"] = tr(str(kwargs["title"]), language)
            if isinstance(kwargs.get("message"), str):
                kwargs["message"] = tr(str(kwargs["message"]), language)
            if isinstance(kwargs.get("detail"), str):
                kwargs["detail"] = tr(str(kwargs["detail"]), language)
            return target(*translated, **kwargs)

        return invoke


class LocalizedFileDialog:
    """Translate native file-dialog titles while preserving every other option."""

    def __init__(self, language_getter: Callable[[], str]):
        self._language_getter = language_getter

    def __getattr__(self, name: str):
        target = getattr(filedialog, name)

        def invoke(*args: object, **kwargs: object):
            if isinstance(kwargs.get("title"), str):
                kwargs["title"] = tr(str(kwargs["title"]), self._language_getter())
            return target(*args, **kwargs)

        return invoke


def output_language_name(language: str) -> str:
''',
)

# ---------------------------------------------------------------------------
# Main window routes all modal/native dialogs and dynamic status text through
# the selected language. Static widgets remain handled by localize_widget_tree.
# ---------------------------------------------------------------------------
replace_once(
    "content_agent/ui/main_window.py",
    "    localize_widget_tree,\n    normalize_language,\n",
    "    LocalizedFileDialog,\n    LocalizedMessageBox,\n    localize_widget_tree,\n    normalize_language,\n",
)
replace_once(
    "content_agent/ui/main_window.py",
    "        self.config = config\n        self._settings_loading = True\n",
    "        self.config = config\n"
    "        self.msg = LocalizedMessageBox(lambda: self.config.ui_language)\n"
    "        self.files = LocalizedFileDialog(lambda: self.config.ui_language)\n"
    "        self._settings_loading = True\n",
)
main_window = read("content_agent/ui/main_window.py")
main_window = main_window.replace("messagebox.", "self.msg.")
main_window = main_window.replace("filedialog.", "self.files.")
write("content_agent/ui/main_window.py", main_window)
replace_once(
    "content_agent/ui/main_window.py",
    "    def set_status(self, text: str) -> None:\n        self.status_var.set(text)\n",
    "    def set_status(self, text: str) -> None:\n        self.status_var.set(self.t(text))\n",
)
replace_once(
    "content_agent/ui/main_window.py",
    '        self.operation_detail_var.set(f"Виконується {minutes:02d}:{seconds:02d}. Не закривайте програму.")\n',
    '        self.operation_detail_var.set(self.t(f"Виконується {minutes:02d}:{seconds:02d}. Не закривайте програму."))\n',
)
replace_once(
    "content_agent/ui/main_window.py",
    "    def _start_operation(self, label: str) -> int | None:\n        if self.operation_running:\n",
    "    def _start_operation(self, label: str) -> int | None:\n"
    "        label = self.t(label)\n"
    "        if self.operation_running:\n",
)
replace_once(
    "content_agent/ui/main_window.py",
    '        self.operation_var.set(f"Поточна операція: {label}")\n        self.operation_detail_var.set("Запущено…")\n',
    '        self.operation_var.set(self.t(f"Поточна операція: {label}"))\n'
    '        self.operation_detail_var.set(self.t("Запущено…"))\n',
)
replace_once(
    "content_agent/ui/main_window.py",
    '        self.operation_var.set("Поточна операція: помилка" if error else "Поточна операція: завершено")\n        self.operation_detail_var.set(detail)\n',
    '        self.operation_var.set(self.t("Поточна операція: помилка" if error else "Поточна операція: завершено"))\n'
    '        self.operation_detail_var.set(self.t(detail))\n',
)
replace_once(
    "content_agent/ui/main_window.py",
    "        localize_widget_tree(self.root, language)\n",
    "        localize_widget_tree(self.root, language)\n"
    "        for variable in (getattr(self, 'status_var', None), getattr(self, 'operation_var', None), getattr(self, 'operation_detail_var', None)):\n"
    "            if variable is not None:\n"
    "                variable.set(tr(original_text(variable.get()), language))\n",
)
replace_once(
    "content_agent/ui/main_window.py",
    "            self.status_var.set(\"Готово. Планувальник публікацій увімкнено.\")\n",
    "            self.set_status(\"Готово. Планувальник публікацій увімкнено.\")\n",
)

# ---------------------------------------------------------------------------
# The one-time queue migration is also bilingual: its window, prompts, warnings
# and result dialogs follow the same setting instead of remaining Ukrainian.
# ---------------------------------------------------------------------------
replace_once(
    "content_agent/queue_migration.py",
    "from .ollama_client import OllamaClient, OllamaError\n",
    "from .i18n import normalize_language, output_language_instruction\n"
    "from .ollama_client import OllamaClient, OllamaError\n",
)
replace_once(
    "content_agent/queue_migration.py",
    "def build_queue_compression_prompt(text: str, limit: int) -> str:\n    return f\"\"\"\n",
    '''def build_queue_compression_prompt(text: str, limit: int, *, language: str = "uk") -> str:
    language = normalize_language(language)
    if language == "en":
        return f"""
{output_language_instruction(language)}
You are shortening an editor-approved news text. Return only the completed text,
without headings, explanations, JSON, or markdown.

STRICT REQUIREMENTS:
- no more than {int(limit)} characters including spaces and line breaks;
- preserve as many verified facts as possible;
- preserve names, positions, dates, numbers, geography, institutions, causes,
  consequences, and the meaning of quotations;
- add no new facts and do not change meaning or tone;
- remove repetition, filler introductions, generic phrases, and decoration;
- do not add a fundraising footer or source link; the application adds them.

APPROVED TEXT:
{text.strip()}
""".strip()
    return f"""
''',
)
replace_once(
    "content_agent/queue_migration.py",
    "    fallback_model: str = \"\",\n) -> tuple[str, str, bool]:\n",
    "    fallback_model: str = \"\",\n    language: str = \"uk\",\n) -> tuple[str, str, bool]:\n",
)
replace_once(
    "content_agent/queue_migration.py",
    "    prompt = build_queue_compression_prompt(text, limit)\n",
    "    language = normalize_language(language)\n    prompt = build_queue_compression_prompt(text, limit, language=language)\n",
)
replace_once(
    "content_agent/queue_migration.py",
    '        raise QueueMigrationError("У налаштуваннях не вибрана основна модель Ollama.")\n',
    '        raise QueueMigrationError(\n'
    '            "No primary Ollama model is selected in Settings."\n'
    '            if normalize_language(language) == "en"\n'
    '            else "У налаштуваннях не вибрана основна модель Ollama."\n'
    '        )\n',
)
replace_once(
    "content_agent/queue_migration.py",
    "def critical_fact_warnings(old_text: str, new_text: str) -> list[str]:\n",
    "def critical_fact_warnings(old_text: str, new_text: str, *, language: str = \"uk\") -> list[str]:\n",
)
replace_once(
    "content_agent/queue_migration.py",
    '        warnings.append("можливо втрачено числа: " + ", ".join(missing_numbers[:8]))\n',
    '        warnings.append(\n'
    '            ("numbers may be missing: " if normalize_language(language) == "en" else "можливо втрачено числа: ")\n'
    '            + ", ".join(missing_numbers[:8])\n'
    '        )\n',
)
replace_once(
    "content_agent/queue_migration.py",
    '        warnings.append("можливо втрачено назви/абревіатури: " + ", ".join(missing_acronyms[:8]))\n',
    '        warnings.append(\n'
    '            ("names/acronyms may be missing: " if normalize_language(language) == "en" else "можливо втрачено назви/абревіатури: ")\n'
    '            + ", ".join(missing_acronyms[:8])\n'
    '        )\n',
)
replace_once(
    "content_agent/ui/queue_migration_dialog.py",
    "from ..database import Database\n",
    "from ..database import Database\n"
    "from ..i18n import LocalizedMessageBox, localize_widget_tree, normalize_language, tr\n",
)
replace_once(
    "content_agent/ui/queue_migration_dialog.py",
    "        self.config = config\n        self.candidates = {item.batch_id: item for item in candidates}\n",
    "        self.config = config\n"
    "        self.language = normalize_language(config.ui_language)\n"
    "        self.msg = LocalizedMessageBox(lambda: self.language)\n"
    "        self.candidates = {item.batch_id: item for item in candidates}\n",
)
replace_once(
    "content_agent/ui/queue_migration_dialog.py",
    "        window = self.window = tk.Toplevel(parent)\n        window.title(\"Разове оновлення завтрашньої черги до 900 символів\")\n",
    "        window = self.window = tk.Toplevel(parent)\n"
    "        window.title(self.t(\"Разове оновлення завтрашньої черги до 900 символів\"))\n",
)
queue_dialog = read("content_agent/ui/queue_migration_dialog.py")
queue_dialog = queue_dialog.replace("messagebox.", "self.msg.")
queue_dialog = queue_dialog.replace('critical_fact_warnings(candidate.old_text, draft)', 'critical_fact_warnings(candidate.old_text, draft, language=self.language)')
queue_dialog = queue_dialog.replace('fallback_model=self.config.ollama_fallback_model,\n                    )', 'fallback_model=self.config.ollama_fallback_model,\n                        language=self.language,\n                    )')
write("content_agent/ui/queue_migration_dialog.py", queue_dialog)
replace_once(
    "content_agent/ui/queue_migration_dialog.py",
    "    @staticmethod\n    def _format_schedule(value: str) -> str:\n",
    "    def t(self, text: str) -> str:\n"
    "        return tr(text, self.language)\n\n"
    "    @staticmethod\n"
    "    def _format_schedule(value: str) -> str:\n",
)
replace_once(
    "content_agent/ui/queue_migration_dialog.py",
    "        if self.order:\n            self.tree.selection_set(str(self.order[0]))\n",
    "        localize_widget_tree(window, self.language)\n"
    "        if self.order:\n"
    "            self.tree.selection_set(str(self.order[0]))\n",
)
replace_once(
    "content_agent/ui/queue_migration_dialog.py",
    '                    "очікує",\n',
    '                    self.t("очікує"),\n',
)
replace_once(
    "content_agent/ui/queue_migration_dialog.py",
    '        self.tree.item(str(batch_id), values=values)\n',
    '        values[5] = self.t(str(values[5]))\n'
    '        self.tree.item(str(batch_id), values=values)\n',
)
replace_once(
    "content_agent/ui/queue_migration_dialog.py",
    '                    lambda i=index, total=len(self.order), bid=batch_id: self.status_var.set(\n                        f"Оброблено {i}/{total}: пакет #{bid}."\n                    ),\n',
    '                    lambda i=index, total=len(self.order), bid=batch_id: self.status_var.set(\n'
    '                        self.t(f"Оброблено {i}/{total}: пакет #{bid}.")\n'
    '                    ),\n',
)

# Audit becomes a real gate rather than a report that succeeds with omissions.
replace_once(
    "tools/audit_v1_1_i18n.py",
    'print("UNTRANSLATED_VISIBLE_LITERALS=" + str(sum(len(items) for items in report.values())))\n',
    'missing_count = sum(len(items) for items in report.values())\n'
    'print("UNTRANSLATED_VISIBLE_LITERALS=" + str(missing_count))\n'
    'raise SystemExit(1 if missing_count else 0)\n',
)

write(
    "tests/test_v1_1_i18n_completion.py",
    '''from __future__ import annotations

from pathlib import Path

from content_agent.i18n import LocalizedFileDialog, LocalizedMessageBox, tr
from content_agent.queue_migration import build_queue_compression_prompt


def test_secondary_ui_catalog_is_complete_for_known_dialogs() -> None:
    assert tr("Діагностика підключень", "en") == "Connection diagnostics"
    assert tr("Переробити всі через Ollama", "en") == "Rewrite all with Ollama"
    assert tr("Об’єднання завершено", "en") == "Merge completed"


def test_dynamic_translation_patterns_cover_operation_and_queue_text() -> None:
    assert tr("Виконується 01:23. Не закривайте програму.", "en") == "Running 01:23. Do not close the application."
    assert tr("Оброблено 2/5: пакет #18.", "en") == "Processed 2/5: batch #18."


def test_queue_compression_prompt_follows_application_language() -> None:
    english = build_queue_compression_prompt("Source text", 900, language="en")
    ukrainian = build_queue_compression_prompt("Текст", 900, language="uk")
    assert "ENGLISH ONLY" in english
    assert "APPROVED TEXT" in english
    assert "повністю українською" in ukrainian


def test_dialog_proxies_are_available_to_both_windows() -> None:
    assert LocalizedMessageBox
    assert LocalizedFileDialog
    main = (Path(__file__).parents[1] / "content_agent" / "ui" / "main_window.py").read_text(encoding="utf-8")
    queue = (Path(__file__).parents[1] / "content_agent" / "ui" / "queue_migration_dialog.py").read_text(encoding="utf-8")
    assert "self.msg = LocalizedMessageBox" in main
    assert "self.files = LocalizedFileDialog" in main
    assert "self.msg = LocalizedMessageBox" in queue
''',
)

Path(__file__).unlink()
print("complete bilingual UI and queue prompt migration applied")
