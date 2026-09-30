from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, Protocol, runtime_checkable


class AITask(StrEnum):
    TOPIC = "topic"
    DUPLICATE = "duplicate"
    CLASSIFY = "classify"
    REWRITE = "rewrite"
    FACT = "fact"
    QUALITY = "quality"
    SUPERVISOR = "supervisor"
    GENERIC = "generic"


class QualityTier(StrEnum):
    FAST_CHEAP = "fast_cheap"
    BALANCED = "balanced"
    STRONG = "strong"
    PREMIUM = "premium"


class AIErrorKind(StrEnum):
    """Stable failure classes shared by every active AI backend."""

    AUTH = "auth"
    QUOTA = "quota"
    CONFIGURATION = "configuration"
    MODEL = "model"
    TEMPORARY = "temporary"
    BAD_RESPONSE = "bad_response"
    VALIDATION = "validation"
    REQUEST_TOO_LARGE = "request_too_large"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


Validator = Callable[[str], object]


@dataclass(frozen=True, slots=True)
class AIRequest:
    prompt: str
    validator: Validator | None = None
    max_output_tokens: int = 4096
    local_prompt: str | None = None
    local_max_output_tokens: int | None = None
    local_timeout_seconds: int = 120
    local_repair: bool = True
    cloud_timeout_seconds: int = 120
    task_timeout_seconds: int | None = None
    skip_providers: tuple[str, ...] = ()
    skip_models: tuple[str, ...] = ()
    suppress_provider_on_quota: bool = False
    cancel_event: object | None = None
    task: AITask = AITask.GENERIC
    quality_tier: QualityTier = QualityTier.BALANCED


@dataclass(frozen=True, slots=True)
class UnifiedAIResult:
    text: str
    backend: str
    provider: str
    model: str
    label: str
    attempted: tuple[str, ...] = ()
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0


@runtime_checkable
class AIBackend(Protocol):
    name: str

    def run(self, request: AIRequest) -> UnifiedAIResult:
        ...


__all__ = [
    "AIBackend",
    "AIErrorKind",
    "AIRequest",
    "AITask",
    "QualityTier",
    "UnifiedAIResult",
    "Validator",
]
