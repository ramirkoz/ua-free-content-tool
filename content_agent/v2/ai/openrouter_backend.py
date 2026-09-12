from __future__ import annotations

import json
import logging
import math
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ...network import NetworkError, fetch_url
from ...paths import data_dir
from .contracts import AITask, QualityTier, UnifiedAIResult, Validator
from .settings import AIBackendSettings, load_openrouter_api_key
from .task_router import next_tier, route_for
from .usage import UsageEvent, record_usage, usage_summary


logger = logging.getLogger("content_agent.v2.openrouter")


class OpenRouterError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        kind: str = "temporary",
        model: str = "",
        finish_reason: str = "",
        reasoning_chars: int = 0,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.model = model
        self.finish_reason = finish_reason
        self.reasoning_chars = max(0, int(reasoning_chars or 0))


@dataclass(frozen=True, slots=True)
class ModelInfo:
    id: str
    name: str
    prompt_price: float
    completion_price: float
    context_length: int
    quality: int
    free: bool
    supported_parameters: tuple[str, ...] = ()
    reasoning_mandatory: bool = False
    reasoning_default_enabled: bool = False
    reasoning_efforts: tuple[str, ...] = ()
    max_completion_tokens: int = 0

    @property
    def blended_price_million(self) -> float:
        return (self.prompt_price * 0.82 + self.completion_price * 0.18) * 1_000_000


_CATALOG_LOCK = threading.Lock()
_CATALOG: tuple[ModelInfo, ...] = ()
_CATALOG_AT = 0.0
_CATALOG_TTL = 6 * 60 * 60
_EVENT_LOCK = threading.Lock()
_DEAD_MODEL_LOCK = threading.Lock()
_DEAD_MODEL_TTL_SECONDS = 12 * 60 * 60
_DEAD_MODELS: dict[str, dict[str, object]] | None = None


def _dead_models_path() -> Path:
    root = data_dir() / "v2"
    root.mkdir(parents=True, exist_ok=True)
    return root / "openrouter_dead_models.json"


def _load_dead_models_locked() -> dict[str, dict[str, object]]:
    global _DEAD_MODELS
    now = time.time()
    if _DEAD_MODELS is None:
        loaded: dict[str, dict[str, object]] = {}
        try:
            raw = json.loads(_dead_models_path().read_text(encoding="utf-8"))
            rows = raw.get("models") if isinstance(raw, dict) else {}
            if isinstance(rows, dict):
                for key, value in rows.items():
                    if isinstance(value, dict):
                        loaded[str(key).casefold()] = dict(value)
        except (OSError, json.JSONDecodeError):
            pass
        _DEAD_MODELS = loaded
    expired = [
        key for key, value in _DEAD_MODELS.items()
        if float(value.get("until", 0.0) or 0.0) <= now
    ]
    for key in expired:
        _DEAD_MODELS.pop(key, None)
    return _DEAD_MODELS


def _save_dead_models_locked() -> None:
    if _DEAD_MODELS is None:
        return
    path = _dead_models_path()
    try:
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps({"models": _DEAD_MODELS}, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)
    except OSError:
        pass


def _quarantined_model_ids() -> set[str]:
    with _DEAD_MODEL_LOCK:
        # _load_dead_models_locked() prunes expired entries in memory. Saving is
        # cheap and keeps the persistent file equally clean across restarts.
        _load_dead_models_locked()
        _save_dead_models_locked()
        return set(_DEAD_MODELS or {})


def _quarantine_model(model_id: str, reason: str, *, ttl_seconds: int = _DEAD_MODEL_TTL_SECONDS) -> None:
    model_key = str(model_id or "").strip().casefold()
    if not model_key:
        return
    with _DEAD_MODEL_LOCK:
        rows = _load_dead_models_locked()
        rows[model_key] = {
            "until": time.time() + max(300, int(ttl_seconds)),
            "reason": str(reason or "")[:600],
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        _save_dead_models_locked()
    logger.warning("OpenRouter quarantined unavailable model=%s for %.1fh: %s", model_id, ttl_seconds / 3600, reason[:300])


def _clear_model_quarantine(model_id: str) -> None:
    model_key = str(model_id or "").strip().casefold()
    if not model_key:
        return
    with _DEAD_MODEL_LOCK:
        rows = _load_dead_models_locked()
        if rows.pop(model_key, None) is not None:
            _save_dead_models_locked()


def _event_path() -> Path:
    root = data_dir() / "v2"
    root.mkdir(parents=True, exist_ok=True)
    return root / "openrouter_events.jsonl"


def _record_event(
    *,
    task: str,
    tier: str,
    model: str,
    outcome: str,
    kind: str = "",
    detail: str = "",
    elapsed_seconds: float = 0.0,
    finish_reason: str = "",
    reasoning_chars: int = 0,
    attempt: int = 0,
) -> None:
    payload = {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "task": str(task or ""),
        "tier": str(tier or ""),
        "model": str(model or ""),
        "attempt": int(attempt or 0),
        "outcome": str(outcome or ""),
        "kind": str(kind or ""),
        "finish_reason": str(finish_reason or ""),
        "reasoning_chars": int(reasoning_chars or 0),
        "elapsed_seconds": round(float(elapsed_seconds or 0.0), 3),
        "detail": str(detail or "")[:1200],
    }
    try:
        path = _event_path()
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        with _EVENT_LOCK:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line)
            if path.stat().st_size > 2 * 1024 * 1024:
                rows = path.read_text(encoding="utf-8", errors="replace").splitlines()[-1200:]
                temp = path.with_suffix(".tmp")
                temp.write_text("\n".join(rows) + "\n", encoding="utf-8")
                temp.replace(path)
    except OSError:
        pass


def recent_events(limit: int = 20) -> list[dict[str, object]]:
    try:
        rows = _event_path().read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, int(limit)):]
    except OSError:
        return []
    out: list[dict[str, object]] = []
    for row in rows:
        try:
            item = json.loads(row)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out


def record_pipeline_event(
    *,
    task: str,
    model: str,
    outcome: str,
    kind: str,
    detail: str,
) -> None:
    _record_event(
        task=task, tier="post_ai", model=model, attempt=0, outcome=outcome, kind=kind, detail=detail,
    )


_SKIP_ID_PARTS = (
    "image", "embedding", "rerank", "audio", "speech", "tts", "transcription", "video",
)


def _catalog_cache_path() -> Path:
    root = data_dir() / "v2"
    root.mkdir(parents=True, exist_ok=True)
    return root / "openrouter_models_cache.json"


def _price(value: object) -> float:
    try:
        result = float(str(value or "0"))
    except Exception:
        return math.inf
    if result < 0:
        return math.inf
    return result


def _quality_hint(model_id: str, name: str) -> int:
    """Conservative writing-quality class for the live OpenRouter catalog.

    RC4 promoted every ``gpt-5-*`` and every ``qwen3-*`` model before checking
    whether it was actually Nano/9B.  That made cheap tiny variants look like
    premium editorial models.  Small-model markers now win over family names.
    """
    text = f"{model_id} {name}".casefold()
    quality = 1
    if any(token in text for token in (
        "claude-sonnet", "claude-opus", "gpt-5", "gpt-6", "gemini-3",
        "gemini-2.5-pro", "grok-4",
    )):
        quality = 4
    elif any(token in text for token in (
        "120b", "235b", "400b", "550b", "671b", "large", "max", "pro", "ultra",
        "gpt-oss-120", "deepseek", "qwen3", "qwen-3", "glm-5", "glm5", "kimi-k2", "nemotron",
    )):
        quality = 3
    elif any(token in text for token in ("medium", "mistral", "command-r", "70b", "72b")):
        quality = 2

    # Explicit size/edition clamps are applied LAST.  A name such as
    # ``gpt-5-nano`` must never inherit GPT-5's premium score, and
    # ``qwen3.5-9b`` must not become STRONG merely because it contains qwen3.
    if any(token in text for token in ("nano", "tiny", "micro")):
        return 1
    if any(token in text for token in ("mini", "small", "lite", "flash")):
        quality = min(quality, 2)

    sizes = []
    for match in re.finditer(r"(?<![a-z0-9])([0-9]+(?:\.[0-9]+)?)b(?![a-z0-9])", text):
        try:
            sizes.append(float(match.group(1)))
        except ValueError:
            pass
    if sizes:
        size = max(sizes)
        if size <= 14:
            quality = min(quality, 1)
        elif size <= 32:
            quality = min(quality, 2)
        elif size <= 80:
            quality = min(quality, 3)
    return quality


def _model_family_key(model_id: str) -> str:
    """Collapse OpenRouter delivery variants to one underlying model family."""
    value = str(model_id or "").strip().casefold()
    if value.startswith("~"):
        value = value[1:]
    return value.split(":", 1)[0]


def _is_batch_variant(model_id: str) -> bool:
    return ":batch" in str(model_id or "").casefold()


def _parse_catalog(payload: object) -> tuple[ModelInfo, ...]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise OpenRouterError("OpenRouter повернув неправильний каталог моделей.", kind="bad_response")
    models: list[ModelInfo] = []
    for raw in payload["data"]:
        if not isinstance(raw, dict):
            continue
        model_id = str(raw.get("id") or "").strip()
        name = str(raw.get("name") or model_id).strip()
        if not model_id or any(part in model_id.casefold() for part in _SKIP_ID_PARTS):
            continue
        architecture = raw.get("architecture") if isinstance(raw.get("architecture"), dict) else {}
        output_modalities = architecture.get("output_modalities") if isinstance(architecture, dict) else None
        if isinstance(output_modalities, list) and "text" not in {str(x).casefold() for x in output_modalities}:
            continue
        pricing = raw.get("pricing") if isinstance(raw.get("pricing"), dict) else {}
        prompt_price = _price(pricing.get("prompt"))
        completion_price = _price(pricing.get("completion"))
        if not math.isfinite(prompt_price) or not math.isfinite(completion_price):
            continue
        context = int(raw.get("context_length") or 0)
        if context and context < 12_000:
            continue
        free = prompt_price == 0.0 and completion_price == 0.0
        supported_raw = raw.get("supported_parameters")
        supported_parameters = tuple(
            str(value).strip().casefold() for value in supported_raw
            if str(value or "").strip()
        ) if isinstance(supported_raw, list) else ()
        reasoning_raw = raw.get("reasoning") if isinstance(raw.get("reasoning"), dict) else {}
        efforts_raw = reasoning_raw.get("supported_efforts") if isinstance(reasoning_raw, dict) else None
        reasoning_efforts = tuple(
            str(value).strip().casefold() for value in efforts_raw
            if str(value or "").strip()
        ) if isinstance(efforts_raw, list) else ()
        top_provider = raw.get("top_provider") if isinstance(raw.get("top_provider"), dict) else {}
        models.append(ModelInfo(
            id=model_id,
            name=name,
            prompt_price=prompt_price,
            completion_price=completion_price,
            context_length=context,
            quality=_quality_hint(model_id, name),
            free=free,
            supported_parameters=supported_parameters,
            reasoning_mandatory=bool(reasoning_raw.get("mandatory", False)),
            reasoning_default_enabled=bool(reasoning_raw.get("default_enabled", False)),
            reasoning_efforts=reasoning_efforts,
            max_completion_tokens=int(top_provider.get("max_completion_tokens") or 0),
        ))
    if not models:
        raise OpenRouterError("OpenRouter не повернув придатних текстових моделей.", kind="bad_response")
    return tuple(models)


def _load_disk_catalog() -> tuple[ModelInfo, ...]:
    path = _catalog_cache_path()
    if not path.exists():
        return ()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        rows = raw.get("models") if isinstance(raw, dict) else None
        if not isinstance(rows, list):
            return ()
        result = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            model_id = str(row["id"])
            name = str(row.get("name") or row["id"])
            # Recompute quality so an RC4 cache cannot preserve the old
            # gpt-5-nano/qwen-9b overrating after upgrading to RC5.
            result.append(ModelInfo(
                id=model_id,
                name=name,
                prompt_price=float(row.get("prompt_price") or 0.0),
                completion_price=float(row.get("completion_price") or 0.0),
                context_length=int(row.get("context_length") or 0),
                quality=_quality_hint(model_id, name),
                free=bool(row.get("free", False)),
                supported_parameters=tuple(str(x).casefold() for x in (row.get("supported_parameters") or ()) if str(x or "").strip()),
                reasoning_mandatory=bool(row.get("reasoning_mandatory", False)),
                reasoning_default_enabled=bool(row.get("reasoning_default_enabled", False)),
                reasoning_efforts=tuple(str(x).casefold() for x in (row.get("reasoning_efforts") or ()) if str(x or "").strip()),
                max_completion_tokens=int(row.get("max_completion_tokens") or 0),
            ))
        return tuple(result)
    except Exception:
        return ()


def _save_disk_catalog(models: tuple[ModelInfo, ...]) -> None:
    path = _catalog_cache_path()
    payload = {
        "saved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "models": [
            {
                "id": row.id,
                "name": row.name,
                "prompt_price": row.prompt_price,
                "completion_price": row.completion_price,
                "context_length": row.context_length,
                "quality": row.quality,
                "free": row.free,
                "supported_parameters": list(row.supported_parameters),
                "reasoning_mandatory": row.reasoning_mandatory,
                "reasoning_default_enabled": row.reasoning_default_enabled,
                "reasoning_efforts": list(row.reasoning_efforts),
                "max_completion_tokens": row.max_completion_tokens,
            }
            for row in models
        ],
    }
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def model_catalog(*, force: bool = False, timeout: float = 20.0) -> tuple[ModelInfo, ...]:
    global _CATALOG, _CATALOG_AT
    now = time.time()
    with _CATALOG_LOCK:
        if _CATALOG and not force and now - _CATALOG_AT < _CATALOG_TTL:
            return _CATALOG
    try:
        response = fetch_url(
            "https://openrouter.ai/api/v1/models",
            headers={"Accept": "application/json"},
            max_bytes=12 * 1024 * 1024,
            allowed_content_types={"application/json"},
            timeout=timeout,
            max_redirects=0,
            allow_http_errors=True,
        )
        if response.status >= 400:
            raise OpenRouterError(f"Каталог OpenRouter: HTTP {response.status}.", kind="network")
        parsed = _parse_catalog(response.json())
        with _CATALOG_LOCK:
            _CATALOG, _CATALOG_AT = parsed, now
        try:
            _save_disk_catalog(parsed)
        except OSError:
            pass
        return parsed
    except Exception:
        cached = _load_disk_catalog()
        if cached:
            with _CATALOG_LOCK:
                _CATALOG, _CATALOG_AT = cached, now
            return cached
        raise


def _tier_rank(tier: QualityTier) -> int:
    return {
        QualityTier.FAST_CHEAP: 1,
        QualityTier.BALANCED: 2,
        QualityTier.STRONG: 3,
        QualityTier.PREMIUM: 4,
    }[tier]


def _candidate_models(
    catalog: tuple[ModelInfo, ...],
    tier: QualityTier,
    *,
    prompt_chars: int,
    max_output_tokens: int,
    strategy: str,
    exclude_models: set[str] | frozenset[str] = frozenset(),
    task: AITask | None = None,
) -> list[ModelInfo]:
    min_quality = _tier_rank(tier)
    estimated_prompt_tokens = max(64, int(prompt_chars / 3.5))
    required_context = max(12_000, estimated_prompt_tokens + max_output_tokens * 2 + 2_000)
    cap = {
        QualityTier.FAST_CHEAP: 1.5,
        QualityTier.BALANCED: 5.0,
        QualityTier.STRONG: 18.0,
        QualityTier.PREMIUM: 80.0,
    }[tier]
    if strategy == "economy":
        cap *= 0.65
    elif strategy == "quality":
        cap *= 1.7

    excluded = {str(value or "").strip().casefold() for value in exclude_models if str(value or "").strip()}
    excluded_families = {_model_family_key(value) for value in excluded}

    def eligible_row(row: ModelInfo) -> bool:
        return (
            not _is_batch_variant(row.id)
            and row.id.casefold() not in excluded
            and _model_family_key(row.id) not in excluded_families
            and row.quality >= min_quality
            and (not row.context_length or row.context_length >= required_context)
            and row.blended_price_million <= cap
        )

    eligible = [row for row in catalog if eligible_row(row) and (strategy == "economy" or not row.free)]
    if not eligible and strategy != "economy":
        eligible = [row for row in catalog if eligible_row(row)]

    reasoning_tokens = ("gpt-oss", "deepseek-r1", "/r1", "qwq", "reasoning")

    def reasoning_penalty(row: ModelInfo) -> int:
        if row.reasoning_mandatory:
            return 2
        if row.reasoning_default_enabled or any(token in row.id.casefold() for token in reasoning_tokens):
            return 1
        return 0

    def sort_key(row: ModelInfo):
        penalty = reasoning_penalty(row)
        if task in {AITask.REWRITE, AITask.QUALITY}:
            # Editorial copy values predictable direct instruction-following over
            # hidden reasoning burn.  Inside that class, prefer the strongest
            # model before price.
            return (penalty, -row.quality, row.blended_price_million, -row.context_length, row.id)
        if task == AITask.FACT:
            return (-row.quality, penalty, row.blended_price_million, -row.context_length, row.id)
        return (penalty, row.blended_price_million, -row.quality, -row.context_length, row.id)

    eligible.sort(key=sort_key)
    return eligible[:12]


def _extract_text(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(str(item["text"]))
        return "\n".join(parts).strip()
    return ""


def _response_meta(payload: object) -> tuple[str, int]:
    if not isinstance(payload, dict):
        return "", 0
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return "", 0
    first = choices[0]
    finish_reason = str(first.get("finish_reason") or "")
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    reasoning_chars = 0
    if isinstance(message, dict):
        reasoning = message.get("reasoning")
        if isinstance(reasoning, str):
            reasoning_chars += len(reasoning)
        details = message.get("reasoning_details")
        if isinstance(details, list):
            for item in details:
                if isinstance(item, dict):
                    for key in ("text", "content", "summary"):
                        value = item.get(key)
                        if isinstance(value, str):
                            reasoning_chars += len(value)
    return finish_reason, reasoning_chars


def _usage(payload: object, model: ModelInfo) -> tuple[int, int, float]:
    if not isinstance(payload, dict):
        return 0, 0, 0.0
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    prompt_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    raw_cost = usage.get("cost")
    try:
        cost = float(raw_cost) if raw_cost is not None else 0.0
    except Exception:
        cost = 0.0
    if cost <= 0 and (prompt_tokens or completion_tokens):
        cost = prompt_tokens * model.prompt_price + completion_tokens * model.completion_price
    return prompt_tokens, completion_tokens, max(0.0, cost)


def _reasoning_config(model: ModelInfo, task: AITask) -> dict[str, object] | None:
    params = set(model.supported_parameters)
    if "reasoning" not in params and "reasoning_effort" not in params:
        return None
    efforts = tuple(value.casefold() for value in model.reasoning_efforts)
    # For editorial rewrite/QA the public answer matters more than hidden chain
    # length.  FACT gets a small reasoning allowance; everything else is kept
    # as direct as the model permits.
    preferred = ("low", "minimal", "none") if task == AITask.FACT else ("none", "minimal", "low")
    if model.reasoning_mandatory:
        preferred = tuple(value for value in preferred if value != "none")
    effort = next((value for value in preferred if not efforts or value in efforts), None)
    if effort is None and efforts:
        effort = efforts[-1]
    if effort is None:
        return None
    return {"effort": effort}


def _completion_limit(model: ModelInfo, requested: int) -> tuple[str, int]:
    value = min(8192, max(64, int(requested)))
    if model.reasoning_mandatory:
        # Tiny probe/classification budgets can be consumed entirely by mandatory
        # reasoning before a single public token is emitted.
        value = max(value, 256)
    if model.max_completion_tokens > 0:
        value = min(value, model.max_completion_tokens)
    key = "max_completion_tokens" if "max_completion_tokens" in set(model.supported_parameters) else "max_tokens"
    return key, value


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
        model: ModelInfo,
        *,
        max_output_tokens: int,
        timeout_seconds: int,
        task: AITask,
    ) -> tuple[str, str, object, ModelInfo]:
        api_key = load_openrouter_api_key()
        if not api_key:
            raise OpenRouterError("OpenRouter API key не налаштовано.", kind="configuration")
        limit_key, limit_value = _completion_limit(model, max_output_tokens)
        body = {
            "model": model.id,
            "messages": [{"role": "user", "content": prompt}],
            limit_key: limit_value,
            "usage": {"include": True},
            "provider": {
                "allow_fallbacks": True,
                "sort": "price",
                "data_collection": "deny",
            },
        }
        params = set(model.supported_parameters)
        if "temperature" in params:
            body["temperature"] = 0
        reasoning = _reasoning_config(model, task)
        if reasoning is not None:
            body["reasoning"] = reasoning
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
            timeout=max(8, int(timeout_seconds)),
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
            kind = (
                "quota" if response.status == 429
                else "auth" if response.status in {401, 403}
                else "network" if response.status >= 500
                else "bad_response"
            )
            raise OpenRouterError(
                f"OpenRouter HTTP {response.status}: {detail or 'request rejected'}",
                kind=kind,
                model=model.id,
            )
        text = _extract_text(payload)
        finish_reason, reasoning_chars = _response_meta(payload)
        used_model_id = str(payload.get("model") or model.id) if isinstance(payload, dict) else model.id
        if not text:
            detail = f"finish_reason={finish_reason or '<none>'}; reasoning_chars={reasoning_chars}"
            raise OpenRouterError(
                f"OpenRouter model {used_model_id} повернула порожній content ({detail}).",
                kind="empty_content",
                model=used_model_id,
                finish_reason=finish_reason,
                reasoning_chars=reasoning_chars,
            )
        return text, used_model_id, payload, model

    def run(
        self,
        prompt: str,
        *,
        validator: Validator | None = None,
        max_output_tokens: int = 800,
        timeout_seconds: int = 60,
        task: AITask | None = None,
        skip_models: set[str] | frozenset[str] | tuple[str, ...] = (),
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
        excluded = {str(value or "").strip().casefold() for value in skip_models if str(value or "").strip()}
        # Models that OpenRouter explicitly reported as having no endpoint are
        # persisted across restarts for a bounded TTL.  RC5 retried the same 404
        # model on every rewrite because it remained in the catalog cache.
        excluded.update(_quarantined_model_ids())
        deadline = time.monotonic() + max(15, int(timeout_seconds))
        last_error: Exception | None = None
        max_distinct_attempts = min(3, max(1, int(route.max_attempts)))
        tries = 0

        while tier is not None and tries < max_distinct_attempts:
            candidates = _candidate_models(
                catalog,
                tier,
                prompt_chars=len(prompt),
                max_output_tokens=max_output_tokens,
                strategy=self.settings.openrouter_strategy,
                exclude_models=excluded | {value.casefold() for value in attempted},
                task=route.task,
            )
            if not candidates:
                if tier == route.max_tier:
                    break
                tier = next_tier(tier)
                continue

            model = candidates[0]
            remaining = int(deadline - time.monotonic())
            if remaining < 8:
                break
            tries += 1
            attempted.append(model.id)
            attempts_left = max(1, max_distinct_attempts - tries + 1)
            per_model_timeout = min(35, max(8, remaining // attempts_left))
            started = time.monotonic()
            logger.info(
                "OpenRouter task=%s tier=%s attempt=%s/%s model=%s timeout=%ss excluded=%s",
                route.task.value, tier.value, tries, max_distinct_attempts, model.id, per_model_timeout, len(excluded),
            )
            try:
                text, used_model_id, payload, used_model = self._call(
                    prompt,
                    model,
                    max_output_tokens=max_output_tokens,
                    timeout_seconds=per_model_timeout,
                    task=route.task,
                )
                prompt_tokens, completion_tokens, cost = _usage(payload, used_model)
                finish_reason, reasoning_chars = _response_meta(payload)
                if validator is not None:
                    try:
                        validator(text)
                    except Exception as exc:
                        elapsed = time.monotonic() - started
                        detail = f"QA rejected: {exc}"
                        record_usage(UsageEvent(
                            timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
                            backend="openrouter", task=route.task.value, provider="openrouter", model=used_model_id,
                            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, cost_usd=cost,
                            elapsed_seconds=elapsed, success=False, detail=detail[:800],
                        ))
                        _record_event(
                            task=route.task.value, tier=tier.value, model=used_model_id, attempt=tries,
                            outcome="qa_fail", kind="validation", detail=detail, elapsed_seconds=elapsed,
                            finish_reason=finish_reason, reasoning_chars=reasoning_chars,
                        )
                        last_error = OpenRouterError(
                            f"Відповідь {used_model_id} не пройшла QA: {exc}",
                            kind="validation", model=used_model_id, finish_reason=finish_reason,
                            reasoning_chars=reasoning_chars,
                        )
                        continue

                elapsed = time.monotonic() - started
                record_usage(UsageEvent(
                    timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
                    backend="openrouter", task=route.task.value, provider="openrouter", model=used_model_id,
                    prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, cost_usd=cost,
                    elapsed_seconds=elapsed, success=True,
                ))
                _record_event(
                    task=route.task.value, tier=tier.value, model=used_model_id, attempt=tries,
                    outcome="ok", elapsed_seconds=elapsed, finish_reason=finish_reason, reasoning_chars=reasoning_chars,
                )
                logger.info(
                    "OpenRouter success task=%s tier=%s model=%s attempt=%s in=%s out=%s cost=%.6f elapsed=%.2f finish=%s",
                    route.task.value, tier.value, used_model_id, tries, prompt_tokens, completion_tokens, cost, elapsed, finish_reason,
                )
                _clear_model_quarantine(used_model_id)
                return UnifiedAIResult(
                    text=text, backend="openrouter", provider="openrouter", model=used_model_id,
                    label=f"{used_model.name} / OpenRouter", attempted=tuple(dict.fromkeys(attempted)),
                    prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, cost_usd=cost,
                )
            except OpenRouterError as exc:
                last_error = exc
                elapsed = time.monotonic() - started
                logger.warning(
                    "OpenRouter failure task=%s tier=%s attempt=%s model=%s kind=%s detail=%s",
                    route.task.value, tier.value, tries, model.id, exc.kind, str(exc)[:500],
                )
                if exc.kind != "validation":
                    record_usage(UsageEvent(
                        timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
                        backend="openrouter", task=route.task.value, provider="openrouter", model=exc.model or model.id,
                        prompt_tokens=0, completion_tokens=0, cost_usd=0.0, elapsed_seconds=elapsed,
                        success=False, detail=str(exc)[:800],
                    ))
                    _record_event(
                        task=route.task.value, tier=tier.value, model=exc.model or model.id, attempt=tries,
                        outcome="failed", kind=exc.kind, detail=str(exc), elapsed_seconds=elapsed,
                        finish_reason=exc.finish_reason, reasoning_chars=exc.reasoning_chars,
                    )
                detail_cf = str(exc).casefold()
                if exc.kind == "bad_response" and "http 404" in detail_cf and "no endpoints found" in detail_cf:
                    _quarantine_model(exc.model or model.id, str(exc))
                    excluded.add((exc.model or model.id).casefold())
                if exc.kind in {"auth", "configuration", "budget"}:
                    raise
                continue
            except NetworkError as exc:
                elapsed = time.monotonic() - started
                last_error = OpenRouterError(str(exc), kind="network", model=model.id)
                _record_event(
                    task=route.task.value, tier=tier.value, model=model.id, attempt=tries,
                    outcome="failed", kind="network", detail=str(exc), elapsed_seconds=elapsed,
                )
                continue

        if last_error is not None:
            tried = ", ".join(dict.fromkeys(attempted)) or "немає"
            raise OpenRouterError(
                f"OpenRouter не завершив AI-задачу після різних моделей [{tried}]: {last_error}",
                kind=getattr(last_error, "kind", "temporary"),
                model=getattr(last_error, "model", ""),
                finish_reason=getattr(last_error, "finish_reason", ""),
                reasoning_chars=getattr(last_error, "reasoning_chars", 0),
            )
        raise OpenRouterError("OpenRouter не знайшов придатної моделі для AI-задачі.", kind="configuration")

    def probe(self) -> str:
        result = self.run(
            "Відповідай тільки словом OK.",
            max_output_tokens=16,
            timeout_seconds=30,
            task=AITask.CLASSIFY,
        )
        return f"OpenRouter працює: {result.model}"
