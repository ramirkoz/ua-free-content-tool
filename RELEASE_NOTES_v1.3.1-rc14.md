# UA FREE Content Tool v1.3.1-rc14

RC14 is a Windows UI/startup stabilization and operational-history retention release. It is based on the canonical RC13 GitHub/Drive source, not on locally repacked portable archives.

## Startup/UI stabilization

- A visible startup shell is created before SQLite validation or maintenance.
- Database construction and `PRAGMA quick_check` run off the Tk main thread.
- A startup watchdog can write `Data/ui_startup_freeze_trace.log` even when the main window has not yet been constructed.
- Inbox stale-group cleanup uses bulk updates in one transaction rather than per-group autocommits.
- Queue refresh hydrates targets and group labels in bulk and uses a 15-second safety poll.
- Remaining worker-thread Tk callbacks were moved onto the UI dispatcher.

## Seven-day publication history

- Publication History shows only the most recent rolling 7 days.
- Bulk statistics refresh works only on that same 7-day operational window.
- Completed/cancelled publication batches with sent targets older than 7 days are automatically moved out of the operational `publication_batches` / `publication_targets` tables into `archived_publication_batches` / `archived_publication_targets` tables in the same SQLite database.
- Archived platform statuses remain available to duplicate-publication checks, so archiving history does not allow an old successful target to be posted again.
- Because archive tables live in the same SQLite database, the existing Backup/Import flow carries them automatically; no separate archive-file handling is required.

## Compatibility

- Operational SQLite schema remains version 8; RC14 archive tables are additive and created lazily.
- Existing RC13 `Data` is compatible. No manual database migration is required.
- Collection, rewrite, media and publishing logic are unchanged except for the UI-thread and history-query behavior above.

## Upgrade

Use a fresh RC14 portable folder with the existing Data directory. Do not overlay program/runtime files onto RC13.
