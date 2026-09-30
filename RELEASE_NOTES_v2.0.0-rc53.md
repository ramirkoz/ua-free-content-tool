# UA FREE Content Tool 2.0.0-rc53

RC53 is the **Inbox/shared UI components/first TabController** milestone of the agreed roadmap.

## What changed

- Added the first real `TabController` boundary: `InboxTabController` owns Inbox filter state, SQL query and rendering.
- Source + Topic + Search now live in one authoritative `FilterBar`.
- Source/Topic/Search filtering is performed in SQLite through `list_inbox_groups()` instead of deleting non-matching Treeview rows after loading them.
- Multi-word Inbox search keeps AND semantics across group/article title and text.
- Added shared `ActionBar`, `FilterBar`, `StatusBar` and `PublicationStatus` components.
- The canonical stable shell now uses shared components while the previous large RC44 shell is frozen as an explicit legacy compatibility boundary.
- Added a visible `Джерело` column, retained `Джерел` count, removed hidden/legacy columns from the canonical display order, and persist Inbox column widths.
- Inbox timestamps use one `dd.mm.YYYY HH:MM` Kyiv format.
- `Ctrl+F` focuses the canonical Inbox search field; `Esc` clears search and returns focus to the Inbox list.
- The Supervisor tab is labelled `Стан системи`.
- No new version-numbered `window_rc53.py` or `*_rc53_window.py` layer was added.

## Deliberately not included

RC54 owns the remaining full UI/platform/data consolidation and DPI/manual layout hardening. RC55 owns final architecture cleanup, updater security and repository-wide suite closure.

## Acceptance

RC53 has a dedicated Windows gate, retained RC41-RC52 release regressions, architecture invariants, repository-wide audit, signed portable build and exact artifact packaging.
