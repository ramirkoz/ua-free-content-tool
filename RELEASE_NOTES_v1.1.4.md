# UA FREE Content Tool v1.1.4

This stabilization release fixes the displayed application version, adds typed sorting to the main tables, and separates current news potential from the historical performance forecast in Inbox.

## What changed

### Correct application version

- The window title no longer contains a hard-coded `v1.1.2` value.
- The displayed version is loaded from `PUBLIC_VERSION.txt`.
- The release package, version files, GitHub tag and visible application title now use the same `1.1.4` value.
- If the version resource is unavailable or malformed, the application falls back safely instead of failing during startup.

### Sorting by table columns

The main tables can now be sorted by clicking a column heading:

- Sources;
- Inbox;
- Publication Queue;
- Publication History.

The first click sorts in ascending order. A second click on the same heading reverses the order. The active heading displays `▲` or `▼`.

Sorting is type-aware:

- block, batch, source and count columns are treated as numbers;
- values such as `39/100` and `68/100` are sorted by their numeric score;
- ISO and visible date/time values are sorted chronologically;
- text is sorted case-insensitively;
- empty values and `—` remain at the end.

The selected sorting remains active when the corresponding list is refreshed during the current application session.

### Clearer potential indicators in Inbox

The former `Virality` column has been replaced with two separate columns:

- **Current potential** shows the latest saved current score based on freshness, source count, mention velocity, topic impact, media and available Threads activity.
- **Historical forecast** shows the latest saved relative prediction based on the installation's own previous publication metrics.

A historical forecast is displayed as a score and confidence, for example:

`68/100 · 54%`

If the prediction has not been calculated, the table shows `—`. If fewer than five suitable historical publications with metrics are available, it shows that there is insufficient data instead of presenting an invented zero.

The Inbox does not recalculate thousands of rows during every five-minute source refresh. It displays the most recently saved result produced by **Evaluate potential**.

## Data compatibility

- Database schema remains version 8.
- No migration of `Data` is required.
- Existing sources, tokens, queue packages, publication history, metrics, exclusions and editorial learning data remain compatible.
- The release does not rewrite or reschedule existing queue items.

## Validation

Windows CI passed on Python 3.11, 3.12 and 3.13:

- `compileall`: PASS;
- `pytest`: 258 passed;
- entrypoint import validation: PASS;
- `import content_agent.main`: PASS.

The first CI run detected an unsafe attempt to parse a score such as `39/100` as an ISO date. Date parsing was made fail-safe and the complete matrix passed after the correction.

The release workflow additionally validates the signed Python Software Foundation runtime, performs a portable startup smoke test, scans both the extracted application and final ZIP with Microsoft Defender, validates ZIP paths and CRC, and rejects runtime data or unexpected executables.

## Updating from v1.1.3

1. Fully close the old application and verify that `UA_FREE_Content_Tool.exe` is not running in Task Manager.
2. Make a backup copy of the entire current application folder.
3. Extract v1.1.4 into a separate new folder.
4. Replace the new empty `Data` folder with the complete `Data` folder from the previous working installation.
5. Do not copy the old EXE, runtime libraries or `_internal` directory.
6. Start `UA_FREE_Content_Tool.exe`.
7. Confirm that the title shows `v1.1.4`, the Inbox contains both potential columns, and heading clicks sort the tables.
8. Keep the previous working copy until the first successful live publication.

## Operational limitations

- Ollama and a compatible local model are installed separately.
- Platform API behavior still depends on the operator's tokens, permissions, pages, profiles and channel access.
- Historical forecasting requires at least five prior publications with usable collected metrics.
- Telegram Bot API does not provide the same post-publication metric coverage as Facebook or Threads.
