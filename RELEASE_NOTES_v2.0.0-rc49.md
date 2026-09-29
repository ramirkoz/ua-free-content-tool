# UA FREE Content Tool 2.0.0-rc49

Manual-test candidate built on RC48.

## RC49 changes

- Defers Supervisor startup until the complete outer Tk shell is ready.
- Prevents startup-time Supervisor `quick_check` from contending with Source/Topic UI reads on the global SQLite maintenance lock.
- Moves the update-health marker to the point where the full UI is ready and Supervisor can actually start.
- Adds V2 migration `0010_articles_discovered_at_index`.
- Rewrites `count_today_articles()` to use an indexed canonical UTC range instead of `julianday(discovered_at)` over the whole historical article table.
- Adds regression tests proving Supervisor stays dormant before `_ui_ready` and the current-day query uses `idx_articles_discovered_at`.
- Replaces the ambiguous first-run Yes/No prompt with explicit operator choices: `Імпортувати`, `Почати з чистого`, `Вирішити пізніше`.
- `Вирішити пізніше` does not create a permanent first-run marker, so the choice is offered again on the next launch.
- Startup progress stages are rendered as human Ukrainian labels rather than internal identifiers.
- Preserves RC48 Source/Topic filter fixes, explicit publication outcomes, manual-edit rewrite protection, adaptive shell layout and unknown-publication fail-closed UX.

## Live incident addressed

RC48 telemetry on a ~315 MB portable database reported a 12.2 second `UI_STALLED` during startup. Diagnostic stack traces showed two contributing causes:

1. Supervisor started from an inner V2 constructor while outer Source/Topic UI construction was still active, then performed `PRAGMA quick_check` under the global database maintenance lock.
2. `count_today_articles()` wrapped `discovered_at` in `julianday()`, preventing an efficient index range scan on the large historical `articles` table.

RC49 addresses both mechanisms without weakening the startup watchdog or runtime Supervisor.

## Not claimed in RC49

This candidate does not yet claim completion of the remaining broader roadmap items such as backup-format-v2 credential separation, full AI-tab consolidation, DestinationRegistry extraction, signed Ed25519 release manifests, or large MRO/TabController consolidation. Those remain subsequent work after RC49 manual/live acceptance.
