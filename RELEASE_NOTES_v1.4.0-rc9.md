# UA FREE Content Tool v1.4.0-rc9

RC9 fixes two production regressions found in the v1.4 source/settings UI.

## Sources

- New sources default to **auto** type detection instead of assuming RSS.
- Strong Telegram addresses (`@channel`, `t.me`, `telegram.me`) are automatically stored as `telegram` even if the selector was left on the wrong value.
- Strong feed addresses (`/feed`, `/rss`, `.xml`, `.rss`, Atom/RSS query markers) are automatically stored as `rss`.
- Generic HTTP(S) addresses remain `url`; unusual feeds can still be forced to `rss` manually.
- Sources are now editable without deleting their accumulated history. Editing can change type, name and address; changing a source resets only its last-check timestamp.
- The Sources table now uses real extended selection: Shift range, Ctrl individual rows and Ctrl+A work.
- `Delete` and the Delete button remove all selected sources with one confirmation and one database transaction.
- Double-click opens the selected source editor.

## Publication schedules

- The obsolete common/global publication schedule is removed from the v1.4 Settings UI. v1.4 has one schedule per concrete destination and no longer exposes a second competing scheduler.
- Existing per-profile schedules are preserved.
- For a destination that has never had an explicit schedule, the old global values are copied **once** as migration defaults and immediately materialized into that destination's own schedule row. Later runtime decisions do not consult the common schedule.
- Queue approval continues to calculate one slot per destination.
- Recovery/rescheduling of paused or overdue v1.4 batches now also uses each destination's own start/end/interval instead of the legacy global schedule.
- Pre-v1.4 multi-target batches are not silently forced onto one profile's clock during recovery; they are left untouched rather than violating independent schedules.

## Compatibility

- No database schema migration.
- Existing sources, articles, groups, queues, media references, social tokens and editorial learning data are preserved.
- Existing `destination_schedules_v1_4.json` values are preserved.
