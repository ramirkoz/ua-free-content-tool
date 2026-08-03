# Update a Working R8 FIX29 Installation to R8 FIX30 Without Losing Data

FIX30 is a program-only hotfix. It does not run a database migration and does not modify the current queue.

## What changed

- Shift-click selects a continuous range in Incoming and Queue views on Windows.
- English Ollama output is rejected and not saved.
- After an invalid first response, the model rewrites again from the original sources instead of translating its own unsupported text.
- Speculative or reflective phrases not supported by the materials are rejected.
- If two attempts fail to produce a Ukrainian, fact-grounded rewrite, the editor and queue remain unchanged.

## What remains unchanged

- SQLite schema version 7.
- Platform tokens, Google Drive connection, sources, and collected news.
- Editorial memory, manual merges, and exclusion rules.
- The complete queue, including package and target IDs, times, platforms, media, statuses, attempts, and remote IDs.
- The completed marker for the previous one-time queue conversion to the 900-character format.

## Update procedure

1. In FIX29, confirm that no package is currently publishing and that the current operation has completed.
2. Close FIX29 and verify in Task Manager that the EXE process has stopped.
3. Create a complete untouched backup of the working folder.
4. Create a second full copy for FIX30.
5. In the second copy, replace only `UA_FREE_Content_Tool.exe` and `_internal` from the program-only FIX30 update.
6. Do not delete or replace `Data`, `portable.flag`, `clean_start.flag`, `config.portable`, or `portable.key`.
7. After startup, verify queue integrity, Shift-click selection, and a test rewrite for an item not already in the queue.

Keep the original FIX29 copy until the first successful live FIX30 publication.
