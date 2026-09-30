# UA FREE Content Tool 2.0.0-rc52

RC52 closes the **publication/platform backend architecture** milestone of the Claude roadmap.

## Platform backend

- Adds typed `PlatformAdapter`, `Authenticator`, `PlatformCapabilities`, `PublishPayload`, `Checkpoint` and `PlatformPublishResult` contracts.
- Adds a single `DestinationRegistry` for Telegram, Instagram, Facebook, Threads and LinkedIn.
- Separates platform auth/readiness state from publication execution.
- Preserves Instagram multi-account destination keys and target isolation.
- Routes the active V14 publication worker through `PublishingService` / `PlatformPublisherFactory` rather than direct platform selection in the worker.

## Publication outcomes and shutdown

- Adapter results use the canonical `PublicationOutcome` contract.
- Ambiguous/untyped transport failures fail closed as `unknown`.
- `unknown` is never marked retryable by the RC52 adapter boundary.
- `PublishingService` blocks new writes during shutdown and exposes a bounded wait for the current external write to reach a safe boundary.
- Existing operator reconciliation (`Пост є / Поста немає`) remains the required path for unresolved unknown outcomes.

## Google Drive boundary

- Google Drive is composed as `GoogleDriveMediaService`.
- Drive is deliberately absent from `DestinationRegistry` publication adapters.
- Media/storage lifecycle remains independent from publisher selection.

## Composition

`AppServices` now composes:
- database;
- config;
- AI gateway;
- maintenance;
- publishing;
- media service.

No `*_rc52_window.py` runtime layer is added.

## Acceptance

RC52 has a dedicated Windows gate covering:
- platform registry/adapters/auth state;
- explicit sent/failed/unknown outcomes;
- `unknown` no-auto-retry semantics;
- worker-compatible publication factory facade;
- graceful shutdown safe boundary;
- Drive media-service separation;
- `AppServices` publication/media composition;
- retained RC41–RC51 release gates;
- signed Windows portable build/package.

The repository-wide suite remains an explicit audit, not a hidden green claim. Historical failures are retained as debt until classified/fixed rather than weakened to manufacture a pass.
