from __future__ import annotations

"""Runtime bridge that upgrades the stable RC30 direct router without duplicating it.

The legacy router still owns secrets, route scoring, local fallback and compatibility
contracts.  V2 replaces only direct provider transport/model metadata with the
provider-recovery layer proven in Telegram Autopilot RC48.
"""

import logging
import threading

from .provider_api import ProviderAPIError, gemini_generate, openai_compatible_chat

logger = logging.getLogger("content_agent.v2.direct_router")
_LOCK = threading.Lock()
_INSTALLED = False


def install_direct_router_runtime() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    with _LOCK:
        if _INSTALLED:
            return
        from ... import ai_router as legacy

        # Keep the public RC30 router contract while using the reviewed current
        # production model generation.  Groq 20B/Flash-Lite fallbacks live inside
        # provider_api and therefore do not need extra public slots.
        legacy.MODEL_SLOTS = (
            legacy.AIModelSlot(1, "codex", "codex-chatgpt", "Codex / ChatGPT", "codex"),
            legacy.AIModelSlot(2, "gemini", "gemini-3.5-flash", "Gemini 3.5 Flash / Google", "gemini"),
            legacy.AIModelSlot(3, "nvidia", "nvidia/nemotron-3-ultra-550b-a55b", "Nemotron 3 Ultra 550B / NVIDIA"),
            legacy.AIModelSlot(4, "nvidia", "nvidia/nemotron-3-super-120b-a12b", "Nemotron 3 Super 120B / NVIDIA"),
            legacy.AIModelSlot(5, "groq", "openai/gpt-oss-120b", "GPT-OSS 120B / Groq"),
            legacy.AIModelSlot(6, "groq", "qwen/qwen3.8-27b", "Qwen 3.8 27B / Groq"),
            legacy.AIModelSlot(7, "cloudflare", "@cf/nvidia/nemotron-3-120b-a12b", "Nemotron 3 120B / Cloudflare"),
            legacy.AIModelSlot(8, "cloudflare", "@cf/zai-org/glm-4.7-flash", "GLM-4.7 Flash / Cloudflare"),
            legacy.AIModelSlot(9, "local", "local-model", "Локальний AI · Ollama → llama.cpp", "local"),
        )

        def wrap(exc: ProviderAPIError):
            return legacy.AIModelError(
                str(exc),
                kind=str(getattr(exc, "kind", "temporary") or "temporary"),
                retry_after=getattr(exc, "retry_after", None),
            )

        def openai_call(slot, cfg, prompt: str, *, max_output_tokens: int, timeout_seconds: int) -> str:
            try:
                if slot.provider == "nvidia":
                    api_key = cfg.nvidia_api_key
                    account_id = ""
                elif slot.provider == "groq":
                    api_key = cfg.groq_api_key
                    account_id = ""
                elif slot.provider == "cloudflare":
                    api_key = cfg.cloudflare_api_token
                    account_id = cfg.cloudflare_account_id
                else:
                    raise legacy.AIModelError("Невідомий OpenAI-compatible провайдер.", kind="configuration")
                reply = openai_compatible_chat(
                    slot.provider,
                    model=slot.model,
                    api_key=api_key,
                    account_id=account_id,
                    prompt=prompt,
                    max_output_tokens=max_output_tokens,
                    timeout_seconds=timeout_seconds,
                )
                if reply.model and reply.model != slot.model:
                    logger.info(
                        "Direct provider fallback provider=%s requested=%s used=%s",
                        slot.provider, slot.model, reply.model,
                    )
                return reply.text
            except ProviderAPIError as exc:
                raise wrap(exc) from exc

        def gemini_call(slot, cfg, prompt: str, *, max_output_tokens: int, timeout_seconds: int) -> str:
            try:
                reply = gemini_generate(
                    model=slot.model,
                    api_key=cfg.gemini_api_key,
                    prompt=prompt,
                    max_output_tokens=max_output_tokens,
                    timeout_seconds=timeout_seconds,
                )
                if reply.model and reply.model != slot.model:
                    logger.info("Gemini fallback requested=%s used=%s", slot.model, reply.model)
                return reply.text
            except ProviderAPIError as exc:
                raise wrap(exc) from exc

        old_classifier = legacy._classify_cooldown_reason

        def classify_reason(reason: str) -> str:
            low = str(reason or "").casefold().strip()
            # The explicit kind written by _record_failure is authoritative.
            # In particular `temporary: HTTP 429: ... rate limit` must not turn
            # back into a hard quota on the next state normalization pass.
            for kind in (
                "temporary", "auth", "configuration", "quota", "model",
                "bad_response", "validation", "request_too_large",
            ):
                if low.startswith(kind + ":"):
                    return kind
            return old_classifier(reason)

        legacy._openai_call = openai_call
        legacy._gemini_call = gemini_call
        legacy._classify_cooldown_reason = classify_reason
        _INSTALLED = True
        logger.info("RC8 direct AI provider recovery runtime installed")
