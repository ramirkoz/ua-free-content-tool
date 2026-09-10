from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable


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


Validator = Callable[[str], object]
