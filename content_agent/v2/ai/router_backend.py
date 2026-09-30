from __future__ import annotations

from .contracts import AIRequest, UnifiedAIResult


class CanonicalRouterBackend:
    """Typed V2 boundary around the retained multi-provider router engine.

    RC51 removes runtime monkey-patching. The historical router remains the routing
    engine until its internals are retired, but it is now invoked only through this
    explicit AIBackend contract and never mutated at package import time.
    """

    name = "router"

    def run(self, request: AIRequest) -> UnifiedAIResult:
        from ... import ai_router as legacy

        result = legacy.run_ai_router(
            request.prompt,
            validator=request.validator,
            max_output_tokens=request.max_output_tokens,
            local_prompt=request.local_prompt,
            local_max_output_tokens=request.local_max_output_tokens,
            local_timeout_seconds=request.local_timeout_seconds,
            local_repair=request.local_repair,
            cloud_timeout_seconds=request.cloud_timeout_seconds,
            task_timeout_seconds=request.task_timeout_seconds,
            skip_providers=request.skip_providers,
            skip_models=request.skip_models,
            suppress_provider_on_quota=request.suppress_provider_on_quota,
            cancel_event=request.cancel_event,
        )
        return UnifiedAIResult(
            text=str(result.text or ""),
            backend="router",
            provider=str(result.provider or "router"),
            model=str(result.model or ""),
            label=str(result.label or "AI Router"),
            attempted=tuple(result.attempted or ()),
        )


__all__ = ["CanonicalRouterBackend"]
