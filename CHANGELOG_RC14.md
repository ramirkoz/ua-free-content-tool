# v1.3.1-rc14 stabilization delta

- Tk window is created before SQLite validation and heavy maintenance.
- SQLite quick_check and startup Data work run outside the Tk main thread.
- Startup freeze watchdog writes `Data/ui_startup_freeze_trace.log` if the event loop stalls.
- Stale editorial group archiving uses bulk transaction writes instead of per-row autocommit.
- Publication history shown in UI and used for metric refresh is limited to the last 7 days at SQL level.
- Sent publication batches older than 7 days move from operational queue tables to archive tables in the same SQLite database.
- Archived sent targets remain part of duplicate-publication protection.
- Queue refresh uses bulk target loading and a 15-second safety poll.
- Threads connection error reporting uses the existing thread-safe UI queue instead of calling Tk directly from a worker thread.
