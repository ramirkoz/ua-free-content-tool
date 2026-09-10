from __future__ import annotations

import json
import logging
import time
from datetime import datetime

from ...network import NetworkError, fetch_url
from .contracts import AITask, UnifiedAIResult, Validator
from .settings import AIBackendSettings, load_openrouter_api_key
from .task_router import next_tier, route_for
from .usage import UsageEvent, record_usage, usage_summary
from .openrouter_catalog import OpenRouterError, ModelInfo, model_catalog, _candidate_models, _extract_text, _usage

logger = logging.getLogger("content_agent.v2.openrouter")


class OpenRouterBackend:
    def __init__(self, settings: AIBackendSettings):
        self.settings = settings.normalized()

    def configured(self) -> bool:
        try:
            return bool(load_openrouter_api_key())
        except Exception:
            return False

    def _ensure_budget(self) -> None:
        budget = float(self.settings.openrouter_monthly_budget_usd or 0.0)
        if budget <= 0:
            return
        spent = float(usage_summary(backend="openrouter").get("month_cost") or 0.0)
        if spent >= budget:
            raise OpenRouterError(
                f"Досягнуто місячний ліміт OpenRouter ${budget:.2f}; витрачено ${spent:.2f}.",
                kind="budget",
            )

    def _call(
        self,
        prompt: str,
        models: list[ModelInfo],
        *,
        max_output_tokens: int,
        timeout_seconds: int,
    ) -> tuple[str, str, object, ModelInfo]:
        api_key = load_openrouter_api_key()
        if not api_key:
            raise OpenRouterError("OpenRouter API key не налаштовано.", kind="configuration")
        if not models:
            raise OpenRouterError("OpenRouter: немає моделі для цього класу задачі.", kind="configuration")
        primary = models[0]
        body = {
            "models": [row.id for row in models[:3]],
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": min(8192, max(32, int(max_output_tokens))),
            "temperature": 0,
            "usage": {"include": True},
            "provider": {
                "allow_fallbacks": True,
                "sort": "price",
                "data_collection": "deny",
            },
        }
        response = fetch_url(
            "https://openrouter.ai/api/v1/chat/completions",
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
                "X-Title": "UA FREE Content Tool V2",
            },
            body=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            max_bytes=8 * 1024 * 1024,
            allowed_content_types={"application/json"},
            timeout=max(10, int(timeout_seconds)),
            max_redirects=0,
            allow_http_errors=True,
        )
        payload = response.json() if response.body else {}
        if response.status >= 400:
            detail = ""
            if isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, dict):
                    detail = str(error.get("message") or error.get("code") or "")
                elif error:
                    detail = str(error)
            kind = "quota" if response.status == 429 else "auth" if response.status in {401, 403} else "network" if response.status >= 500 else "bad_response"
            raise OpenRouterError(f"OpenRouter HTTP {response.status}: {detail or 'request rejected'}", kind=kind)
        text = _extract_text(payload)
        if not text:
            raise OpenRouterError("OpenRouter повернув порожню відповідь.", kind="bad_response")
        used_model_id = str(payload.get("model") or primary.id) if isinstance(payload, dict) else primary.id
        used = next((row for row in models if row.id == used_model_id), primary)
        return text, used_model_id, payload, used

    def run(
        self,
        prompt: str,
        *,
        validator: Validator | None = None,
        max_output_tokens: int = 800,
        timeout_seconds: int = 60,
        task: AITask | None = None,
    ) -> UnifiedAIResult:
        if not self.configured():
            raise OpenRouterError("OpenRouter API key не налаштовано.", kind="configuration")
        self._ensure_budget()
        route = route_for(
            prompt,
            max_output_tokens=max_output_tokens,
            strategy=self.settings.openrouter_strategy,
            task=task,
        )
        catalog = model_catalog()
        tier = route.initial_tier
        attempted: list[str] = []
        deadline = time.monotonic() + max(15, int(timeout_seconds))
        last_error: Exception | None = None
        tries = 0
        while tier is not None and tries < route.max_attempts:
            candidates = _candidate_models(
                catalog,
                tier,
                prompt_chars=len(prompt),
                max_output_tokens=max_output_tokens,
                strategy=self.settings.openrouter_strategy,
            )
            if not candidates:
                if tier == route.max_tier:
                    break
                tier = next_tier(tier)
                continue
            remaining = max(8, int(deadline - time.monotonic()))
            if remaining <= 8 and tries:
                break
            started = time.monotonic()
            tries += 1
            attempted.extend(row.id for row in candidates[:3])
            try:
                logger.info("OpenRouter task=%s tier=%s candidates=%s", route.task.value, tier.value, ",".join(row.id for row in candidates[:3]))
                text, used_model_id, payload, used_model = self._call(
                    prompt,
                    candidates,
                    max_output_tokens=max_output_tokens,
                    timeout_seconds=min(remaining, 75),
                )
                prompt_tokens, completion_tokens, cost = _usage(payload, used_model)
                if validator is not None:
                    try:
                        validator(text)
                    except Exception as exc:
                        elapsed = time.monotonic() - started
                        record_usage(UsageEvent(
                            timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
                            backend="openrouter",
                            task=route.task.value,
                            provider="openrouter",
                            model=used_model_id,
                            prompt_tokens=prompt_tokens,
                            completion_tokens=completion_tokens,
                            cost_usd=cost,
                            elapsed_seconds=elapsed,
                            success=False,
                            detail=f"QA rejected: {exc}"[:800],
                        ))
                        last_error = OpenRouterError(f"Відповідь {used_model_id} не пройшла QA: {exc}", kind="validation")
                        if tier == route.max_tier:
                            raise last_error
                        tier = next_tier(tier)
                        continue
                elapsed = time.monotonic() - started
                record_usage(UsageEvent(
                    timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
                    backend="openrouter",
                    task=route.task.value,
                    provider="openrouter",
                    model=used_model_id,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost_usd=cost,
                    elapsed_seconds=elapsed,
                    success=True,
                ))
                logger.info(
                    "OpenRouter success task=%s tier=%s model=%s in=%s out=%s cost=%.6f elapsed=%.2f",
                    route.task.value, tier.value, used_model_id, prompt_tokens, completion_tokens, cost, elapsed,
                )
                return UnifiedAIResult(
                    text=text,
                    backend="openrouter",
                    provider="openrouter",
                    model=used_model_id,
                    label=f"{used_model.name} / OpenRouter",
                    attempted=tuple(dict.fromkeys(attempted)),
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost_usd=cost,
                )
            except OpenRouterError as exc:
                last_error = exc
                logger.warning("OpenRouter failure task=%s tier=%s kind=%s detail=%s", route.task.value, tier.value, exc.kind, str(exc)[:500])
                elapsed = time.monotonic() - started
                if exc.kind not in {"validation"}:
                    record_usage(UsageEvent(
                        timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
                        backend="openrouter",
                        task=route.task.value,
                        provider="openrouter",
                        model=candidates[0].id,
                        prompt_tokens=0,
                        completion_tokens=0,
                        cost_usd=0.0,
                        elapsed_seconds=elapsed,
                        success=False,
                        detail=str(exc)[:800],
                    ))
                if exc.kind in {"auth", "configuration", "budget"}:
                    raise
                if tier == route.max_tier:
                    break
                tier = next_tier(tier)
            except NetworkError as exc:
                last_error = OpenRouterError(str(exc), kind="network")
                if tier == route.max_tier:
                    break
                tier = next_tier(tier)
        if last_error is not None:
            raise OpenRouterError(f"OpenRouter не завершив AI-задачу: {last_error}", kind=getattr(last_error, "kind", "temporary"))
        raise OpenRouterError("OpenRouter не знайшов придатної моделі для AI-задачі.", kind="configuration")

    def probe(self) -> str:
        result = self.run(
            "Відповідай тільки словом OK.",
            max_output_tokens=16,
            timeout_seconds=30,
            task=AITask.CLASSIFY,
        )
        return f"OpenRouter працює: {result.model}"
