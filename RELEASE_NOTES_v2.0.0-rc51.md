# UA FREE Content Tool 2.0.0-rc51

RC51 is the **AI final architecture** milestone of the agreed Claude roadmap.

## What changed

- `AIRequest -> AIGateway -> AIBackend -> UnifiedAIResult` is the canonical active contract.
- Added explicit shared AI error taxonomy: auth, quota, configuration, model, temporary, bad response, validation, request-too-large, timeout, cancelled.
- Removed `content_agent/v2/ai/direct_router_runtime.py` and its import-time mutation of the legacy Router.
- Removed package-import rebinding of `service.backend_status`, `service.test_active_backend`, and `usage.usage_summary`.
- RC49 UI compatibility is retained as ordinary function contracts/wrappers, not runtime monkey-patching.
- Router execution is behind `CanonicalRouterBackend` and remains serialized around its durable cooldown/model-health state.
- Pre/post execution cancellation is fail-closed across the gateway contract.
- Explicit backend probes no longer change the selected backend.
- Usage budget/remaining is now a native `usage_summary()` contract.
- `AppServices.ai` remains the single composed `AIGateway` entrypoint.
- No new version-numbered runtime UI layer is added.

## Deliberately not included

RC52 owns publication/platform backend architecture (`DestinationRegistry`, `PlatformAdapter`, auth contracts). RC53 owns Inbox/shared UI components and TabController extraction. RC54 owns full platform/data UI and DPI hardening. RC55 owns final consolidation/security/full-suite closure.

## Acceptance

RC51 has a dedicated Windows gate plus retained RC41-RC50 regressions and portable packaging. Repository-wide pytest remains an explicit audit until the historical suite debt is reconciled rather than hidden.
