# UA FREE Content Tool v1.4.0-rc14

RC14 adds two editor-controlled Inbox composition tools without changing the database schema or resetting Data.

## Keyword merge search

- A new Inbox search accepts one or more keywords.
- Matching is local and deterministic: no AI request is used.
- Search checks the block title, every source title and the full source text.
- Every entered word must be present somewhere in the block, with Unicode case-insensitive matching.
- Results open in a dedicated window that contains only matching blocks.
- The editor can select several matches and merge them immediately.
- The first selected block is marked as the primary block and keeps its title/media/options under the existing safe merge rules.
- Approved/archived blocks are not offered because merge is a pre-publication operation.

## Edit an already merged block

- `Редагувати склад блоку` opens every source story inside one selected merged block.
- The editor can inspect the source/title/full text and select one or more wrongly merged stories.
- Removing a story from the block does not delete it from Data.
- Every removed story returns to Inbox as its own new one-story block.
- At least one story must remain in the original block.
- If the removed story owned the original canonical title, the remaining block is re-anchored to a remaining story title.
- Derived rewrite/fact-card/platform text and explosiveness analysis are reset/recomputed because the factual source set changed.
- Publication history or queued blocks are protected from membership changes.
- When learning is enabled, manual removals are recorded as `not_related` feedback.

## Preserved

- RC13 exact per-destination schedules remain intact.
- RC12 Sources health-column compatibility remains intact.
- RC11 Inbox sorting/merged-block visibility remains intact.
- RC10 `ОПУБЛІКУВАТИ ЗАРАЗ` remains isolated from the normal queue.
- No database schema migration and no Data reset.
