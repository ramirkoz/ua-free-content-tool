from __future__ import annotations

import json
import logging
import math
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
    def __init__(self, message: str, *, kind: str = "temporary") -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True, slots=True)
class ModelInfo:
    id: str
    name: str
    prompt_price: float
    completion_price: float
    context_length: int
    quality: int
    free: bool

    @property
    def blended_price_million(self) -> float:
        return (self.prompt_price * 0.82 + self.completion_price * 0.18) * 1_000_000


_CATALOG_LOCK = threading.Lock()
_CATALOG: tuple[ModelInfo, ...] = ()
_CATALOG_AT = 0.0
_CATALOG_TTL = 6 * 60 * 60


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
    text = f"{model_id} {name}".casefold()
    quality = 1
    # Parameter-size and family hints are deliberately broad. The live catalog
    # changes faster than Content Tool releases, so V2 selects a class, not a
    # hard-coded model name.
    if any(token in text for token in (
        "120b", "235b", "400b", "550b", "671b", "large", "max", "pro", "ultra",
        "gpt-oss-120", "deepseek", "qwen3", "qwen-3", "glm-5", "glm5", "kimi-k2", "nemotron",
    )):
        quality = max(quality, 3)
    if any(token in text for token in (
        "claude-sonnet", "claude-opus", "gpt-5", "gpt-6", "gemini-3", "gemini-2.5-pro", "grok-4",
    )):
        quality = 4
    if any(token in text for token in ("flash", "mini", "small", "lite", "8b", "14b", "27b", "30b", "32b")):
        quality = min(quality, 2) if quality < 4 else quality
    return quality


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
        models.append(ModelInfo(
            id=model_id,
            name=name,
            prompt_price=prompt_price,
            completion_price=completion_price,
            context_length=context,
            quality=_quality_hint(model_id, name),
            free=free,
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
            result.append(ModelInfo(
                id=str(row["id"]),
                name=str(row.get("name") or row["id"]),
                prompt_price=float(row.get("prompt_price") or 0.0),
                completion_price=float(row.get("completion_price") or 0.0),
                context_length=int(row.get("context_length") or 0),
                quality=int(row.get("quality") or 1),
                free=bool(row.get("free", False)),
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
) -> list[ModelInfo]:
    min_quality = _tier_rank(tier)
    estimated_prompt_tokens = max(64, int(prompt_chars / 3.5))
    required_context = max(12_000, estimated_prompt_tokens + max_output_tokens * 2 + 2_000)
    # Per-million blended ceilings protect against a surprise premium route.
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

    eligible = [
        row for row in catalog
        if row.quality >= min_quality
        and (not row.context_length or row.context_length >= required_context)
        and row.blended_price_million <= cap
        and (strategy == "economy" or not row.free)
    ]
    if not eligible and strategy != "economy":
        eligible = [
            row for row in catalog
            if row.quality >= min_quality
            and (not row.context_length or row.context_length >= required_context)
            and row.blended_price_million <= cap
        ]
    # Cheapest viable model wins inside a quality class. For equal price prefer
    # higher quality and more context. OpenRouter itself then chooses the cheapest
    # healthy provider endpoint for that model.
    eligible.sort(key=lambda row: (row.blended_price_million, -row.quality, -row.context_length, row.id))
    return eligible[:8]


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

