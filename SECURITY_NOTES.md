# Security Policy and Operational Boundaries

## Supported version

Security fixes are currently provided for the latest public release only.

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
