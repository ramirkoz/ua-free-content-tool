# Portable Mode

UA FREE Content Tool stores the database, sources, queue, encrypted credentials, Google Drive refresh token, settings, local learning data, exclusion rules, and logs in the `Data` folder next to `UA_FREE_Content_Tool.exe`.

## Move the application to another computer

1. Close the application.
2. Confirm that no `UA_FREE_Content_Tool.exe` process remains.
3. Copy the **entire `UA_FREE_Content_Tool` folder**, not only the EXE.
4. Start the EXE from the copied folder on the new Windows computer.

`Data\config.portable` and `Data\portable.key` form one cryptographic pair. Do not delete, rename, or move them separately. Anyone with physical access to the complete portable folder may be able to access the stored credentials, so protect the folder accordingly.

Ollama and local model files are not included in the portable folder. Install Ollama and the selected model separately on the destination computer. A platform may also require reauthorization if it has revoked or expired its token.

## Updating to v1.1.3

Version 1.1.3 uses a new signed Python runtime package. It does not use the earlier PyInstaller `_internal` layout.

Recommended procedure:

1. Keep the blocked v1.1.2 executable in quarantine or remove it through Windows Security. Never restore or allow it.
2. Delete the downloaded v1.1.2 ZIP and the extracted v1.1.2 program folder.
3. Close the last trusted working version completely.
4. Copy its complete application folder to a backup location.
5. Extract v1.1.3 into a separate new folder.
6. Copy **only the complete trusted `Data` folder** from v1.1.1 or another known-good backup into the v1.1.3 folder.
7. Do not copy the v1.1.2 EXE, `_internal` directory, DLLs, Python files, or other runtime components.
8. Scan the extracted v1.1.3 folder with Microsoft Defender.
9. Start v1.1.3 and confirm that sources, settings, learning data, queue, and publication history are present.
10. Keep the known-good backup until the first successful live publication.

The database schema remains version 8. No database conversion is required from v1.1.0, v1.1.1, or v1.1.2 data, but only a trusted `Data` folder should be migrated.

Do not copy only `UA_FREE_Content_Tool.exe`. The EXE depends on the `DLLs`, `Lib`, `tcl`, `content_agent`, and signed Python runtime files shipped in the same release.

The release archive does not contain production tokens, configuration, SQLite files, logs, or queue data. The application creates `Data` on first launch if the folder is absent.

## Earlier v1.0.0 to v1.1.x database migration

Version 1.1.0 upgraded the SQLite schema from version 7 to version 8. The migration preserves:

- configured sources and incoming blocks;
- merged source relationships and approved text;
- publication batches and target statuses;
- attempts, errors, and remote IDs;
- editorial examples and topic feedback;
- permanent content exclusions;
- encrypted platform settings and credentials.

## Migration from legacy local data

On the first eligible launch, the application can migrate legacy data from:

```text
%LOCALAPPDATA%\UA_FREE_Content_Tool\data
```

The migration creates a verified SQLite snapshot and converts the previous machine-bound configuration into the portable encrypted format. The legacy folder is not deleted automatically.

An empty schema-only portable database created by a test launch is not treated as authoritative. Real legacy sources and settings can still be imported. A non-empty portable database is never overwritten automatically.

## Backups

Before every update:

1. Close the application and confirm the process has stopped.
2. Copy the complete application folder to a separate backup location.
3. Apply only the documented program update or move the complete trusted `Data` folder into a separately extracted new version.
4. Keep the previous working copy until the first successful live publication with the new version.

The in-application backup and learning export functions are useful additional safeguards, but they do not replace a complete offline copy of the portable folder before a version update.

Never upload a real working `Data` folder to GitHub or attach it to an issue.
