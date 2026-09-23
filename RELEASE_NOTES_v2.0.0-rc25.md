# UA FREE Content Tool v2.0.0-rc25 — MANUAL TEST

Targeted Windows handle-leak repair based on RC24 overnight type telemetry.

- Passive 10-second UI status refresh no longer launches Codex SDK app-server subprocesses while Agent/Codex is not the active backend.
- When Agent/Codex is active, the passive session probe cache is widened to 5 minutes. Manual login/test actions can still force an immediate probe.
- Added one shared Codex subprocess reaper. Completed SDK children are removed from the strong process registry and completed pipe streams are closed instead of being retained for the lifetime of the app.
- Added `system.codex_process_registry` telemetry: registered/reaped/registry_size/active/completed_retained/reaper_alive.
- RC24 Windows handle-type telemetry remains enabled so the live test can verify whether Process/Semaphore/File growth is actually gone.
- No collection, grouping, rewrite, publishing or source-selection behavior changed.
- MANUAL TEST: no auto-update promotion.
