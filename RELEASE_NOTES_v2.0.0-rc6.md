# UA FREE Content Tool v2.0.0-rc6

RC6 is a focused stabilization release based on live Supervisor evidence from 12 September 2026.

## Fixed

- **Fact Guard semantic false-positive:** a source claim such as `рекордное количество` may safely be rewritten as `найбільша кількість` when the source clearly describes a record quantity and not a record low. Other strengthening rules remain strict.
- **Rewrite routing precedence:** explicit rewrite intent is evaluated before generic `topic/тема` markers, so editorial rewrites cannot silently fall into the FAST_CHEAP TOPIC route merely because the long prompt contains topic metadata.
- **Dead OpenRouter endpoints:** an explicit `HTTP 404: No endpoints found` quarantines only that concrete model for 12 hours and persists the quarantine in `Data/v2/openrouter_dead_models.json`. Healthy siblings/families remain eligible.
- **Bounded DNS resolver:** the old per-request daemon DNS thread path is replaced with four fixed daemon workers plus a bounded queue. Resolver stalls can no longer create an unbounded number of native threads/handles.
- **Windows descriptor headroom:** startup raises the MSVCRT stdio ceiling to 8192 while retaining leak telemetry. This is containment, not a substitute for closing resources.
- **Resource-exhaustion containment:** collection stops the current cycle on `Too many open files` instead of falsely recording the same local process failure against every enabled source. Supervisor backs off for ten minutes when it itself hits that condition.
- **Supervisor observability:** status now includes thread count, Windows process handle count, and bounded DNS resolver statistics; high handle pressure and DNS queue pressure become explicit incidents.

## Compatibility

- Existing `Data` is compatible. Do not delete or rebuild the database.
- Close the previous build, extract RC6 into a new folder, then copy the working `Data` folder into it.
- Windows GUI runtime was not executed inside the Linux build environment; live Windows burn-in is still required.
