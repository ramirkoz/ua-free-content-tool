# UA FREE Content Tool v2.0.0-rc24 — MANUAL TEST

Resource-forensics build for the unresolved Windows kernel-handle leak. No content selection, collection rules, AI routing, publishing logic or Drive folder layout was changed.

- Adds Windows process handle census grouped by kernel object type (`process_handle_types`).
- Supervisor records per-type baseline and growth (`types_current`, `types_growth`) so the leaking subsystem can be identified from live telemetry instead of guessed.
- Adds CRT stdio open-handle count.
- Adds SQLite connection lifecycle counters: opened, closed, active.
- Extends DNS telemetry with submitted, completed and in-flight request counts.
- Removes needless temporary `threading.Event()` construction from supervisor status/runtime paths.
- Existing HTTP connection/response lifecycle counters remain in place for cross-checking.
- MANUAL TEST: auto-update promotion remains disabled.
