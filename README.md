# UA FREE Content Tool v2.0.0-rc28

Windows Portable інструмент для збору, редактури, підготовки й публікації контенту з AI Router, Supervisor та інтеграціями соцмереж.

## Архітектура

- `content_agent/v2` — активний V2 runtime і канонічне V2-вікно.
- `Data` — лише користувацькі дані: база, налаштування, журнали, кеш, backup/recovery state.
- `Tools` — відтворювані важкі runtime-компоненти, зокрема Codex. Вони не повинні роздувати Data.
- V2 більше не використовує ланцюг `window_rc7 -> rc8 -> rc11`; актуальні V2-функції зведені в канонічні модулі.
- Старий UI-контур використовується тільки як compatibility boundary для функцій, які ще не перенесені в V2, і прихований під час побудови вікна, тому старі RC-версії не повинні мигати користувачу.

## Перший запуск / міграція

Не копіюйте стару `Data` в нову папку. На першому запуску можна вибрати стару папку Content Tool або її `Data`. Read-only importer переносить тільки довготривалі джерела, групи, матеріали, publication state, editorial examples, feedback/learning та налаштування. Старі logs/cache/backups/diagnostics/Tools не переносяться.

## Секрети та соцмережі

API/access/page tokens зберігаються як службові secrets. Інтерфейс не пропонує копіювати Facebook Page token або інші секрети в clipboard. Facebook Pages обираються як сторінки для публікації, а їхні page tokens залишаються внутрішніми даними інтеграції.

## Portable layout

```text
UA_FREE_Content_Tool.exe
_runtime/
Tools/
Data/
VERSION.txt
PUBLIC_VERSION.txt
README.txt
```

Updater зберігає `Data` і `Tools`. Поточний реліз: **v2.0.0-rc28**.
