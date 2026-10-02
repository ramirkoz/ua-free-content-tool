# UA FREE Content Tool 2.0.0-rc59

Focused media UX and reliability repair on top of the repaired RC58 baseline.

- Restores deterministic human-readable media filenames based on the material headline/context and group ID. The RC56 Google Drive client had bypassed the earlier readable-name wrapper, which caused opaque candidate/download names to return.
- Keeps the media progress bar visible while idle. It animates only while one or more media discovery jobs are active and uses a reference counter so overlapping jobs cannot hide or stop each other incorrectly.
- Adds bounded retries for read-only media candidate downloads to reduce one-off missing preview/image/video fetches.
- Strengthens exact Telegram post media discovery with one additional embed retry and bounded retries for Telegram player pages.
- Preserves RC58 grouped-video extraction, 2–10 video selection and Telegram native media-group delivery.
- Adds RC59 regressions for readable media names, transient media download recovery, Telegram empty-embed retry, progress-bar lifetime and publication context propagation.

Runtime acceptance remains telemetry-based. RC59 should be validated live against the reported intermittent video/preview cases before it becomes the fully accepted operator baseline.
