# UA FREE Content Tool 2.0.0-rc56

RC56 is a focused live-acceptance bugfix release on top of the RC55 final architecture.

## Fixed

- AI provider configuration is no longer duplicated in Settings; the dedicated AI tab is authoritative.
- Static publication images are normalized to an Instagram-supported feed aspect ratio without cropping the source image.
- Media discovery again shows an explicit indeterminate progress indicator in the publication media area.
- Anti-Slop blocks vague pseudo-attribution such as `офіційні джерела повідомляють` and `за даними джерел`.
- Inbox text search uses Unicode `casefold`, so Ukrainian/Cyrillic search is case-insensitive.
- Inbox refresh/delete preserves a surviving viewport anchor instead of drifting down the list.
- Exact Telegram post media discovery retries once, uses a safe exact-embed fallback, and emits `TELEGRAM_MEDIA_NOT_RESOLVED` telemetry when media cannot be resolved.

## Compatibility

- No new version-numbered MainWindow layer.
- Existing RC55 storage, publication, backup, updater and composition contracts remain intact.
