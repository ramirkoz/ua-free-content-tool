# UA FREE Content Tool 2.0.0-rc52

RC52 closes the publication/platform backend architecture milestone of the agreed Claude roadmap.

## Publication contracts

- Added typed `PublishPayload`, `PublishAttempt`, platform capabilities and auth states.
- Added `DestinationRegistry` as the single publication destination registry.
- Added `PublicationService` as the orchestration boundary for external writes.
- Ambiguous `UNKNOWN` outcomes are fail-closed and never automatically retried.
- Graceful shutdown stops accepting new external writes and waits for in-flight publication to reach a safe boundary.

## Platforms

The registry models Telegram, Facebook, Instagram multi-account destinations, Threads and LinkedIn behind one adapter contract.

Google Drive is explicitly a media/storage service and is rejected as a publication destination.

## Composition

`AppServices` now composes:
- database;
- configuration;
- AI gateway;
- maintenance;
- destination registry;
- publication service;
- Google Drive media service.

The RC52 publishing layer carries per-attempt donation policy in `PublishPayload`; it does not mutate donation module globals.

## Compatibility

Existing proven platform HTTP transports remain compatibility implementations behind the typed adapter boundary. RC52 does not add another versioned MainWindow/MRO layer.

## Acceptance

The dedicated Windows RC52 gate covers publication contracts plus retained RC41-RC51 gates, architecture invariants, signed portable packaging and a non-blocking repository-wide audit.
