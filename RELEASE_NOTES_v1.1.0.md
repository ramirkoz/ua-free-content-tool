# UA FREE Content Tool v1.1.0

Version 1.1.0 expands the validated v1.0.0 Windows application without changing its local-first editorial model or replacing human approval with automatic decisions.

## Main changes

### Ukrainian and English modes

- The application interface can be switched between Ukrainian and English in Settings.
- The selected language also controls Ollama prompts, repair prompts, compression prompts, fact cards, and final rewrite output.
- Ukrainian and English editorial examples are stored and ranked separately.
- Visible interface labels, status messages, modal dialogs, file dialogs, queue-migration messages, and connection diagnostics are localized.

### Focused topic merging

- Topic search now opens a separate candidate window instead of marking rows across the full Inbox.
- The editor can review likely matches, accept or reject candidates, and merge only after explicit confirmation.
- Rejected candidate pairs and confirmed manual merges can be recorded in the local learning store.

### Inbox and queue usability

- Added a visible vertical scrollbar and keyboard navigation with Page Up, Page Down, Home, and End.
- Preserved list position after refreshes and actions.
- Added clearer one-row actions and light-green highlighting for approved rows.
- Removed the confusing visible “in work” status.
- Kept simple deletion separate from the permanent “remember and exclude” action.

### Local learning

- Added local event recording for generated rewrites, approved final texts, manual merges, rejected topic candidates, permanent exclusions, and restored exclusions.
- Added learning statistics, configurable prompt-example limits, export, import, and history clearing.
- Learning exports now include permanent content exclusions and can restore them during import.
- No learning data is uploaded to a cloud training service.

### Platform settings

- Facebook and Threads now use separate App IDs and App Secrets.
- Existing legacy Meta fields remain migratable for compatibility.
- Platform publication targets, queue state, attempts, remote IDs, and credentials remain preserved through the schema migration.

## Data migration

- Database schema version is upgraded from 7 to 8 automatically.
- Existing sources, incoming blocks, editorial text, local memory, exclusion rules, publication queue, target statuses, attempts, and remote IDs are preserved.
- Ukrainian and English learning signatures are language-scoped to avoid cross-language collisions.
- Back up the complete portable application folder before updating.

## Validation completed before release preparation

- Python compilation: PASS.
- Automated tests on Windows with Python 3.12: 238 passed.
- Entrypoint import check: PASS.
- `import content_agent.main`: PASS.
- Visible localization audit: 0 untranslated Ukrainian literals in the audited interface windows.
- Legacy regression compatibility: PASS.

The final public release remains subject to the repository’s Python 3.11, 3.12, and 3.13 Windows CI matrix and portable PyInstaller build gate. Live publication still depends on current platform tokens, roles, API permissions, account state, and network conditions.

## Updating from v1.0.0

1. Close UA FREE Content Tool completely.
2. Confirm in Task Manager that `UA_FREE_Content_Tool.exe` is no longer running.
3. Copy the complete existing application folder to a backup location.
4. Extract v1.1.0 into a separate folder.
5. Copy the complete existing `Data` folder into the new portable folder.
6. Start v1.1.0 and confirm that sources, settings, learning data, and the publication queue are present.
7. Do not delete the v1.0.0 backup until the first successful live publication from v1.1.0.

Do not copy only the EXE. The application build includes the `_internal` directory and version-specific runtime files.

## Operational requirements

- Windows 10 or Windows 11.
- Ollama and a compatible local model installed separately.
- Internet access for collection and platform APIs.
- Current credentials and permissions for each configured platform.
- A Google Cloud OAuth client of type Desktop app when Google Drive media is used.

Real tokens, application secrets, SQLite files, logs, and the working `Data` folder are not included in release assets.
