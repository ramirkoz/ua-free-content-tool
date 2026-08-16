from __future__ import annotations

from . import ai_router_v1_2_1 as router


ACTIVE_AI_PROVIDERS: tuple[str, ...] = (
    "codex",
    "gemini",
    "nvidia",
    "groq",
    "cloudflare",
    "local",
)


def activate_ai_providers() -> None:
    """Keep only providers that are part of the supported v1.2.1 production chain."""
    active = set(ACTIVE_AI_PROVIDERS)
    kept = [slot for slot in router.MODEL_SLOTS if slot.provider in active]
    router.MODEL_SLOTS = tuple(
        router.AIModelSlot(index, slot.provider, slot.model, slot.label, slot.family)
        for index, slot in enumerate(kept, start=1)
    )


activate_ai_providers()
