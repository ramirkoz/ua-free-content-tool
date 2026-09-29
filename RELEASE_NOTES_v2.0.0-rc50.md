# UA FREE Content Tool 2.0.0-rc50

RC50 closes the agreed Claude architecture/UI reliability roadmap on top of RC45–RC49.

## Reliability and startup

- Keeps RC49 deferred Supervisor startup and indexed `articles(discovered_at)` query.
- Real Windows MainWindow smoke now constructs the full shell and refreshes the AI status path that failed in manual RC49 testing.
- AI service keeps one typed request/backend gateway while exposing a stable UI status/probe contract.
- Router state execution remains serialized without blocking OpenRouter/Agent.

## Data and publication safety

- Numbered migrations and explicit publication outcomes remain canonical.
- Backup contract v3 includes DB snapshot, durable sidecars and publication receipts.
- Normal backup does not contain portable credentials.
- Password-protected migration backup uses scrypt + AES-GCM for credentials.
- Unknown publication outcome stays fail-closed until explicit operator confirmation.
- Graceful publication shutdown from RC49 is preserved.

## Composition and destinations

- `AppServices` owns DB, configuration, AI gateway, destination registry and backup service.
- `DestinationRegistry` is the authoritative V2 destination identity/readiness view.
- Google Drive remains media/storage infrastructure, not a publication destination.

## UI/UX

- RC48 Source + Topic filter fixes, bottom status bar, adaptive geometry, unknown-outcome controls and manual rewrite protection are preserved.
- Windows per-monitor DPI awareness is enabled before Tk creates the first window.
- First-run Import / Fresh / Later flow and Ukrainian startup stages are preserved.

## Update security

- Automatic release discovery now requires an Ed25519-authenticated release manifest.
- Unsigned releases fail closed for automatic application.
- The portable embeds only the public verification key.
- Offline signing utility: `tools/sign_release_manifest.py`.
- The private release key is never stored in the repository or portable package.

## Manual acceptance required

Do not promote RC50 to CURRENT until the Windows portable has passed operator startup/import/UI/publication smoke on real data.
