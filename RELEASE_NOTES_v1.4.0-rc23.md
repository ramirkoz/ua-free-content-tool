# UA FREE Content Tool v1.4.0-rc23

RC23 fixes the interactive rewrite hang exposed after RC22: the UI watchdog could stop a rewrite at 105 seconds while the background worker was still alive, and a second click then reported that the previous AI rewrite was still stopping.

## What changed

- Gives one absolute monotonic deadline to the entire AI Router task. Recovery attempts now consume the remaining budget instead of receiving the full timeout again.
- Stale-cooldown recovery runs only when the base router genuinely attempted zero providers because all configured routes were already cooling down.
- A provider that was actually tried and failed in the current task is not immediately taken out of the cooldown and hammered again.
- Cancellation is checked before and after every router pass and before every stale-cooldown recovery attempt.
- The rewrite worker therefore cannot multiply an 82-second AI task into several full 82-second retries behind the 105-second UI watchdog.
- Keeps RC22 truthful provider health, bounded cooldown policy and live Codex verification.
- Keeps RC21 full-current-day Inbox coverage unchanged.

## Compatibility

- No database schema migration.
- Existing Data, sources, groups, queue, publication history, AI keys, Rowboat memory, media references and settings are preserved.
