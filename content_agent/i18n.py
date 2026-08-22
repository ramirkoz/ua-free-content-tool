from __future__ import annotations

import re
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Iterable

from .i18n_extra import EXTRA_EN, EXTRA_PATTERNS

SUPPORTED_LANGUAGES = ("uk", "en")
LANGUAGE_LABELS = {"uk": "Українська", "en": "English"}

# The source UI remains Ukrainian. English mode translates the original labels at
# runtime, which keeps widget construction deterministic and lets older plugins
# continue to address the same controls.
_EN: dict[str, str] = {
    "Джерела": "Sources",
    "Вхідні": "Inbox",
    "Редактор": "Editor",
    "Публікація": "Publication",
    "Черга": "Queue",
    "Налаштування": "Settings",
    "Тип": "Type",
    "Назва": "Name",
    "URL або @telegram_channel": "URL or @telegram_channel",
    "Додати": "Add",
    "Оновити список": "Refresh list",
    "Оновити": "Refresh",
    "Видалити": "Delete",
    "Зібрати вибране": "Collect selected",
    "Зібрати всі джерела": "Collect all sources",
    "Показати": "Show",
    "Активні": "Active",
    "Нові": "New",
    "Схвалені": "Approved",
    "Відхилені": "Rejected",
    "Архів": "Archive",
    "Відновити / прийняти": "Open",
    "Запам’ятати й виключати": "Remember and never suggest again",
    "Запам’ятати й більше не пропонувати": "Remember and never suggest again",
    "Знайти все по темі": "Find similar topic materials",
    "Пошук схожих за темою матеріалів": "Find similar topic materials",
    "Об’єднати в один блок": "Merge into one block",
    "Об’єднати вибрані": "Merge selected",
    "Вибрати всі": "Select all",
    "Зняти вибір": "Clear selection",
    "Відкрити матеріал": "Open item",
    "Скасувати": "Cancel",
    "Блок": "Block",
    "Статус": "Status",
    "Подія": "Event",
    "Джерел": "Sources",
    "Остання згадка": "Latest mention",
    "Вибуховість": "Virality",
    "нова": "new",
    "схвалено": "approved",
    "відхилено": "rejected",
    "архів": "archive",
    "Блок не вибрано": "No block selected",
    "Зберегти": "Save",
    "Оновити блок": "Refresh block",
    "Оцінити вибуховість": "Evaluate virality",
    "Оцінити потенціал": "Evaluate potential",
    "Рерайт через Ollama": "Rewrite with Ollama",
    "Тексти всіх джерел": "All source texts",
    "Відкрити новину": "Open article",
    "№": "No.",
    "Джерело": "Source",
    "Заголовок": "Headline",
    "Час": "Time",
    "Факт-картка і суперечності між джерелами": "Fact card and source conflicts",
    "Текст публікації: один для всіх мереж": "Publication text: one version for all networks",
    "Куди публікувати:": "Publish to:",
    "Не вибрано": "Not selected",
    "Налаштувати платформи й медіа": "Configure platforms and media",
    "СХВАЛИТИ Й ПОСТАВИТИ В ЧЕРГУ": "APPROVE AND ADD TO QUEUE",
    "Медіа з Google Drive": "Media from Google Drive",
    "Перевірити медіа": "Check media",
    "Відкрити файл": "Open file",
    "Прибрати": "Remove",
    "Оберіть платформи:": "Select platforms:",
    "Усі доступні": "All available",
    "Очистити": "Clear",
    "Додати посилання на джерело": "Add source link",
    "Доступні сторінки й профілі": "Available pages and profiles",
    "Відкрити й редагувати": "Open and edit",
    "Повторити невідправлені": "Retry unsent",
    "Перепланувати пропущені / призупинені": "Reschedule missed / paused",
    "Скасувати / прибрати": "Cancel / remove",
    "Запустити один пакет зараз": "Run one package now",
    "Пакет": "Batch",
    "Новина": "Story",
    "Спроби": "Attempts",
    "Платформи": "Platforms",
    "Очищення Drive": "Drive cleanup",
    "Призупинені": "Paused",
    "Усі": "All",
    "Завершені": "Completed",
    "Скасовані": "Cancelled",
    "очікує": "pending",
    "публікується": "publishing",
    "призупинено": "paused",
    "завершено": "completed",
    "скасовано": "cancelled",
    "опубліковано": "published",
    "помилка": "error",
    "Розмір шрифту:": "Font size:",
    "ЗБЕРЕГТИ ЗМІНИ": "SAVE CHANGES",
    "Усі зміни збережено": "All changes saved",
    "Є незбережені зміни": "There are unsaved changes",
    "1. Ollama і моделі": "1. Ollama and models",
    "Знайти моделі": "Find models",
    "Основна модель": "Primary model",
    "Запасна модель": "Fallback model",
    "Без запасної моделі": "No fallback model",
    "2. Платформи й Google Drive": "2. Platforms and Google Drive",
    "Автоматична діагностика токенів і прав": "Automatic token and permission diagnostics",
    "Перевірити всі підключення зараз": "Check all connections now",
    "Платформа": "Platform",
    "Стан": "State",
    "Що перевірено / що зробити": "What was checked / what to do",
    "Facebook застосунок": "Facebook application",
    "Threads застосунок": "Threads application",
    "Відкрити налаштування застосунку": "Open application settings",
    "Facebook Pages": "Facebook Pages",
    "Facebook User Access Token": "Facebook User Access Token",
    "Відкрити Graph API Explorer": "Open Graph API Explorer",
    "Знайти сторінки": "Find pages",
    "Сторінка": "Page",
    "Визначити профіль": "Identify profile",
    "Перевірити пошук трендів": "Check trend search",
    "Перевірити токен": "Check token",
    "Перевірити": "Check",
    "Канал, наприклад @uafree_org": "Channel, for example @uafree_org",
    "Google Drive — тимчасове медіа": "Google Drive — temporary media",
    "OAuth Client ID типу Desktop app": "OAuth Client ID of Desktop app type",
    "Підключити Drive": "Connect Drive",
    "3. Розклад і резервні копії": "3. Schedule and backups",
    "Створити backup": "Create backup",
    "Імпортувати backup": "Import backup",
    "Мова програми": "Application language",
    "Локальне навчання": "Local learning",
    "Використовувати навчальні приклади в промптах Ollama": "Use learning examples in Ollama prompts",
    "Кількість прикладів у промпті": "Examples per prompt",
    "Оновити статистику": "Refresh statistics",
    "Експортувати навчальні дані": "Export learning data",
    "Імпортувати навчальні дані": "Import learning data",
    "Очистити навчальну історію": "Clear learning history",
    "Готово": "Ready",
    "Помилка": "Error",
    "Медіа не додано": "No media added",
    "Вибуховість не розрахована": "Virality has not been calculated",
    "Редакційна пам’ять: 0 схвалених прикладів": "Editorial memory: 0 approved examples",
    "Натисніть «Знайти моделі».": "Click “Find models”.",
    "не налаштовано": "not configured",
    "актуальний": "current",
    "замінити токен": "replace token",
    "перевірити права": "check permissions",
    "тимчасово не перевірено": "temporarily unchecked",
}
_EN.update(EXTRA_EN)

_EN_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^Знайдено моделей: (\d+)$"), r"Models found: \1"),
    (re.compile(r"^Підключено сторінок: (\d+)(.*)$"), r"Connected pages: \1\2"),
    (re.compile(r"^Редакційна пам’ять: (\d+) схвалених прикладів$"), r"Editorial memory: \1 approved examples"),
    (re.compile(r"^Схожих матеріалів для об’єднання не знайдено\.$"), "No similar materials were found for merging."),
    (re.compile(r"^Кандидатів на об’єднання: (\d+)$"), r"Merge candidates: \1"),
    (re.compile(r"^Поточна операція: немає$"), "Current operation: none"),
    (re.compile(r"^Поточна операція: (.+)$"), r"Current operation: \1"),
    (re.compile(r"^(\d+) / (\d+) символів(.*)$"), r"\1 / \2 characters\3"),
) + EXTRA_PATTERNS


def normalize_language(value: str | None) -> str:
    language = str(value or "uk").strip().lower()
    return language if language in SUPPORTED_LANGUAGES else "uk"


def language_label(language: str) -> str:
    return LANGUAGE_LABELS[normalize_language(language)]


def language_from_label(label: str) -> str:
    value = str(label or "").strip()
    for code, name in LANGUAGE_LABELS.items():
        if value == name:
            return code
    return normalize_language(value)


def tr(text: str, language: str) -> str:
    value = str(text or "")
    if normalize_language(language) == "uk" or not value:
        return value
    leading = value[: len(value) - len(value.lstrip())]
    trailing = value[len(value.rstrip()) :]
    core = value.strip()
    translated = _EN.get(core)
    if translated is None:
        for pattern, replacement in _EN_PATTERNS:
            if pattern.match(core):
                translated = pattern.sub(replacement, core)
                break
    return leading + (translated if translated is not None else core) + trailing


def original_text(value: str) -> str:
    current = str(value or "")
    reverse = {english: ukrainian for ukrainian, english in _EN.items()}
    return reverse.get(current, current)


class LocalizedMessageBox:
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
    return "English" if normalize_language(language) == "en" else "українська"


def output_language_instruction(language: str) -> str:
    if normalize_language(language) == "en":
        return (
            "OUTPUT LANGUAGE: ENGLISH ONLY. Translate every source-language fragment, "
            "including quotations and captions, into natural English. Do not leave "
            "Ukrainian or Russian prose in the publication text."
        )
    return (
        "ВИХІДНА МОВА: ВИКЛЮЧНО УКРАЇНСЬКА. Навіть якщо джерела іншою мовою, "
        "переклади українською весь текст, включно з цитатами й підписами."
    )


def prompt_labels(language: str) -> dict[str, str]:
    if normalize_language(language) == "en":
        return {
            "headline": "HEADLINE",
            "facts": "FACTS",
            "text": "TEXT",
            "source_title": "SOURCE HEADLINE",
            "materials": "ALL SOURCE MATERIALS",
        }
    return {
        "headline": "ЗАГОЛОВОК",
        "facts": "ФАКТИ",
        "text": "ТЕКСТ",
        "source_title": "ПОЧАТКОВИЙ ЗАГОЛОВОК",
        "materials": "МАТЕРІАЛИ ВСІХ ДЖЕРЕЛ",
    }


def _localize_notebook(widget: ttk.Notebook, language: str) -> None:
    bases = getattr(widget, "_i18n_tab_bases", None)
    tabs = widget.tabs()
    if bases is None:
        bases = {tab: widget.tab(tab, "text") for tab in tabs}
        setattr(widget, "_i18n_tab_bases", bases)
    for tab in tabs:
        base = bases.get(tab, widget.tab(tab, "text"))
        widget.tab(tab, text=tr(base, language))


def _localize_tree(widget: ttk.Treeview, language: str) -> None:
    bases = getattr(widget, "_i18n_heading_bases", None)
    columns: Iterable[str] = widget.cget("columns")
    if bases is None:
        bases = {str(column): widget.heading(column, "text") for column in columns}
        setattr(widget, "_i18n_heading_bases", bases)
    for column, base in bases.items():
        widget.heading(column, text=tr(base, language))


def localize_widget_tree(root: tk.Misc, language: str) -> None:
    """Translate visible static widget text without rebuilding the Tk hierarchy."""

    language = normalize_language(language)
    stack: list[tk.Misc] = [root]
    while stack:
        widget = stack.pop()
        try:
            stack.extend(widget.winfo_children())
        except tk.TclError:
            pass
        if isinstance(widget, ttk.Notebook):
            _localize_notebook(widget, language)
        if isinstance(widget, ttk.Treeview):
            _localize_tree(widget, language)
        try:
            current = str(widget.cget("text"))
        except (tk.TclError, TypeError):
            continue
        base = getattr(widget, "_i18n_base_text", None)
        if base is None:
            base = original_text(current)
            setattr(widget, "_i18n_base_text", base)
        try:
            widget.configure(text=tr(base, language))
        except tk.TclError:
            pass
