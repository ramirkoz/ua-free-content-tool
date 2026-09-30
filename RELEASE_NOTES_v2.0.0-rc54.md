# UA FREE Content Tool 2.0.0-rc54

RC54 is the **operator UI/platform/data/DPI** milestone of the agreed roadmap, including corrections from the RC53 live operator review.

## Inbox operator corrections

- Visible Inbox columns are now only `Подія | Тема | Джерел | Час`.
- Removed visible block ID, status, source-name and current-potential columns.
- Publication time is displayed as Kyiv `HH:MM`; the redundant date is not shown in the current-day workspace.
- Source/Topic/Search SQL filtering and the RC53 `InboxTabController` remain canonical.
- Removed the hidden 200-group Inbox cap. The controller requests all matching rows and reports that full count.
- Approved/rewrite state remains visible through row styling rather than a redundant Status column.

## Potential/scoring removal

- Automatic potential score is no longer persisted or exposed as active operator product behavior.
- Historical score fields remain readable for schema compatibility only; `set_group_analysis()` is a compatibility sink until RC55 schema/dead-code cleanup.
- Operator judgement, not automatic potential scoring, determines editorial priority.

## Seven-day operational retention

- Added `RetentionService` to `AppServices`.
- The live portable database automatically removes operational news older than seven calendar days at startup.
- Sources, manual topics/assignments, settings, credentials, editorial learning and exclusions are preserved.
- Pending/in-progress/paused publication and unresolved `UNKNOWN` outcomes are protected from automatic deletion.
- Orphaned old groups are removed after eligible article deletion.
- SQLite VACUUM is bounded to at most once per local day and only when deletion actually occurred.
- The retention service is exposed in `Дані й резервні копії` with an explicit manual cleanup action.

## Platform/data UI

- Added a unified `Платформи` tab with readiness rows for Telegram, Facebook pages, Instagram, Threads, LinkedIn and Google Drive media storage.
- Added `Дані й резервні копії` with normal backup, migration backup, restore and retention controls.
- Google Drive remains media/storage rather than a publication destination.

## Layout / DPI

- Canonical shell applies bounded Tk DPI scaling and accepts compact window sizes down to the roadmap target range.
- Publication destination area is prioritized over media preview height so destination controls remain visible.
- No new `window_rc54.py` / `*_rc54_window.py` runtime layer is introduced.

## Acceptance

RC54 has a dedicated Windows gate, retained RC41-RC53 product regressions, RC54 operator/retention tests, repository-wide audit, signed portable build and exact artifact packaging.
