# UA FREE Content Tool v1.4.0-rc12

RC12 is a production hotfix for the Sources tab regression exposed by the RC9 source editor and visible in RC11.

## Sources tab

- Fixes `Invalid column index health` during startup/refresh.
- The editable RC9 Sources UI now restores the full persistent source-health column set expected by the inherited source diagnostics layer: state, newly inserted items, last new item, error count, last check and URL.
- Automatic source-type detection, editing, Shift/Ctrl multi-selection, Ctrl+A and bulk Delete remain intact.
- The source-health label updater is defensive during localization and only addresses columns that actually exist.

## Version identity

- The current window title is re-applied after inherited localization hooks, so the running build reports `UA FREE Content Tool — v1.4.0-rc12` instead of falling back to an old `v1.3.1-rc7` title.
- `VERSION.txt`, `PUBLIC_VERSION.txt` and the Python package version are aligned at `1.4.0-rc12`.

## Preserved

- RC11 Inbox sorting/merged-block visibility fixes remain unchanged.
- RC10 `ОПУБЛІКУВАТИ ЗАРАЗ` remains isolated from the normal queue.
- No database schema migration and no Data reset.
