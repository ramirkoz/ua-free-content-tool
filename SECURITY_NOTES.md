# Security Policy and Operational Boundaries

## Supported version

Security fixes are currently provided for the latest public release only.

## Windows release integrity

Starting with v1.1.3, the Windows portable build no longer uses a generated PyInstaller launcher. The visible `UA_FREE_Content_Tool.exe` is an unchanged official `pythonw.exe` binary whose Authenticode signature must validate to the Python Software Foundation.

Every Windows release must pass all of these gates before publication:

- the complete automated test suite;
- isolated runtime import and Tk startup checks;
- a real GUI startup smoke test;
- verification of the launcher Authenticode signature and signer;
- updated Microsoft Defender definitions;
- a Microsoft Defender custom scan of the extracted runtime;
- a second Defender scan of the final ZIP archive;
- ZIP CRC, duplicate-path, path-traversal, runtime-data, and diagnostic-file checks;
- SHA-256 checksums published with the release.

A clean scan is evidence for the exact scanned build and Defender signature version, not an absolute guarantee against every possible threat. Users should keep Defender enabled and scan the downloaded archive locally before first use.

The v1.1.2 Windows binary was withdrawn after a critical Defender detection and must not be restored, allowed, or added to exclusions.

## Never publish these files

Do not attach or commit a real working `Data` folder. In portable mode it may contain:

- `config.portable` with encrypted credentials;
- `portable.key`, which can decrypt that configuration;
- the SQLite database with sources, queue history, and editorial data;
- private Google Drive identifiers and operational logs.

Do not publish access tokens, app secrets, OAuth client secrets, refresh tokens, private Drive links, or screenshots containing secrets.

## Local secret storage

- Portable configuration is encrypted with AES-GCM.
- The portable encryption key is stored next to the encrypted configuration so the full folder can move between computers.
- This portability means physical access to the complete application folder may permit access to stored credentials.
- Tokens are not stored in SQLite.
- Secret values are masked in the interface and removed from normal error output.

## Network and media controls

- External URLs pass through application network safeguards.
- Private and non-global destinations are rejected for external fetches.
- Google Drive files are downloaded through OAuth.
- Temporary public access is created only when Threads requires a public media URL.
- The application revokes only the permission it created.
- A Drive file is deleted only after every selected publication succeeds.

## Queue safety

- SQLite uses WAL, foreign keys, and full synchronous mode.
- Publication targets are processed sequentially.
- Partial retry does not repeat successful targets.
- A second application process is blocked by an OS lock.
- Queue and database migrations are tested for preservation of pending items, target statuses, attempts, and remote IDs.

## Reporting a vulnerability

Send a minimal report to `kozyriev@uafree.org` or use a private maintainer contact channel.

Include:

- affected version;
- reproduction steps;
- security impact;
- sanitized evidence.

Remove all real credentials and personal data.
