# UA FREE Content Tool 2.0.0-rc44

RC44 is a focused UI correction on top of RC43 manual source topics.

## Inbox topic filter visibility

- Keeps the RC43 manual topic model unchanged: topics remain operator-owned source metadata.
- Keeps the existing source-owned topic values in Inbox unchanged.
- Moves the Inbox filters to a dedicated full-width row directly above the news table.
- Shows both `Джерело` and `Тема` dropdowns at the same time instead of packing them into the already crowded keyword-search toolbar.
- Source and topic filters can still be combined.
- `Скинути фільтри` clears both filters.

## Compatibility

- No database migration is required beyond RC43.
- Existing topic catalog and source-to-topic assignments are preserved.
- Collection, grouping, rewriting, publication, Instagram and Google Drive logic are unchanged.

## Regression intent

RC44 exists because RC43 contained the topic-filter logic but its controls could be clipped out of the visible Inbox toolbar. RC44 protects the filter layout separately from the filtering logic.
