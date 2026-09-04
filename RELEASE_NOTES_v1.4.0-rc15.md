# UA FREE Content Tool v1.4.0-rc15

RC15 is an Inbox editorial-workflow release built directly on the live-accepted RC14 baseline.

## Inbox review workspaces

- Keyword-search results now open in the same near-fullscreen working geometry used by large merge/review dialogs.
- The merged-block composition editor also opens near-fullscreen, so source title, publisher, time and full article text can be reviewed without working inside a small fixed dialog.
- The geometry reserves safe space above the Windows taskbar instead of relying on Tk's maximized state, which can extend controls underneath the taskbar on DPI-scaled desktops.

## Source filter

- Inbox now includes a **Джерело** filter next to the RC14 keyword/composition tools.
- The selector is rebuilt from source names that are actually present in the current status-filtered Inbox working set.
- **Усі джерела** is the default.
- Selecting a source keeps every block containing at least one article from that source, including already merged blocks with multiple publishers.
- The filter is applied after the normal Inbox refresh, so the existing RC11 authoritative multi-sort remains the ordering engine.

## Compatibility

- RC14 keyword search, manual merge, safe detach, learning feedback and queued/published protections are unchanged.
- RC13 exact per-destination scheduling is unchanged.
- RC12 source-health compatibility, RC11 Inbox sorting and RC10 publish-now behavior are preserved.
- No SQLite schema migration.
- Existing portable `Data` remains compatible and must be carried forward unchanged.
