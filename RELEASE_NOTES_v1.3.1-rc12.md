# UA FREE Content Tool v1.3.1-rc12

## Stability fix: rewrite + Threads reconciliation

- Interactive rewrite no longer scans the full Rowboat Markdown graph on every click.
- Rewrite preparation uses a bounded 12k-character similarity query and at most 300 recent editorial examples, preventing 50+ source groups from spending the whole UI timeout before AI starts.
- Added rewrite preparation milestones to logs for deterministic diagnosis.
- Threads code 24 / subcode 4279009 reconciliation now works for one-part posts, multi-part chains, single media and galleries.
- Reconciliation retries the recent-post lookup briefly to cover Threads eventual consistency, requires a unique exact normalized-text match, then resumes remaining chain parts without reposting the root.
- If the root and all text parts are already published but a donation reply fails, the root publication stays successful and donation failure is recorded separately.
- No database schema change; existing RC11 Data remains compatible.
