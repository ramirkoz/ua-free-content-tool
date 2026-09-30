# UA FREE Content Tool 2.0.0-rc45

RC45 is a focused reliability and safety update on top of the synchronized RC44 baseline. It deliberately avoids a large UI/storage rewrite.

## Backup / restore

- Current RC43/RC44 databases with `manual_topics` and `sources.topic_id` are accepted by the backup validator.
- Older schema-8 backups without manual topics remain readable.
- Backup validation still fails closed on unknown tables/columns.
- Manual backup holds the maintenance lock only while taking the SQLite snapshot; ZIP compression runs after the lock is released.
- Restore and startup use the same active `v2.storage.reliable.Database` composition through `create_database()`.
- A round-trip regression test covers current-schema backup → restore.

## Clean import

- After selective first-run import, the active database composition is recreated so one-time migrations and publication receipt reconciliation run on imported rows.
- `PRAGMA foreign_key_check` is enforced after table import.
- Valid `publication_recovery/target_*.json` receipts are carried only when the referenced target exists in the imported database.

## Rewrite safety

- Every candidate, including same-provider repair results, now passes one mandatory acceptance gate: Fact Guard → sanitize → Anti-Slop.
- A candidate that fails only Anti-Slop no longer falls through into an empty `FACT-SAFE REPAIR`.
- Fact repair only runs for an actual Fact Guard rejection.

## Publication retry safety

- Existing unknown-outcome markers and started-without-completed progress now fail closed in `resume_batch` and rescheduling.
- No new schema column is introduced in RC45; structured publication outcomes are deferred to a later numbered version.

## AI runtime safety

- Agent/Codex backend uses the existing bounded Codex watchdog instead of unbounded `run_codex()`.
- Agent/OpenRouter skip checks and pre/post cancellation checks remain explicit at the V2 service boundary.

## UI threading / diagnostics

- Queued UI callback exceptions are logged instead of silently swallowed in the active V2 window.

## Regression / architecture gates

- Active database composition test.
- Current-schema backup round-trip test.
- Unknown-outcome retry guards.
- RC27 QA acceptance/repair matrix.
- Real Tk management test for the RC44 Source/Topic filter row when a GUI display is available.
- RC45 runtime filename/PR gate prevents adding a new `*_rc45*` application layer.
- RC41 Drive auth, RC42 Instagram multi-account, RC43 manual topics and RC44 Inbox filters remain required gates.

## Intentionally not included

RC45 does not yet introduce `AppServices`, numbered schema migrations, a new publication-outcome column, backup format v2, platform-adapter registry or a new TabController UI shell. Those follow in later sequential RC versions after this safety baseline is validated.
