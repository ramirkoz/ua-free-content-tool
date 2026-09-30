# UA FREE Content Tool 2.0.0-rc50

RC50 is the storage/backup/composition milestone of the Claude architecture roadmap. It deliberately does not pull RC51 AI consolidation or RC52 platform-adapter work forward.

## Backup / restore

- The active V2 UI now creates backups through `AppServices.maintenance`, not the legacy backup module.
- Normal backup uses the durable schema-3 contract and contains the SQLite snapshot, durable sidecars and publication receipts, but no transferable credentials.
- A separate password-protected migration backup is available for cross-machine credential transfer.
- Migration credentials use the existing scrypt + AES-GCM protection and are password-validated before a restore is staged.
- Restore is now a restart-boundary operation: the running process validates and stages the archive, then the next process applies it before constructing the active database.
- Portable restart passes a migration password only through the child process environment; the password is not written into `Data`.
- Historical schema-2 backups remain readable.

## Numbered migrations

- Manual topics schema ownership moves out of `ManualTopicsMixin.__init__` into numbered migration `0008_manual_topics`.
- Existing RC43+ databases are adopted idempotently: already-present `manual_topics` / `sources.topic_id` are recorded without data loss.
- `0009_publication_target_outcome` and `0010_articles_discovered_at_index` remain unchanged.
- The active manual-topics regression now tests the real `create_database()` composition rather than a synthetic `ManualTopicsMixin + BaseDatabase` class.

## Composition root

- `AppServices` now owns a `MaintenanceService` alongside the active DB/config/AI gateway.
- Backup creation, migration backup and restore staging are application services; UI no longer selects a storage implementation directly.

## Safety / acceptance

RC50 adds regressions for:
- RC42 database -> active manual-topic numbered migration without source loss;
- no schema-mutating constructor in `ManualTopicsMixin`;
- active composition owns maintenance;
- normal backup excludes credentials while keeping durable state;
- migration-backup password validation before staging;
- active stable window uses the maintenance boundary;
- no new `*_rc50_window.py` runtime layer.

The Windows RC50 gate also runs the repository-wide test suite, retained RC41-RC49 gates, signed portable build and package creation.

## Deliberately deferred

- AI monkey-patch removal / final backend consolidation: RC51.
- DestinationRegistry and platform adapter consolidation: RC52.
- Inbox TabController/shared UI components: RC53.
- Platforms/Data full UI restructuring and DPI acceptance: RC54.
- legacy MRO/dead-code/security final consolidation: RC55.
