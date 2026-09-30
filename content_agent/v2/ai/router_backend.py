from __future__ import annotations

import time

from .contracts import AIRequest, UnifiedAIResult
from .provider_api import ProviderAPIError, gemini_generate, openai_compatible_chat


class CanonicalRouterBackend:
    """Non-mutating V2 Router backend.

    Routing/cooldown state remains compatible with the durable legacy state format,
    while cloud transport and provider fallback are owned explicitly here. Nothing is
    installed into or monkey-patched onto ``content_agent.ai_router`` at runtime.
    """

    name = "router"

    @staticmethod
    def _cancelled(request: AIRequest) -> bool:
        return bool(
            request.cancel_event is not None
            and getattr(request.cancel_event, "is_set", lambda: False)()
        )

    @staticmethod
    def _provider_error(exc: ProviderAPIError):
        from ... import ai_router as legacy

        return legacy.AIModelError(
            str(exc),
            kind=str(getattr(exc, "kind", "temporary") or "temporary"),
            retry_after=getattr(exc, "retry_after", None),
        )

    def _invoke_cloud(self, slot, cfg, prompt: str, *, max_output_tokens: int, timeout_seconds: int):
        from ... import ai_router as legacy

        try:
            if slot.provider == "gemini":
                reply = gemini_generate(
                    model=slot.model,
                    api_key=cfg.gemini_api_key,
                    prompt=prompt,
                    max_output_tokens=max_output_tokens,
                    timeout_seconds=timeout_seconds,
                )
            else:
                if slot.provider == "nvidia":
                    api_key, account_id = cfg.nvidia_api_key, ""
                elif slot.provider == "groq":
                    api_key, account_id = cfg.groq_api_key, ""
                elif slot.provider == "cloudflare":
                    api_key, account_id = cfg.cloudflare_api_token, cfg.cloudflare_account_id
                else:
                    raise ProviderAPIError(f"Unsupported provider: {slot.provider}", kind="configuration")
                reply = openai_compatible_chat(
                    slot.provider,
                    model=slot.model,
                    api_key=api_key,
                    account_id=account_id,
                    prompt=prompt,
                    max_output_tokens=max_output_tokens,
                    timeout_seconds=timeout_seconds,
                )
        except ProviderAPIError as exc:
            raise self._provider_error(exc) from exc

        runtime_slot = slot
        if reply.model and reply.model != slot.model:
            runtime_slot = legacy.AIModelSlot(slot.priority, slot.provider, reply.model, slot.label, slot.family)
        return str(reply.text or "").strip(), runtime_slot

    def _invoke(self, slot, cfg, request: AIRequest, *, timeout_seconds: int, output_budget: int, local_budget: int):
        from ... import ai_router as legacy

        if slot.provider == "local":
            output, target = legacy._invoke_local(
                cfg,
                str(request.local_prompt or request.prompt),
                max_output_tokens=local_budget,
                timeout_seconds=timeout_seconds,
            )
            runtime_slot = legacy.AIModelSlot(
                slot.priority,
                slot.provider,
                str(getattr(target, "model", "") or slot.model),
                str(getattr(target, "label", "") or slot.label),
                slot.family,
            )
            return str(output or "").strip(), runtime_slot
        if slot.provider == "codex":
            return legacy._invoke_codex_limited(request.prompt, timeout_seconds), slot
        return self._invoke_cloud(
            slot,
            cfg,
            request.prompt,
            max_output_tokens=output_budget,
            timeout_seconds=timeout_seconds,
        )

    def run(self, request: AIRequest) -> UnifiedAIResult:
        from ... import ai_router as legacy

        legacy._normalize_state()
        if self._cancelled(request):
            raise legacy.AIRouterError("AI-завдання скасовано.")
        prompt = str(request.prompt or "").strip()
        if not prompt:
            raise legacy.AIRouterError("AI Router отримав порожній запит.")

        cfg = legacy.load_provider_secrets()
        state = legacy.load_router_state()
        skipped_providers = {str(v).strip().casefold() for v in request.skip_providers if str(v).strip()}
        skipped_models = {str(v).strip().casefold() for v in request.skip_models if str(v).strip()}
        routes = legacy._available_routes(
            cfg=cfg,
            state=state,
            skip_providers=skipped_providers,
            skip_models=skipped_models,
        )
        if not routes:
            raise legacy._diagnostic_error(legacy.AIRouterError("Немає здорового маршруту поза cooldown."))

        total_timeout = 150 if request.task_timeout_seconds is None else max(3, int(request.task_timeout_seconds))
        deadline = time.monotonic() + total_timeout
        output_budget = min(4095, max(128, int(request.max_output_tokens)))
        local_budget = min(1400, max(128, int(request.local_max_output_tokens or output_budget)))
        attempted: list[str] = []
        failures: list[str] = []
        blocked_providers: set[str] = set()

        for slot in routes:
            if self._cancelled(request):
                raise legacy.AIRouterError("AI-завдання скасовано.")
            if slot.provider in blocked_providers:
                continue
            remaining = max(0, int(deadline - time.monotonic()))
            if remaining < 3:
                failures.append("Загальний ліміт часу AI-завдання вичерпано.")
                break
            if slot.provider == "local" and remaining < 30:
                continue
            provider_cap = {"codex": 45, "gemini": 25, "nvidia": 30, "groq": 25, "cloudflare": 25, "local": 60}.get(slot.provider, 25)
            if slot.provider == "local":
                provider_cap = min(provider_cap, max(30, int(request.local_timeout_seconds)))
            elif slot.provider != "codex":
                provider_cap = min(provider_cap, max(3, int(request.cloud_timeout_seconds)))
            call_timeout = max(3, min(provider_cap, remaining))
            attempted.append(slot.label)
            started = time.monotonic()
            legacy._record_model_health(state, slot, outcome="running")
            legacy.save_router_state(state)

            try:
                output, runtime_slot = self._invoke(
                    slot,
                    cfg,
                    request,
                    timeout_seconds=call_timeout,
                    output_budget=output_budget,
                    local_budget=local_budget,
                )
                if not output:
                    raise legacy.AIModelError("Порожня відповідь.", kind="bad_response")
                if self._cancelled(request):
                    raise legacy.AIRouterError("AI-завдання скасовано.")
                if request.validator is not None:
                    try:
                        request.validator(output)
                    except Exception as validation_error:
                        elapsed = time.monotonic() - started
                        failures.append(f"{runtime_slot.label}: QA ({validation_error})")
                        legacy._record_model_health(
                            state,
                            slot,
                            outcome="qa_rejected",
                            elapsed=elapsed,
                            detail=str(validation_error),
                        )
                        legacy.save_router_state(state)
                        if slot.provider != "local" or not request.local_repair:
                            continue
                        remaining = max(0, int(deadline - time.monotonic()))
                        if remaining < 30:
                            continue
                        try:
                            repaired, target = legacy._repair_local_output(
                                cfg,
                                str(request.local_prompt or request.prompt),
                                output,
                                validation_error,
                                max_output_tokens=min(local_budget, 320),
                                timeout_seconds=min(60, remaining),
                            )
                            output = str(repaired or "").strip()
                            request.validator(output)
                            runtime_slot = legacy.AIModelSlot(
                                slot.priority,
                                slot.provider,
                                str(getattr(target, "model", "") or runtime_slot.model),
                                str(getattr(target, "label", "") or runtime_slot.label),
                                slot.family,
                            )
                        except Exception:
                            continue
            except legacy.AIRouterError:
                raise
            except legacy.AIModelError as exc:
                elapsed = time.monotonic() - started
                failures.append(f"{slot.label}: {exc}")
                legacy._record_failure(state, slot, exc, elapsed)
                legacy.save_router_state(state)
                if str(getattr(exc, "kind", "temporary") or "temporary") in {"quota", "auth", "configuration"}:
                    blocked_providers.add(slot.provider)
                continue
            except Exception as exc:
                elapsed = time.monotonic() - started
                failures.append(f"{slot.label}: {exc}")
                wrapped = legacy.AIModelError(str(exc), kind="temporary")
                legacy._record_failure(state, slot, wrapped, elapsed)
                legacy.save_router_state(state)
                continue

            elapsed = time.monotonic() - started
            state.last_provider = runtime_slot.provider
            state.last_model = runtime_slot.model
            state.last_label = runtime_slot.label
            state.last_success_at = time.time()
            legacy._record_model_health(state, slot, outcome="ok", elapsed=elapsed)
            legacy._clear_success_cooldowns(state, slot)
            legacy.save_router_state(state)
            return UnifiedAIResult(
                text=output,
                backend="router",
                provider=runtime_slot.provider,
                model=runtime_slot.model,
                label=runtime_slot.label,
                attempted=tuple(attempted),
            )

        detail = " | ".join(failures[-6:])
        raise legacy._diagnostic_error(
            legacy.AIRouterError("Усі здорові маршрути цього завдання відмовили. " + detail)
        )


__all__ = ["CanonicalRouterBackend"]
