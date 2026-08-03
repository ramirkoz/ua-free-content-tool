# Portable Mode

UA FREE Content Tool stores the database, sources, queue, encrypted credentials, Google Drive refresh token, settings, and logs in the `Data` folder next to `UA_FREE_Content_Tool.exe`.

## Move the application to another computer

1. Close the application.
2. Confirm that no `UA_FREE_Content_Tool.exe` process remains.
3. Copy the **entire `UA_FREE_Content_Tool` folder**, not only the EXE.
4. Start the EXE from the copied folder on the new Windows computer.

`Data\config.portable` and `Data\portable.key` form one cryptographic pair. Do not delete, rename, or move them separately. Anyone with physical access to the complete portable folder may be able to access the stored credentials, so protect the folder accordingly.

Ollama and local model files are not included in the portable folder. Install Ollama and the selected model separately on the destination computer. A platform may also require reauthorization if it has revoked or expired its token.

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
3. Apply only the documented program update.
4. Keep the previous working copy until the first successful live publication with the new version.

Never upload a real working `Data` folder to GitHub or attach it to an issue.
