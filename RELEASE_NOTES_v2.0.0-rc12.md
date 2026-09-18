# UA FREE Content Tool v2.0.0-rc12

RC12 is the canonical synchronization release that merges the proven RC11 runtime with the corrected RC10 diagnostics model.

## Preserved from the real RC11 runtime

- Remote-control Drive transport/auth failures propagate to the Supervisor circuit breaker.
- HTTP 401/403/invalid_grant enters a real 15-minute backoff and cached Drive/auth state is discarded before retry.
- Remote-control polling and status uploads use independent schedules.
- Drive work is suppressed early when Windows process-handle growth becomes abnormal while local collection/publication/status continue.
- Supervisor distinguishes auto_collect_running, auto_collect_scheduled and auto_collect_enabled.
- The five-minute auto-collect watchdog restores a missing Tk schedule when background services are alive.
- Durable external-publication receipts and reconciliation are preserved.

## Diagnostics corrections merged into RC12

- Added explicit DRIVE_REAUTH_REQUIRED state after Drive authentication failures; Analyzer must not misattribute this to OpenRouter/AI.
- Retained failed_targets_24h as historical context while adding failed_targets_15m, failed_targets_60m and last_failed_target_at.
- Active publication warning now requires a fresh failure wave: >=3 failures in 15 minutes or >=5 in 60 minutes.
- process_handle_count is treated as the Content Tool process count, not whole-Windows pressure.
- Removed the misleading 6000-handle warning; thresholds align with containment: soft >=16000 with growth >=750, hard >=20000.
- Finished operations report operation_age_seconds=0 and an empty operation label.

RC12 preserves existing Data and settings and keeps the RC8+ remote update/restart/rollback protocol.
