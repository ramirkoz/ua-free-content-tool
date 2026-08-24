# UA FREE Content Tool v1.3.1-rc13

Focused publication-queue stabilization on the canonical RC12 source.

## Fixed
- Drive publication preflight no longer runs the expensive Threads public-URL probe for every generic media read.
- Publication-side Google OAuth refresh is bounded to 15 seconds.
- Drive media preflight hard limit is 100 seconds and now exceeds the bounded token + metadata + download path instead of contradicting its inner timeouts.
- One batch can have only one Drive preflight in flight. A late read is reused by the next controlled retry instead of spawning overlapping daemon requests.
- Threads public accessibility is checked only when Threads actually needs the URL, before a temporary permission is created.
- Explicit queue cancellation is audited with a reason and has its own WorkerResult state. The UI no longer describes a cancelled package as if its unsent targets were awaiting automatic retry.
- Stale orange preflight warnings are cleared when a controlled retry starts making publication progress.

## Compatibility
- No SQLite schema change.
- Copy the complete existing `Data` directory into a fresh RC13 portable folder.
- Already-sent targets remain protected from duplicate publication.
