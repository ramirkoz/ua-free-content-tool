from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding='utf-8')

def write(rel: str, text: str) -> None:
    (ROOT / rel).write_text(text, encoding='utf-8')

def once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f'{label}: expected 1 match, got {n}')
    return text.replace(old, new, 1)

def between(text: str, start: str, end: str, replacement: str, label: str) -> str:
    a = text.find(start)
    b = text.find(end, a)
    if a < 0 or b < 0:
        raise RuntimeError(f'{label}: markers not found')
    return text[:a] + replacement + text[b:]

def patch_router_121() -> None:
    rel = 'content_agent/ai_router_v1_2_1.py'
    text = read(rel)
    imp = 'from .local_ai_runtime_v1_2_2 import LocalAIRuntimeError, generate_local_text'
    if imp not in text:
        text = once(text, 'from .paths import data_dir\n', 'from .paths import data_dir\n' + imp + '\n', 'router121 import')
    text = text.replace('AIModelSlot(17, "local", "local-model", "Локальний AI / llama.cpp", "local")', 'AIModelSlot(17, "local", "local-model", "Локальний AI · Ollama → llama.cpp", "local")')
    replacement = '''def _local_call(slot: AIModelSlot, cfg: AIProviderSecrets, prompt: str) -> str:\n    del slot\n    try:\n        text, _target = generate_local_text(\n            preferred_model=cfg.local_model,\n            manual_base_url=cfg.local_base_url,\n            manual_model=cfg.local_model,\n            prompt=prompt,\n            max_output_tokens=4096,\n            temperature=0.05,\n        )\n        return text\n    except LocalAIRuntimeError as exc:\n        lowered = str(exc).casefold()\n        kind = "configuration" if any(token in lowered for token in ("не налаштован", "url має бути", "локальних моделей немає")) else "temporary"\n        raise AIModelError(str(exc), kind=kind) from exc\n\n\n'''
    text = between(text, 'def _local_call(', 'def _invoke_slot(', replacement, 'router121 local')
    text = text.replace('AIModelSlot(slot.priority, slot.provider, cfg.local_model or slot.model, f"{cfg.local_model or \'Local\'} / llama.cpp", slot.family)', 'AIModelSlot(slot.priority, slot.provider, cfg.local_model or slot.model, "Локальний AI · авто: Ollama → llama.cpp", slot.family)')
    text = text.replace('key = _provider_key(slot.provider) if exc.kind in {"auth", "quota", "configuration"} else _slot_key(slot)', 'key = _provider_key(slot.provider) if exc.kind in {"auth", "configuration"} else _slot_key(slot)')
    write(rel, text)

def patch_router_122() -> None:
    rel = 'content_agent/ai_router_v1_2_2.py'
    text = read(rel)
    imp = 'from .local_ai_runtime_v1_2_2 import LocalAIRuntimeError, generate_local_text'
    if imp not in text:
        text = once(text, 'from .network import NetworkError, fetch_url\n', 'from .network import NetworkError, fetch_url\n' + imp + '\n', 'router122 import')
    replacement = '''def _local_call_limited(\n    slot: AIModelSlot,\n    cfg: AIProviderSecrets,\n    prompt: str,\n    *,\n    max_output_tokens: int,\n) -> str:\n    del slot\n    try:\n        text, _target = generate_local_text(\n            preferred_model=cfg.local_model,\n            manual_base_url=cfg.local_base_url,\n            manual_model=cfg.local_model,\n            prompt=prompt,\n            max_output_tokens=max_output_tokens,\n            temperature=0.0,\n        )\n        return text\n    except LocalAIRuntimeError as exc:\n        lowered = str(exc).casefold()\n        if "завеликий" in lowered:\n            kind = "request_too_large"\n        elif any(token in lowered for token in ("не налаштован", "url має бути", "локальних моделей немає")):\n            kind = "configuration"\n        else:\n            kind = "temporary"\n        raise AIModelError(str(exc), kind=kind) from exc\n\n\n'''
    text = between(text, 'def _local_call_limited(', 'def _invoke_limited(', replacement, 'router122 local')
    text = text.replace('AIModelSlot(slot.priority, slot.provider, cfg.local_model or slot.model, f"{cfg.local_model or \'Local\'} / llama.cpp", slot.family)', 'AIModelSlot(slot.priority, slot.provider, cfg.local_model or slot.model, "Локальний AI · авто: Ollama → llama.cpp", slot.family)')
    text = text.replace('key_name = legacy._provider_key(slot.provider) if exc.kind in {"auth", "quota", "configuration"} else legacy._slot_key(slot)', 'key_name = legacy._provider_key(slot.provider) if exc.kind in {"auth", "configuration"} else legacy._slot_key(slot)')
    write(rel, text)

def patch_duplicates() -> None:
    rel = 'content_agent/global_duplicates_v1_3_rc6.py'
    text = read(rel)
    if 'def _decode_duplicate_payload(' in text:
        return
    start = 'def parse_duplicate_clusters(raw: str, valid_ids: set[int]) -> list[DuplicateCluster]:\n'
    marker = '    result: list[DuplicateCluster] = []\n'
    a = text.find(start)
    b = text.find(marker, a)
    if a < 0 or b < 0:
        raise RuntimeError('duplicates parser markers not found')
    replacement = '''def _balanced_json_objects(value: str) -> Iterable[str]:\n    text = str(value or "")\n    for start, char in enumerate(text):\n        if char != "{":\n            continue\n        depth = 0\n        in_string = False\n        escaped = False\n        for index in range(start, len(text)):\n            current = text[index]\n            if in_string:\n                if escaped:\n                    escaped = False\n                elif current == "\\\\":\n                    escaped = True\n                elif current == '\"':\n                    in_string = False\n                continue\n            if current == '\"':\n                in_string = True\n                continue\n            if current == "{":\n                depth += 1\n            elif current == "}":\n                depth -= 1\n                if depth == 0:\n                    yield text[start : index + 1]\n                    break\n                if depth < 0:\n                    break\n\n\ndef _decode_duplicate_payload(raw: str) -> dict[str, object]:\n    cleaned = _CODE_FENCE.sub("", str(raw or "").strip()).strip()\n    candidates = [cleaned, *_balanced_json_objects(cleaned)]\n    seen: set[str] = set()\n    last_error: json.JSONDecodeError | None = None\n    for candidate in candidates:\n        value = candidate.strip()\n        if not value or value in seen:\n            continue\n        seen.add(value)\n        try:\n            payload = json.loads(value)\n        except json.JSONDecodeError as exc:\n            last_error = exc\n            continue\n        if isinstance(payload, dict) and isinstance(payload.get("clusters"), list):\n            return payload\n    raise AIRouterError("AI повернув глобальний пошук дублікатів не у валідному JSON.") from last_error\n\n\ndef parse_duplicate_clusters(raw: str, valid_ids: set[int]) -> list[DuplicateCluster]:\n    payload = _decode_duplicate_payload(raw)\n'''
    text = text[:a] + replacement + text[b:]
    write(rel, text)

def patch_ai_engine() -> None:
    rel = 'content_agent/ui/ai_engine_v1_3.py'
    text = read(rel)
    imp = 'from ..local_ai_runtime_v1_2_2 import LocalAIRuntimeError, LocalAITarget, test_local_runtime'
    if imp not in text:
        text = once(text, 'from ..models import RewriteResult\n', 'from ..models import RewriteResult\n' + imp + '\n', 'ai engine import')
    if 'self.ai_local_runtime_status_var' not in text:
        old = '        self.memory_graph_status_var = tk.StringVar(value="Редакційна пам’ять: готова до синхронізації")\n'
        new = old + '        self.ai_local_runtime_status_var = tk.StringVar(\n            value="Локальний резерв: спочатку використовується вже встановлена Ollama та її моделі; нічого автоматично не завантажується."\n        )\n'
        text = once(text, old, new, 'local status var')
    text = text.replace('text="Локальний аварійний AI", variable=self.ai_local_enabled_var', 'text="Локальний аварійний AI · Ollama автоматично", variable=self.ai_local_enabled_var')
    text = text.replace('ttk.Label(frame, text="Модель").grid(row=6, column=2, sticky="e", pady=2)', 'ttk.Label(frame, text="Запасна llama.cpp модель").grid(row=6, column=2, sticky="e", pady=2)')
    if 'textvariable=self.ai_local_runtime_status_var' not in text:
        old = '''        ttk.Entry(frame, textvariable=self.ai_provider_vars["local_model"], width=28).grid(\n            row=6, column=3, sticky="ew", padx=(8, 14), pady=2\n        )\n\n        actions = ttk.Frame(frame)\n        actions.grid(row=7, column=0, columnspan=5, sticky="w", pady=(7, 4))\n'''
        new = '''        ttk.Entry(frame, textvariable=self.ai_provider_vars["local_model"], width=28).grid(\n            row=6, column=3, sticky="ew", padx=(8, 14), pady=2\n        )\n\n        ttk.Label(frame, textvariable=self.ai_local_runtime_status_var, foreground="#555", wraplength=1120).grid(\n            row=7, column=0, columnspan=5, sticky="w", pady=(2, 4)\n        )\n\n        actions = ttk.Frame(frame)\n        actions.grid(row=8, column=0, columnspan=5, sticky="w", pady=(7, 4))\n'''
        text = once(text, old, new, 'local status label')
    if 'text="Перевірити локальний AI"' not in text:
        old = '        ttk.Button(actions, text="Тест AI Router", command=self.test_ai_router_ui).pack(side="left", padx=(6, 0))\n'
        text = once(text, old, old + '        ttk.Button(actions, text="Перевірити локальний AI", command=self.test_local_ai_ui).pack(side="left", padx=(6, 0))\n', 'local test button')
    if 'row=13, column=0, columnspan=5' not in text:
        for old, new in [
            ('row=8, column=0, columnspan=5, sticky="w", pady=(2, 5)', 'row=9, column=0, columnspan=5, sticky="w", pady=(2, 5)'),
            ('row=9, column=0, columnspan=5, sticky="ew", pady=6', 'row=10, column=0, columnspan=5, sticky="ew", pady=6'),
            ('row=10, column=0, sticky="w")', 'row=11, column=0, sticky="w")'),
            ('row=10, column=1, columnspan=4, sticky="w", padx=(10, 0)', 'row=11, column=1, columnspan=4, sticky="w", padx=(10, 0)'),
            ('row=11, column=0, columnspan=5, sticky="w", pady=(5, 2)', 'row=12, column=0, columnspan=5, sticky="w", pady=(5, 2)'),
            ('row=12, column=0, columnspan=5, sticky="w", pady=(4, 0)', 'row=13, column=0, columnspan=5, sticky="w", pady=(4, 0)'),
        ]:
            text = text.replace(old, new, 1)
    if 'def test_local_ai_ui(self)' not in text:
        method = '''    def test_local_ai_ui(self) -> None:\n        try:\n            values = self._provider_secrets_from_ui().normalized()\n            save_provider_secrets(values)\n        except Exception as exc:\n            self._show_error(exc)  # type: ignore[attr-defined]\n            return\n        if not values.local_enabled:\n            self.ai_local_runtime_status_var.set("Локальний резерв вимкнено.")\n            self.set_status("Локальний аварійний AI вимкнено.")  # type: ignore[attr-defined]\n            return\n\n        def success(result: object) -> None:\n            if not isinstance(result, LocalAITarget):\n                self.set_status(f"Неправильний результат локальної перевірки: {result}")  # type: ignore[attr-defined]\n                return\n            clear_router_cooldowns()\n            started = " · Ollama була запущена програмою" if result.started_by_app else ""\n            self.ai_local_runtime_status_var.set(\n                f"Локальний резерв готовий: {result.label}{started}. Нові моделі не встановлювалися і не завантажувалися."\n            )\n            self.refresh_ai_component_status()\n            self.set_status(f"Локальний AI працює: {result.label}")  # type: ignore[attr-defined]\n\n        def action() -> object:\n            try:\n                return test_local_runtime(\n                    preferred_model=values.local_model,\n                    manual_base_url=values.local_base_url,\n                    manual_model=values.local_model,\n                )\n            except LocalAIRuntimeError:\n                raise\n\n        self.run_async(  # type: ignore[attr-defined]\n            action,\n            success,\n            label="Перевіряю Ollama / локальний резерв",\n            done_label="Локальний AI перевірено",\n        )\n\n'''
        text = once(text, '    def clear_ai_router_cooldowns_ui(self) -> None:\n', method + '    def clear_ai_router_cooldowns_ui(self) -> None:\n', 'local test method')
    write(rel, text)

def patch_rc10() -> None:
    rel = 'content_agent/ui/v1_2_rc10_window.py'
    text = read(rel)
    text = text.replace('if str(widget.cget("text")) == "Локальний аварійний AI":', 'if str(widget.cget("text")).startswith("Локальний аварійний AI"):')
    text = text.replace('self._local_diagnostic_base_text = "Локальний аварійний AI"', 'self._local_diagnostic_base_text = "Локальний аварійний AI · Ollama автоматично"')
    write(rel, text)

def main() -> None:
    patch_router_121()
    patch_router_122()
    patch_duplicates()
    patch_ai_engine()
    patch_rc10()
    print('V122_RC2_SOURCE_PATCH_OK')

if __name__ == '__main__':
    main()
