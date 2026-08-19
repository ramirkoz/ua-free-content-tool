from __future__ import annotations

from dataclasses import dataclass

from .local_ai_runtime_v1_2_2 import LocalAIRuntimeError, test_local_runtime
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
    "groq": "Groq",
    "cloudflare": "Cloudflare",
    "local": "Локальний AI",
}


def _provider_slot_groups() -> list[tuple[str, list[AIModelSlot]]]:
    groups: dict[str, list[AIModelSlot]] = {}
    for slot in MODEL_SLOTS:
        groups.setdefault(slot.provider, []).append(slot)
    return list(groups.items())


def _runtime_slot(slot: AIModelSlot, cfg: AIProviderSecrets) -> AIModelSlot:
    if slot.provider != "local":
        return slot
    model = cfg.local_model or slot.model
    return AIModelSlot(slot.priority, slot.provider, model, "Локальний AI · авто: Ollama → llama.cpp", slot.family)


def _status_for_error(error: AIModelError) -> str:
    if error.kind in {"auth", "configuration"}:
        return "error"
    return "warning"


def test_configured_providers() -> list[ProviderDiagnostic]:
    """Test every production provider independently without changing cooldown state.

    Multi-model providers are considered healthy when any configured model responds to the
    control prompt. Authentication/configuration failures stop immediately; model-specific
    and temporary failures fall through to the next model of the same provider.
    """

    cfg = load_provider_secrets()
    rows: list[ProviderDiagnostic] = []
    prompt = "Reply with a short non-empty plain-text health response."

    for provider, original_slots in _provider_slot_groups():
        slots = [_runtime_slot(slot, cfg) for slot in original_slots]
        label = PROVIDER_LABELS.get(provider, provider)

        if provider == "local":
            if not cfg.local_enabled:
                rows.append(ProviderDiagnostic(provider, label, "unconfigured", "вимкнено", cfg.local_model))
                continue
            try:
                target = test_local_runtime(
                    preferred_model=cfg.local_model,
                    manual_base_url=cfg.local_base_url,
                    manual_model=cfg.local_model,
                )
            except LocalAIRuntimeError as exc:
                lowered = str(exc).casefold()
                status = "error" if any(token in lowered for token in ("не налаштован", "url має бути")) else "warning"
                rows.append(ProviderDiagnostic(provider, label, status, str(exc)[:300], cfg.local_model))
            else:
                started = " · сервер запущено програмою" if target.started_by_app else ""
                rows.append(ProviderDiagnostic(provider, label, "ok", f"працює · {target.label}{started}", target.model))
            continue
        if not slots or not any(_configured(slot, cfg) for slot in slots):
            model = slots[0].model if slots else ""
            rows.append(ProviderDiagnostic(provider, label, "unconfigured", "не налаштовано", model))
            continue

        failures: list[str] = []
        terminal_status = "warning"
        terminal_model = slots[0].model
        success_row: ProviderDiagnostic | None = None

        for slot in slots:
            terminal_model = slot.model
            try:
                text = _invoke_slot(slot, cfg, prompt).strip()
                if not text:
                    failures.append(f"{slot.model}: порожня контрольна відповідь")
                    continue
            except AIModelError as exc:
                failures.append(f"{slot.model}: {exc}")
                if exc.kind in {"auth", "configuration"}:
                    terminal_status = "error"
                    break
                if exc.kind == "quota":
                    terminal_status = "warning"
                    continue
                continue
            except Exception as exc:
                failures.append(f"{slot.model}: тимчасова помилка перевірки: {exc}")
                continue

            success_row = ProviderDiagnostic(provider, label, "ok", f"API працює · відповідь отримано · {slot.model}", slot.model)
            break

        if success_row is not None:
            rows.append(success_row)
            continue

        detail = failures[-1] if failures else "провайдер не повернув успішної відповіді"
        if len(failures) > 1:
            detail += f" · перевірено моделей: {len(failures)}"
        rows.append(ProviderDiagnostic(provider, label, terminal_status, detail[:300], terminal_model))

    return rows
