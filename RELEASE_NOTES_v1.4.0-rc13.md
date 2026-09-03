# UA FREE Content Tool v1.4.0-rc13

RC13 fixes the per-destination publication scheduler so a configured interval is honored exactly instead of being rounded again against the minute of the clock hour.

## Exact destination intervals

- A 45-minute schedule now stays 45 minutes: `17:45 -> 18:30 -> 19:15`.
- The previous scheduler could turn 45 minutes into 60 or 75 minutes because it added the configured interval and then performed a second modulo-based rounding step.
- The cadence remains anchored to the latest scheduled publication for that destination.
- If a slot was missed during the same publishing window, the next slot stays on that destination's cadence instead of switching to an unrelated wall-clock grid.
- First slots without an earlier scheduled item are aligned from the configured daily start time.
- Start/end publishing windows and next-day rollover remain enforced.
- Existing 60-minute and other supported intervals remain unchanged in meaning.

## Regression coverage

- Covers the reported `17:45 + 45 min = 18:30` case.
- Covers `17:30 + 45 min = 18:15`.
- Covers repeated 45-minute sequences without drift.
- Covers missed slots, first-slot alignment, 60-minute behavior and end-of-window rollover.

## Preserved

- RC12 Sources-tab health-column fix remains intact.
- RC11 Inbox sorting/merged-block visibility fixes remain intact.
- RC10 `ОПУБЛІКУВАТИ ЗАРАЗ` remains isolated from the normal queue.
- No database schema migration and no Data reset.
