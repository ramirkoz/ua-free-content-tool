from __future__ import annotations

from dataclasses import dataclass

from .ai_router_v1_2_1 import (
    AIModelError,
    AIModelSlot,
    AIProviderSecrets,
    MODEL_SLOTS,
    _configured,
    _invoke_slot,
    load_provider_secrets,
)


@dataclass(frozen=True, slots=True)
class ProviderDiagnostic:
    provider: str
    label: str
    status: str
    detail: str
    model: str = ""


PROVIDER_LABELS: dict[str, str] = {
    "codex": "Codex / ChatGPT",
    "gemini": "Google Gemini",
    "nvidia": "NVIDIA NIM",
    "sambanova": "SambaNova",
    "cerebras": "Cerebras",
    "groq": "Groq",
    "openrouter": "OpenRouter",
    "cloudflare": "Cloudflare",
    "local": "Локальний AI",
}


def _representative_slots() -> list[AIModelSlot]:
    result: list[AIModelSlot] = []
    seen: set[str] = set()
    for slot in MODEL_SLOTS:
        if slot.provider in seen:
            continue
        seen.add(slot.provider)
        result.append(slot)
    return result


def _runtime_slot(slot: AIModelSlot, cfg: AIProviderSecrets) -> AIModelSlot:
    if slot.provider != "local":
        return slot
    model = cfg.local_model or slot.model
    return AIModelSlot(slot.priority, slot.provider, model, f"{model or 'Local'} / llama.cpp", slot.family)


def _status_for_error(error: AIModelError) -> str:
    if error.kind in {"auth", "configuration"}:
        return "error"
    return "warning"


def test_configured_providers() -> list[ProviderDiagnostic]:
    """Test every configured provider independently without changing router cooldown state."""
    cfg = load_provider_secrets()
    rows: list[ProviderDiagnostic] = []
    prompt = "Return exactly this text and nothing else: UA_FREE_PROVIDER_OK"

    for original in _representative_slots():
        slot = _runtime_slot(original, cfg)
        label = PROVIDER_LABELS.get(slot.provider, slot.provider)
        if not _configured(slot, cfg):
            rows.append(ProviderDiagnostic(slot.provider, label, "unconfigured", "не налаштовано", slot.model))
            continue
        try:
            text = _invoke_slot(slot, cfg, prompt).strip()
            if "UA_FREE_PROVIDER_OK" not in text:
                rows.append(
                    ProviderDiagnostic(
                        slot.provider,
                        label,
                        "warning",
                        "провайдер відповів, але контрольний текст не збігся",
                        slot.model,
                    )
                )
                continue
        except AIModelError as exc:
            rows.append(
                ProviderDiagnostic(
                    slot.provider,
                    label,
                    _status_for_error(exc),
                    str(exc)[:300],
                    slot.model,
                )
            )
            continue
        except Exception as exc:
            rows.append(
                ProviderDiagnostic(
                    slot.provider,
                    label,
                    "warning",
                    f"тимчасова помилка перевірки: {exc}"[:300],
                    slot.model,
                )
            )
            continue

        rows.append(ProviderDiagnostic(slot.provider, label, "ok", f"працює · {slot.model}", slot.model))

    return rows
