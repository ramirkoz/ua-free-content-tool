# UA FREE Content Tool v2.0.0-rc9

RC9 is a production-stability release focused on publication history integrity and Supervisor retry/resource containment.

## Publication success reconciliation

- Added a durable per-target recovery receipt before an externally accepted publication is committed as `sent` in SQLite.
- Pending receipts are reconciled before the publication worker can claim another due batch.
- A target with a known external success receipt is never downgraded to `failed` merely because the local database commit failed.
- Batch-level failure handling excludes targets with unresolved external-success receipts, preventing an automatic retry from duplicating an already accepted post.
- Reconciliation is idempotent: a leftover receipt can safely re-assert the same `sent` state and is removed after a successful local commit.

## Supervisor / Google Drive containment

- Added authentication-aware Drive backoff. Repeated 401/403/invalid-grant failures now back off for 15 minutes instead of polling every Supervisor cycle.
- Other Drive failures use bounded exponential backoff up to five minutes.
- Remote-control polling, status upload and report upload share the same containment state.
- Local status/incident files continue to be written while Drive is unavailable.

## Windows handle telemetry

- Supervisor status now records handle baseline, current count, growth since Supervisor start, per-cycle delta and estimated hourly growth.
- At high and growing handle counts, secondary Drive polling is suppressed to preserve the editor/publisher process instead of worsening resource exhaustion.

RC9 preserves existing Data, settings and the RC8 remote update/report/restart protocol.
