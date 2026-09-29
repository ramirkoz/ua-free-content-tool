# UA FREE Content Tool 2.0.0-rc50

RC50 closes the reliability, architecture and UI/UX roadmap reviewed for the RC44–RC49 line while preserving the Windows portable / Tkinter / SQLite product model.

## Runtime and AI

- Fix the RC49 startup regression caused by the old UI calling the new `backend_status()` contract with positional arguments.
- Align all active AI UI calls with the typed V2 service contract, including explicit backend probes and OpenRouter usage reporting.
- Remove the active `direct_router_runtime` monkey-patch bridge. Current provider recovery/fallback transport is owned directly by `ai_router.py` through `v2.ai.provider_api`.
- Keep one typed AI request/backend gateway and the mandatory Fact Guard → sanitize → Anti-Slop acceptance path.
- Preserve bounded timeout/cancel/skip-provider semantics and Router state serialization.

## Composition and services

- Expand `AppServices` into the active composition root for database, AI, destination registry, collection, publishing and maintenance.
- Compose the final active publication factory/worker through the publishing service instead of allowing the final runtime owner to be selected by an RC-numbered UI layer.
- Add stable `CollectionService`, `PublishingService`, `MaintenanceService`, `DestinationRegistry`, publisher/auth adapter contracts and a dedicated Google Drive media-service role.

## Storage, migrations and maintenance

- Move manual source-topic schema ownership into numbered migration `0011_manual_source_topics`.
- Keep publication outcome migration `0009` and `articles(discovered_at)` index migration `0010`.
- Replace the process-wide “one SQLite connection at a time” lock with a shared/exclusive maintenance gate: normal SQLite connections can coexist, destructive backup/import remains exclusive.
- Use schema-3 backup contract from the active UI: DB snapshot + durable state + publication receipts + manifest.
- Normal backups do not contain portable credentials.
- Explicit migration backups encrypt credentials with scrypt + AES-GCM and a user password.
- Restore is staged, validated, safety-backed-up and closes the application after success instead of hot-reloading stale runtime objects.

## Publication and platforms

- Preserve explicit target outcomes: `not_attempted`, `sent`, `failed_known`, `unknown`, `confirmed_not_sent`.
- Unknown external outcomes remain fail-closed until the operator confirms “Пост є” or “Поста немає”.
- Keep graceful publication shutdown and publication receipts.
- Add a unified Platforms view backed by `DestinationRegistry`; Google Drive is shown as media/storage rather than a publisher.

## UI/UX

- Keep the single authoritative Source + Topic Inbox filter and indexed SQL predicate for manual topic/source filtering.
- Keep the always-visible bottom status bar and adaptive main window layout.
- Add stable `StatusBar`, `FilterBar`, `ActionBar`, `PublicationStatus` component boundaries and an `InboxTabController` without a new RC-numbered MainWindow subclass.
- Add dedicated `Дані й backup` and `Платформи` tabs.
- Rename Supervisor surface to `Стан системи`.
- Enable Windows per-monitor DPI awareness before Tk is created.
- Keep manual-edit protection before AI rewrite, keyboard search flow and safe unknown-publication controls.

## Signed updates

- Add Ed25519-signed release manifest verification with an embedded project public key.
- Auto-update candidates now require portable asset + signed manifest + signature.
- Signed manifest binds version, asset name, SHA-256, minimum updater version and rollback version.
- Unsigned or invalidly signed releases fail closed.
- Add offline signing tool; private release key is never stored in repo, portable Data or release assets.

## Validation

- Add full V2 Tk startup/UI smoke regression that builds the real active window and refreshes the AI status path.
- Add architecture/reliability tests for AI contract, signed manifests, maintenance concurrency, composition root, destination registry, numbered migrations, no active direct-router monkey-patch and no new RC50 window layer.
- Existing RC41–RC49 regression gates remain part of the RC50 Windows gate.

RC50 remains a manual-test candidate until live operator acceptance. ProductVault/Drive CURRENT must not be promoted before that acceptance.
