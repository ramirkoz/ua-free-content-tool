# UA FREE Content Tool 2.0.0-rc48

RC48 follows RC47 and applies the first critical UI/UX findings from the independent RC46 review without introducing another version-numbered MainWindow layer.

## Changes

- Fixes the Inbox Source filter regression caused by RC15 and RC43/44 sharing one `StringVar` with incompatible values.
- The historical RC15 source-only filter now owns private state and is explicitly disabled in the V2 shell.
- Keeps one authoritative visible Source + Topic filter pair in Inbox.
- Shortens crowded Inbox actions so the primary merge workflow survives narrower logical window sizes.
- Adds `Ctrl+F` focus for Inbox keyword search and `Esc` to clear that search field.
- Replaces the fixed 1440x920 shell assumption with screen-bounded startup geometry and a visible bottom status bar.
- Keeps publication destinations visible by reserving minimum target-list height and reducing the media candidate table height.
- Makes explicit RC47 publication outcomes visible to the operator: `unknown` is no longer treated as an ordinary retryable error.
- Adds operator resolution actions for ambiguous external publication results: `Пост є` and `Поста немає`.
- `Пост є` records a durable successful outcome even when the remote id was lost after an ambiguous transport result.
- `Поста немає` keeps RC47 `confirmed_not_sent` semantics and is the only path that re-enables a safe retry.
- Immediate publication is blocked for a destination that still has an unresolved `unknown` outcome for the same material.
- Protects operator edits in the Editor: a new AI rewrite cannot silently replace text that differs from the last AI draft.
- Serializes active V2 legacy-Router execution and status reads so concurrent jobs cannot overwrite Router cooldown/model-health read-modify-write state.
- Adds RC48 regression tests and retains RC41-RC47 targeted gates.

## Preserved

- RC47 composition root, typed AI contracts, numbered V2 migrations and explicit publication outcomes.
- RC46 clean-import wrapper discovery.
- RC45 backup/recovery and Fact Guard/Anti-Slop safety gate.
- RC44 visible manual Source/Topic filter row.
- RC43 source-owned manual topics.
- RC42 Instagram multi-account behavior.
- RC41 Google Drive auth recovery.

## Deliberately deferred

- No full UI redesign.
- No DPI-aware process manifest yet; real DPI-awareness remains a separate later candidate after layout stabilization.
- No Backup format v2/staging restore yet.
- No DestinationRegistry/platform-adapter consolidation yet.
- No Ed25519 release manifest yet.
- No mass legacy RC/MRO deletion yet.

RC44 remains the synchronized canonical baseline until a newer candidate is manually validated and explicitly promoted.
