# UA FREE Content Tool 2.0.0-rc57

RC57 is a focused Inbox stability hotfix after live RC56 acceptance.

- preserves the operator-selected Inbox sort across delete, merge, refresh, filter changes and restart;
- persists sort column/direction in portable Data state;
- reapplies sort after rebuilding the Treeview instead of silently reverting to database recency;
- restores the viewport using surviving row anchors after delete/merge, with yview only as a last fallback;
- keeps the RC56 search/media/Anti-Slop fixes unchanged;
- full repository suite is a blocking release gate.
