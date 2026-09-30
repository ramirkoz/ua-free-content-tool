# UA FREE Content Tool 2.0.0-rc46

RC46 supersedes the failed RC45 manual-test candidate. RC44 remains the synchronized accepted baseline until this candidate is manually validated and explicitly promoted.

## Fixed after RC45 manual validation

- Clean import now accepts the outer folder produced by extracting the portable ZIP, for example:
  `UA_FREE_Content_Tool_v2.0.0-rc44_Windows_Portable_MANUAL_TEST/UA_FREE_Content_Tool/Data/content_agent.sqlite3`.
- The import locator also accepts the application folder itself, its `Data` folder, a one-level versioned `UA_FREE_Content_Tool*` application folder, or the SQLite file directly.
- The locator remains deliberately shallow and restricted to the Content Tool package naming family so it does not recursively import an unrelated database.
- Added regression tests for all supported folder selections, including the exact extracted-wrapper layout that failed in RC45.

## Inherited RC45 reliability work

- modern manual-topic-aware backup validation and backup → restore round-trip coverage;
- one active `create_database()` composition for startup and restore;
- post-import database recreation, migration/reconciliation and foreign-key validation;
- durable publication receipt carry-over during clean import;
- SQLite backup compression outside the maintenance lock;
- fail-closed handling of ambiguous external publication outcomes;
- mandatory Fact Guard → sanitize → Anti-Slop acceptance path;
- bounded Agent/Codex execution and skip/cancel boundary checks;
- active V2 UI callback exception logging;
- retained RC41/RC42/RC43/RC44 regression coverage;
- no new versioned runtime/UI/database inheritance layer.

## Promotion rule

RC46 is a manual-test candidate. Do not replace Drive CURRENT or ProductVault canonical RC44 state until operator validation succeeds and promotion is explicitly requested.
