from __future__ import annotations

import json
from datetime import datetime

from ..ai.contracts import AITask
from ..ai.openrouter_backend import OpenRouterBackend
from ..ai.settings import load_backend_settings


def local_markdown_report(status: dict, incidents: list[dict[str, str]], *, event: str) -> str:
    instance = status.get("instance", {}) if isinstance(status.get("instance"), dict) else {}
    content = status.get("content", {}) if isinstance(status.get("content"), dict) else {}
    runtime = status.get("runtime", {}) if isinstance(status.get("runtime"), dict) else {}
    ai = status.get("ai", {}) if isinstance(status.get("ai"), dict) else {}
    lines = [
        f"# UA FREE Content Tool V2 — {event}",
        "",
        f"- timestamp: {status.get('generated_at', '')}",
        f"- version: {status.get('version', '')}",
        f"- instance: {instance.get('instance_name', '')}",
        f"- AI backend: {ai.get('active_backend', '')}",
        f"- today articles: {content.get('today_articles', '')}",
        f"- source errors: {content.get('source_errors_active', '')}/{content.get('enabled_sources', '')}",
        f"- worker alive: {runtime.get('worker_alive', '')}",
        f"- UI lag: {runtime.get('ui_lag_seconds', '')}s",
        "",
        "## Incidents",
    ]
    if incidents:
        for item in incidents:
            lines.append(f"- **{item.get('severity','')} {item.get('code','')}**: {item.get('detail','')}")
    else:
        lines.append("- Активних інцидентів немає.")
    lines.extend([
        "",
        "## Raw status",
        "```json",
        json.dumps(status, ensure_ascii=False, indent=2)[:24000],
        "```",
    ])
    return "\n".join(lines)


def analyze_with_openrouter(status: dict, incidents: list[dict[str, str]], *, event: str) -> str:
    base = local_markdown_report(status, incidents, event=event)
    settings = load_backend_settings()
    backend = OpenRouterBackend(settings)
    if not backend.configured():
        return base + "\n\n> OpenRouter analyzer не запущено: API key не налаштовано."
    prompt = f"""Ти технічний Supervisor Analyzer програми UA FREE Content Tool V2.
Отримуєш лише телеметрію, не керуєш програмою і не змінюєш дані.
Зроби короткий, але технічно змістовний Markdown-звіт українською для розробника.
Обов'язково: подія; що реально працює; що зламано/деградує; найімовірніша причина; ризик втрати/дублювання/зависання; конкретні технічні докази; 3-7 пріоритетних дій.
Не вигадуй фактів, яких немає в JSON. Якщо причин недостатньо, так і напиши.
EVENT: {event}
INCIDENTS: {json.dumps(incidents, ensure_ascii=False)}
STATUS JSON:
{json.dumps(status, ensure_ascii=False)[:22000]}
Поверни тільки Markdown-звіт."""
    try:
        result = backend.run(prompt, max_output_tokens=1100, timeout_seconds=65, task=AITask.SUPERVISOR)
        return result.text.strip()
    except Exception as exc:
        return base + f"\n\n> OpenRouter analyzer не завершився: {exc}"
