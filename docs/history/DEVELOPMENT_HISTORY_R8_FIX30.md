# UA FREE Content Tool Development History — R8 FIX30

This document summarizes the product and stabilization path that led to R8 FIX30.

## Core product direction

The application collects current news as separate blocks, helps an editor find and manually merge materials about the same event, uses all materials in the block for one rewrite of up to 900 characters, learns from approved editorial changes, and publishes one canonical text to Facebook Pages, Threads, LinkedIn, and Telegram.

## Core workflow

1. Enabled sources are checked after startup and periodically.
2. Every collected item remains separate in Incoming until the editor merges it.
3. Topic search highlights possible matches without automatic grouping.
4. The editor opens a block containing all selected source texts.
5. Ollama produces one canonical Ukrainian-language draft.
6. The editor reviews and approves the final text.
7. Publication targets, media, and scheduling are configured in one place.
8. Queue execution preserves per-target status and supports safe partial retry.

## Major product capabilities established before FIX11

- Manual editorial grouping instead of uncontrolled semantic auto-merge.
- One canonical publication across all supported platforms.
- Responsive Tkinter layout and configurable font size.
- Google Drive media workflow with temporary per-file access for Threads.
- Portable `Data` folder with encrypted configuration and migration from legacy `%LOCALAPPDATA%` storage.
- Development and portable build launchers that run without administrator rights.

## FIX11: bounded Threads profile and keyword checks

- Switched profile lookup to the official unversioned `https://graph.threads.net/me` endpoint.
- Sent the token in the Bearer header.
- Added a real end-to-end UI watchdog rather than relying only on socket timeout.
- Separated profile detection from trend-search diagnostics.

## FIX12: editable multi-platform queue

- Re-approving a news item updates the existing package instead of creating duplicates.
- New targets can be added, unsent text can be updated, and unselected pending targets can be removed.
- Sent targets remain immutable.
- Queue packages can be opened, edited, cancelled, and filtered.
- Rejected incoming blocks leave the active list but remain available for deduplication and recovery.

## FIX13: canonical time and overdue execution

- Stored new schedules in UTC and displayed them in Kyiv time.
- Compared legacy offset timestamps as absolute moments.
- Rescheduled overdue edited packages to fresh future slots.
- Woke the worker after queue changes and refreshed the Queue view automatically.

## FIX14: transparent partial-publication results and diagnostics

- Preserved explicit per-target errors instead of returning packages to an ambiguous pending state.
- Avoided reposting successful Threads or LinkedIn targets during retry.
- Added background diagnostics for Facebook, Threads, LinkedIn, Telegram, and Google Drive.
- Distinguished expired credentials, missing permissions, and temporary network failures.

## FIX15–FIX18: faster and more reliable Ollama operation

- Replaced multiple per-platform rewrites with one canonical rewrite request.
- Added streaming response handling, model keep-alive, and bounded primary/fallback timing.
- Improved handling when both models fail.
- Removed false UI timeouts that interrupted valid long-running local inference.

## FIX19: sequential publishing and bounded retry

- Processed publication targets sequentially instead of creating a retry storm.
- Added bounded retry delays for temporary failures.
- Paused packages after repeated failures.
- Preserved successful targets during recovery.
- Added tested schema migration support for the queue changes introduced at that stage.

## FIX20: Ukrainian-only rewrite enforcement

- Required Ukrainian output even when the source material was Russian.
- Checked the complete result for Russian-language markers.
- Performed one corrective request when needed.
- Refused to save or queue a second invalid result.

## FIX21: standard multi-selection in Queue

- Added Shift range selection, Ctrl toggle selection, and Ctrl+A.
- Applied Delete and cancel actions to all selected packages.
- Kept batch cancellation atomic.
- Required exactly one package for edit and retry actions.

## FIX22: manual merge of incoming news

- Added multi-selection to Incoming.
- Merged selected sources into the primary selected block.
- Cleared stale rewrite, fact card, platform text, and trend assessment after source composition changed.
- Prevented merging blocks that already had queue or publication history.
- Kept the operation atomic.

## FIX23: Meta token lifetime and schedule recovery

- Blocked repeated authorization calls after a confirmed Facebook or Threads credential failure.
- Kept independent LinkedIn and Telegram targets running.
- Added Meta App ID and App Secret support for eligible long-lived-token exchange.
- Added rescheduling for missed and paused packages without duplicating sent targets.

## FIX25: adaptive settings and a true clean start

- Reworked Settings to fit the visible window without hidden horizontal content.
- Kept the save action visible.
- Added `clean_start.flag` to prevent automatic import of old tokens, sources, or queue into a fresh portable copy.

## FIX26: live-publication stabilization

- Disabled automatic semantic grouping completely.
- Added multi-item delete to Incoming.
- Removed the artificial 80-second rewrite timer and allowed bounded longer inference.
- Avoided holding a global SQLite maintenance lock during external publication calls.
- Added hard target timeouts and treated timeout results as unknown to prevent automatic duplicates.
- Improved logging and global operation status.

## FIX27: one editor, editorial memory, and topic search

- Replaced multiple platform editors with one canonical text of up to 900 characters.
- Stored original materials, Ollama draft, and approved human text as editorial examples.
- Added local similarity selection and one-model topic verification.
- Recorded manual merges as positive grouping examples.
- Preserved complete Threads text as a main post plus replies with resumable progress.
- Added schema fields for draft text, editorial examples, and merge feedback with verified backup before migration.

## FIX28: safe one-time queue conversion

- Prevented the publication worker from starting before active-queue inspection.
- Blocked conversion when a package was publishing, overdue, or scheduled for the current Kyiv date.
- Presented future over-limit texts in a review wizard.
- Compressed approved text without rebuilding the story from sources.
- Preserved IDs, times, platforms, media, statuses, attempts, remote IDs, and already-sent targets.
- Created a complete backup and applied updates in one SQLite transaction.

## FIX30: controlled exclusions and full-source rewrite

- Separated ordinary Delete from Remember and exclude.
- Added local content-exclusion rules for highly similar future materials.
- Passed a compact factual extract from every source in the block.
- Displayed `N of N` source coverage.
- Removed channel advertising tails before Ollama input.
- Added one compression request for over-limit output and a deterministic final shortening fallback.
- Added only the `content_exclusions` table in schema version 7.

## FIX30: reliable Shift selection on Windows

- Added an explicit Shift-click range handler for Incoming and Queue.
- Selected ranges in visual row order regardless of click direction.
- Preserved Ctrl-click, Ctrl+A, Delete, existing queue content, schema version 7, tokens, sources, times, and media.
