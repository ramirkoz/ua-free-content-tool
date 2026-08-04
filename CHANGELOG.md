# Changelog

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
