# UA FREE Content Tool v1.4.0-rc7

RC7 fixes two runtime regressions that remained visible in RC6.

## Duplicate-review dialog

- RC6 corrected the internal grid, but Windows `state("zoomed")` could still maximize the transient dialog underneath the taskbar.
- RC7 no longer relies on Windows zoomed state for this dialog. It opens near-fullscreen with an explicit bottom work-area reserve in Tk coordinates.
- A runtime guard checks the actual `Об'єднати вибрані матеріали` button after layout and shrinks the window once if the footer still approaches the unsafe bottom edge.
- Manual column widths, horizontal scrolling, persistent layout, and the RC6 confidence colours are preserved.

## Last-used publication destinations

- The historical target-preset layer already knew how to prefer the last actually used selection for a fresh material.
- v1.4 later overrode `apply_recommendations()` and unintentionally replaced that behaviour with destination recommendations every time another fresh material was opened.
- RC4/RC5 restored the last selection only at startup / fixed persistence writers, but did not fix this per-material override.
- RC7 makes persisted `last_targets` authoritative on every fresh material load. Only currently available destinations are restored; if none remain available, normal recommendations are used as fallback.
- Existing queued/publication target statuses are still respected when opening material that already owns concrete queue state.

## Validation

- Adds behavioural regression coverage for the actual RC7 duplicate-dialog class used by the historical duplicate workflow.
- Adds a behavioural test proving that a fresh material restores persisted last-used destinations instead of applying new recommendations.

No database schema or publication-model change is included in RC7.
