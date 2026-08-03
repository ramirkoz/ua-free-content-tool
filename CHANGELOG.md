# Changelog

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
