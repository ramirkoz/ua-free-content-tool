# UA FREE Content Tool v1.4.0-rc11

RC11 stabilizes the **«Вхідні»** list after source-count sorting, background collection and manual merges.

## Inbox ordering and visibility

- Inbox no longer applies the historical 200-row database cap before the user's visual sort. Current RC11 reads the full matching working set first, so sorting by **«Джерел»** is a sort of the actual Inbox rather than a recency-truncated subset.
- A freshly merged block can no longer disappear merely because the source articles inside it carry older publication timestamps and fell outside the old 200-row preselection.
- Inbox now has one authoritative sorting engine. The older generic Treeview sort is explicitly disabled for the Inbox; the existing Inbox multi-sort remains authoritative.
- Every Inbox rebuild reapplies the saved sort immediately and once again after Tk finishes the pending redraw turn. A collector/merge refresh therefore cannot leave newly returned rows appended in an order such as `8, 8, 6, 1, 5, 5` while **«Джерел»** is sorted descending.
- Selection, focus, topic classification and the existing multi-sort UX are preserved.

## Preserved from RC10

- **«ОПУБЛІКУВАТИ ЗАРАЗ»** remains isolated from normal destination schedules and still records outcomes in Publication History.
- Existing Data, profiles, source configuration, queues, media references, learning history and destination schedules are preserved.
- No database schema migration and no Data reset.
