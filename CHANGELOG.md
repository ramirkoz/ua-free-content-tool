# Changelog

## v1.2.2 — 2026-08-17

### Added

- Ollama-first local emergency AI runtime that reuses already installed Ollama and local models without reinstalling or downloading them.
- Hidden `ollama serve` startup on Windows when Ollama is installed but not running.
- Explicit local AI diagnostics that report the actual engine and model in use.
- Bounded global duplicate search with cancellation, global deadlines, GUI watchdog protection, and deterministic local fallback.
- Title-first duplicate candidate generation using rare terms and adjacent title bigrams.
- Regression coverage for large and noisy Inbox datasets and for the reproduced live duplicate pair among approximately 1000 items.

### Changed

- Production rewrite now uses the bounded AI Router and can reach Ollama in the real rewrite path, not only in diagnostics.
- Local rewrite and duplicate-classification prompts are compacted for small local models.
- Duplicate classification accepts the compact `MERGE ...` protocol while retaining compatibility with JSON responses.
- Strong deterministic duplicate candidates remain available for human review even when AI returns `NONE`, invalid output, quota errors, or times out.
- AI provider failures are bounded per operation so repeated quota/429 failures do not turn one duplicate scan into a multi-minute provider loop.

### Fixed

- Global duplicate search no longer hangs the Tkinter UI during long provider failover.
- Duplicate search no longer returns an empty result merely because AI formatting is invalid.
- Dense candidate posting lists no longer exhaust the internal search deadline before obvious duplicate pairs are surfaced.
- Late AI callbacks after timeout/cancellation are ignored.
- Local fallback no longer reports a generic llama.cpp failure when a working Ollama model is available.

### Validation

- Final RC7: 406 automated tests passed.
- Windows CI passed on Python 3.11, 3.12, and 3.13.
- Portable runtime build, GUI startup smoke, Microsoft Defender scan, and ZIP CRC/integrity validation passed.
- Live working-Data acceptance passed for both rewrite and global duplicate grouping.

## v1.1.4 — 2026-08-06

### Added

- Typed sorting by column headings in Sources, Inbox, Publication Queue, and Publication History.
- Ascending and descending indicators on the active sorted heading.
- A separate historical-performance forecast column in Inbox.

### Changed

- The application window title now reads the public version from `PUBLIC_VERSION.txt` instead of containing a hard-coded version string.
- The Inbox `Virality` column is now `Current potential`, while the forecast based on previous publication metrics is displayed separately.
- Historical forecasts show score and confidence, or an explicit insufficient-data status.
- Inbox refresh displays the last saved evaluation instead of recalculating the complete publication history for every visible row.

### Fixed

- The v1.1.3 application no longer displays the obsolete v1.1.2 title.
- Numeric scores such as `39/100` sort numerically rather than lexicographically.
- Date parsing used by sorting now fails safely for non-date values.
- Empty table values remain at the end of sorted lists.

### Validation

- 258 automated tests passed on Windows with Python 3.11, 3.12, and 3.13.
- `compileall`, entrypoint validation, and `import content_agent.main` passed.
- Database schema remains version 8 and existing `Data` requires no migration.

## v1.1.3 — 2026-08-05

### Security

- Replaced the withdrawn v1.1.2 PyInstaller launcher with an isolated runtime based on the unchanged official `pythonw.exe` signed by the Python Software Foundation.
- Added Authenticode signer validation, Microsoft Defender scans of the extracted runtime and final ZIP, fail-closed release commands, and final archive validation.
- Limited the release package to one executable and rejected diagnostic runtimes, databases, logs, secrets, unsafe paths, or unexpected executables.

### Validation

- 255 automated tests passed.
- Windows CI passed on Python 3.11, 3.12, and 3.13.
- Signed-runtime import, Tk startup, portable application startup, ZIP CRC and path validation, and Defender scans passed.

## v1.1.2 — 2026-08-05

### Added

- One-click background refresh of metrics for every sent publication target in Publication History.
- Progress reporting and platform-level circuit breaking for repeated DNS, timeout, token, and permission failures.
- Historical performance forecasting based on the installation's own measured publication results.
- Relative overall and per-platform potential scores with confidence and comparable-publication counts.

### Changed

- **Evaluate virality** is now **Evaluate potential** and combines Threads activity with historical performance evidence.
- Historical scoring normalizes each platform separately and ignores unavailable metrics instead of treating them as zero.

### Fixed

- Failed or skipped metric refreshes preserve previously collected statistics.
- Bulk refresh avoids repeating the same long platform failure for every historical post.

## v1.1.1 — 2026-08-05

### Added

- A Publication History tab before Settings with the rewritten headline, Kyiv publication date and time, networks, per-target status, stored post links, and available engagement metrics.
- Manual refresh of Facebook reactions/comments/shares and Threads views/likes/replies/reposts/quotes/shares.
- A dedicated exclusions manager that can deactivate selected rules or clear all active exclusions without erasing their audit history.

### Changed

- The active Inbox keeps current drafts and recently approved or still-queued stories; approved stories older than 24 hours move out of the working list and remain available in Publication History.
- Ollama prompts use the faster headline/facts/text marker protocol instead of asking small local models to emit JSON.

### Fixed

- Complete or truncated Ollama JSON is decoded safely. Raw JSON can no longer be saved as the publication headline, fact card, or rewrite text.
- A repaired rewrite now uses the repaired fact card instead of the rejected first response.
- Publication metric refresh preserves the original publication timestamp.
- Telegram history stores a public-channel permalink when possible and clearly reports that the Bot API does not expose post engagement statistics.
- LinkedIn metric failures are isolated and shown as permission limitations instead of blocking history.

## v1.1.0 — 2026-08-04

### Added

- Ukrainian and English application modes.
- Language-specific Ollama rewrite, repair, and queue-compression prompts.
- A focused topic-candidate dialog with explicit human confirmation before merging.
- Local learning statistics, configurable example limits, export, import, and history clearing.
- Learning events for generated rewrites, approved publications, manual merges, rejected candidate pairs, exclusions, and restored exclusions.
- Visible Inbox scrollbar and keyboard navigation with Page Up, Page Down, Home, and End.
- Approved-row highlighting and clearer one-row actions.
- Separate Facebook and Threads App IDs and App Secrets.

### Changed

- The selected interface language now controls final rewrite output and fact-card language.
- Ukrainian and English editorial examples and topic feedback use separate language-scoped signatures.
- Topic search no longer marks candidates across the full Inbox.
- Simple deletion remains separate from permanent “remember and exclude”.
- The portable build path and release workflow are version-aware instead of being tied to internal build R8 FIX30.
- Database schema upgraded from version 7 to 8 while preserving existing data and queue state.

### Fixed

- Completed localization of secondary dialogs, file dialogs, diagnostics, dynamic status messages, and the one-time queue migration window.
- Learning export/import now round-trips permanent content exclusions.
- Legacy UI regression tests remain compatible with localized dialog proxies.
- Windows timeout regression test tolerates hosted-runner scheduling jitter while still proving non-blocking behavior.

### Validation

- 238 automated tests passed on Windows with Python 3.12.
- `compileall`, entrypoint import validation, and `import content_agent.main` passed.
- Interface audit reported zero untranslated visible Ukrainian literals in the audited windows.

## v1.0.0 — 2026-08-02

First public release based on internal build R8 FIX30.

### Added

- Windows portable desktop application with a Ukrainian interface.
- Manual news collection, review and grouping workflow.
- Shift/Ctrl multi-selection in incoming news and publication queue.
- Manual merge of related reports.
- Topic candidate highlighting without automatic merging.
- Local Ollama rewrite based on all sources in a block.
- One canonical Ukrainian text of up to 900 characters.
- Editorial memory from final human edits.
- Separate delete and “remember and exclude” actions.
- Facebook Pages, Threads, LinkedIn and Telegram publishing.
- Google Drive media workflow.
- Partial retry and per-target publication status.
- Portable encrypted configuration and queue-preserving updates.

### Validation

- 223 automated tests passed on Windows 11 with Python 3.12.10.
- Portable PyInstaller build and startup passed.
- Clean-start and data-preservation probes passed.
- Shift selection and grounded Ukrainian rewrite guards passed.

### Known operational requirements

- Ollama and a compatible local model must be installed separately.
- Platform APIs and permissions must be configured by the operator.
- Live platform behavior depends on the operator’s tokens, pages, channels and account permissions.
