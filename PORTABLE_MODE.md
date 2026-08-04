# Portable Mode

UA FREE Content Tool stores the database, sources, queue, encrypted credentials, Google Drive refresh token, settings, local learning data, exclusion rules, and logs in the `Data` folder next to `UA_FREE_Content_Tool.exe`.

## Move the application to another computer

1. Close the application.
2. Confirm that no `UA_FREE_Content_Tool.exe` process remains.
3. Copy the **entire `UA_FREE_Content_Tool` folder**, not only the EXE.
4. Start the EXE from the copied folder on the new Windows computer.

`Data\config.portable` and `Data\portable.key` form one cryptographic pair. Do not delete, rename, or move them separately. Anyone with physical access to the complete portable folder may be able to access the stored credentials, so protect the folder accordingly.

Ollama and local model files are not included in the portable folder. Install Ollama and the selected model separately on the destination computer. A platform may also require reauthorization if it has revoked or expired its token.

## Updating from v1.0.0 to v1.1.0

Version 1.1.0 upgrades the SQLite schema from version 7 to version 8. The migration preserves:

- configured sources and incoming blocks;
- merged source relationships and approved text;
- publication batches and target statuses;
- attempts, errors, and remote IDs;
- editorial examples and topic feedback;
- permanent content exclusions;
- encrypted platform settings and credentials.

Recommended procedure:

1. Close v1.0.0 completely.
2. Copy the complete v1.0.0 application folder to a backup location.
3. Extract v1.1.0 into a separate folder.
4. Copy the complete v1.0.0 `Data` folder into the v1.1.0 portable application folder.
5. Start v1.1.0 and allow the schema migration to finish.
6. Confirm that sources, settings, learning data, and publication queue are present.
7. Keep the v1.0.0 backup until the first successful live publication from v1.1.0.

Do not copy only `UA_FREE_Content_Tool.exe`. The `_internal` directory belongs to the same build and must be replaced together with the EXE.

The v1.1.0 release archive contains an empty `Data` directory. It does not contain production tokens, configuration, SQLite files, logs, or queue data.

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
3. Apply only the documented program update or move the complete `Data` folder into a separately extracted new version.
4. Keep the previous working copy until the first successful live publication with the new version.

The in-application backup and learning export functions are useful additional safeguards, but they do not replace a complete offline copy of the portable folder before a version update.

Never upload a real working `Data` folder to GitHub or attach it to an issue.
