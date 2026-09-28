# UA FREE Content Tool 2.0.0-rc43

RC43 replaces unreliable per-news automatic topic assignment with an operator-owned source topic catalog.

## Manual topics

- Adds a durable editable list of arbitrary manual topics.
- Each source is assigned exactly one selected topic from that list.
- New and edited sources require an explicit topic selection.
- Topic assignment is stored in Data and survives restart/backup/upgrade.
- Existing RC42 sources upgrade safely and start as unassigned until the operator selects a topic.
- Renaming a topic updates the visible topic for all linked sources/news without reclassification.
- Deleting a topic only unassigns linked sources; it never deletes collected news.

## Sources

- Sources table now shows the fixed topic.
- Add/edit source dialogs use a topic dropdown.
- A dedicated `Теми…` manager adds, renames and deletes topics.

## Inbox

- The visible `Тема` column is derived from the member news sources, not from the historical automatic classifier.
- Adds independent `Джерело` and `Тема` filters; they may be combined.
- The old per-news topic double-click override is retired. Topic ownership now lives at source level.

## Compatibility

- RC42 Instagram multi-account destination behavior is unchanged.
- RC41 Google Drive auth recovery is unchanged.
- The historical automatic topic-classifier code remains only as compatibility/history; the active RC43 V2 UI no longer treats it as authoritative.
- Manual topics are included in the clean-import durable-state contract for future upgrades.

## Test state

Focused RC43 manual-topic regressions are expected to pass independently of the repository-wide historical test debt. The repository-wide suite still contains the pre-existing RC42 failures and is not claimed clean by this release candidate.
