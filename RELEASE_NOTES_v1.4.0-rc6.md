# UA FREE Content Tool v1.4.0-rc6

RC6 fixes two regressions in the maximized duplicate-review workflow.

## Duplicate-review footer

- The duplicate dialog now uses a fixed three-row grid layout: header, expandable table, fixed action footer.
- Maximizing the dialog can no longer let the Treeview consume the footer area and push `Вибрати всі`, `Зняти всі`, `Об'єднати вибрані матеріали`, or `Закрити` below the usable desktop.
- Existing manual column widths, horizontal scrolling, and persisted layout remain unchanged.

## Confidence colours vs automatic selection

- Visual confidence and automatic selection are separate again.
- 80–89% candidates are shown as strong/green, matching the earlier UI meaning, but are not selected automatically.
- 90–100% candidates are strong/green and are selected automatically.
- Below 80% remains the caution/yellow class.

No database schema or publication model change is included in RC6.
