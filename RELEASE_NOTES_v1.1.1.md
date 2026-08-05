# UA FREE Content Tool v1.1.1

Patch release focused on the real editorial workflow after the first v1.1.0 data migration.

## Main fixes

- Raw or truncated Ollama JSON is no longer shown as the headline, fact card, or publication text.
- The rewrite prompt now uses a simple marker protocol that small local models follow more reliably.
- A repaired model response supplies its own fact card instead of reusing the rejected first response.
- Permanent content exclusions can be inspected, deactivated individually, or cleared in bulk.
- Approved stories older than 24 hours no longer clutter the active Inbox. Recent or still-queued approved stories remain reachable.

## Publication History

A separate **Publication History** tab now appears before **Settings**. It shows:

- rewritten headline;
- actual publication date and time in Kyiv;
- destination networks;
- complete or partial publication status;
- stored post links where the platform exposes them;
- available views, reactions, reposts/shares, and comments/replies.

Metrics are collected only on explicit refresh and are stored locally. Unsupported or permission-restricted metrics are shown as limitations instead of failing the application.

## Platform metric coverage

- Facebook Pages: reactions, comments, shares, permalink.
- Threads: views, likes, replies, reposts, quotes, shares with `threads_manage_insights`.
- LinkedIn: likes/comments only when the application has approved Social Actions read access.
- Telegram: direct public-channel link where possible; Bot API engagement counts are unavailable.

## Data preservation

v1.1.1 uses the same schema 8 database as v1.1.0. Copy the complete existing `Data` folder into the new portable application folder while the old application is closed. Do not copy only the EXE.

## Validation target

The release is gated by Windows tests on Python 3.11, 3.12, and 3.13, a PyInstaller portable build, executable startup smoke test, ZIP integrity/path checks, and secret-file scanning.
