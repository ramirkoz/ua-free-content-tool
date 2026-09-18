# UA FREE Content Tool v2.0.0-rc10

RC10 is a diagnostics and recovery-clarity release. It does not change content selection, rewriting or publishing policy.

## Google Drive reauthentication

- Supervisor now exposes an explicit `DRIVE_REAUTH_REQUIRED` incident after 401/403/invalid-grant style Drive authentication failures.
- The runtime records `drive_runtime.auth_required` until a successful Drive operation proves recovery.
- The user-facing Supervisor status identifies that Google Drive must be reconnected instead of presenting a generic retry/backoff error.
- Supervisor Analyzer is explicitly forbidden from attributing a Drive credential failure to OpenRouter or another AI provider.

## Publication failure telemetry

- The old 24-hour failure count is retained as historical context.
- Added `failed_targets_15m`, `failed_targets_60m` and `last_failed_target_at`.
- `PUBLISH_FAILURES_ACTIVE` is raised only for a fresh failure wave: at least 3 failures in 15 minutes or 5 in 60 minutes.
- Historical failures from an already-recovered incident no longer keep the current system in a false warning state.

## Windows handle diagnostics

- `process_handle_count` is explicitly treated as the handle count of the Content Tool process, not the whole Windows session.
- Removed the misleading warning at 6000 handles.
- Warning thresholds are aligned with the RC9 containment logic: soft pressure at >=16000 only when growth since Supervisor start is >=750; hard pressure at >=20000.
- Supervisor Analyzer must not recommend closing browser tabs or unrelated programs solely from Content Tool process-handle telemetry.

## Operation telemetry

- Finished operations now report `operation_age_seconds=0` and an empty operation label instead of carrying stale elapsed time after completion.

RC10 preserves Data, settings, the RC8 remote update/restart protocol and the RC9 publication-success recovery receipts.
