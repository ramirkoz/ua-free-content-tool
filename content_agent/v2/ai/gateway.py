from __future__ import annotations

from .contracts import AIRequest, UnifiedAIResult


class AIGateway:
    """Stable V2 AI entry point used by the application composition root."""

    def run(self, request: AIRequest) -> UnifiedAIResult:
        from .service import execute_request

        return execute_request(request)

    def execute(self, prompt: str, **kwargs) -> UnifiedAIResult:
        from .service import execute

        return execute(prompt, **kwargs)


__all__ = ["AIGateway"]
