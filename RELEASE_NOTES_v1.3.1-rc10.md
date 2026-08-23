# UA FREE Content Tool v1.3.1-rc10

RC10 is a narrow UI stabilization update built on RC9.

## Fixed

- Inbox columns no longer behave like elastic bands when the window is resized. Every Inbox column now uses the exact user-selected width (`stretch=False`).
- Added a horizontal scrollbar for the Inbox table. Narrow windows scroll horizontally instead of silently squeezing or redistributing columns.
- RC10 starts with a new sane Inbox layout file, so corrupted/over-compressed RC8/RC9 saved widths are not reused.
- Column-width changes are still persisted after manual resizing.
- Added Excel-style multi-column sorting in Inbox:
  - click a heading: single-column sort; repeated click toggles direction;
  - Shift+click another heading: add it as the next sort priority;
  - Ctrl+click a heading: remove it from the active multi-sort;
  - headings show priority and direction, e.g. `Тема 1▲`, `Подія 2▲`.
- Preserved the RC9 fix for the RC8 `bad window path name ...checkbuttonN` crash.

## Example

To sort first by topic and then by title:

1. Click `Тема`.
2. Hold Shift and click `Подія`.

## Data compatibility

No database schema change. Existing `Data` can be copied unchanged. RC10 intentionally uses a new Inbox layout JSON file so only the broken/squeezed column geometry is reset.
