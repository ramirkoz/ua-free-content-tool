# UA FREE Content Tool 2.0.0-rc47

RC47 continues the reliability/architecture roadmap on top of RC46 without adding another version-numbered runtime UI layer.

## Changes

- Adds `AppServices` and `build_services()` as the first explicit application composition root.
- Startup now composes the active reliable database, config and AI gateway once and passes that service container into the active V2 UI shell.
- Backup restore rebuilds the same `AppServices` composition after replacing Data/config.
- Adds typed `AIRequest` and `AIBackend` contracts plus a stable `AIGateway` entry point.
- Existing OpenRouter, Agent/Codex and Router behavior is preserved behind backend adapters; the legacy public call signature remains compatible.
- Adds numbered V2 migration registry `schema_migrations` while keeping legacy `PRAGMA user_version=8` as the historical compatibility baseline.
- Adds migration `0009_publication_target_outcome`.
- Adds explicit publication outcomes: `not_attempted`, `sent`, `failed_known`, `unknown`, `confirmed_not_sent`.
- Existing fail-closed unknown-outcome markers are backfilled into the explicit outcome column.
- Successful receipt reconciliation and normal send/fail paths keep outcome state synchronized.
- Adds database API for explicit operator confirmation that an unknown external attempt was not sent.
- Backup validation remains backward compatible with RC44/RC46 databases and now accepts the additive V2 migration table/outcome column.
- Adds RC47 regression tests for composition, AI contracts, migration/backfill, explicit outcome state and backup compatibility.
- Keeps the historical RC46 workflow as a regression gate on later PRs instead of trying to package a fake RC46 artifact from a newer version.

## Preserved

- RC46 clean-import wrapper discovery.
- RC45 backup/recovery and QA hardening.
- RC44 visible Source/Topic filter row.
- RC43 manual source topics.
- RC42 Instagram multi-account behavior.
- RC41 Google Drive auth recovery.

## Deliberately not included yet

- No UI redesign.
- No mass deletion/collapse of legacy RC layers.
- No platform adapter registry yet.
- No Backup format v2/staging restore yet.
- No signed Ed25519 update manifest yet.
- Legacy direct Router runtime patching remains behind the new typed AI contract for now.
- Router-state concurrency hardening remains a later change.
