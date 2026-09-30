from __future__ import annotations

from pathlib import Path
import re


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"RC50 patch anchor missing: {label}")
    return text.replace(old, new, 1)


# 1. AI service no longer imports the deleted monkey-patch runtime.
path = Path("content_agent/v2/ai/service.py")
text = path.read_text(encoding="utf-8")
text = text.replace("from .direct_router_runtime import install_direct_router_runtime\n", "")
text = text.replace(
    "# Compatibility transport bridge. RC50 keeps this active until the direct Router\n"
    "# transport is moved into ai_router.py itself; the public V2 contract below is stable.\n"
    "install_direct_router_runtime()\n\n\n",
    "",
)
old = '''def test_active_backend() -> str:\n    settings = load_backend_settings()\n    if settings.active_backend == BACKEND_OPENROUTER:\n        return OpenRouterBackend(settings).probe()\n    if settings.active_backend == BACKEND_AGENT:\n        result = execute(\"Відповідай тільки словом OK.\", max_output_tokens=16, task_timeout_seconds=45)\n        return f\"Agent backend працює: {result.label}\"\n    from ...ai_router import test_ai_router\n\n    with _ROUTER_EXECUTION_LOCK:\n        return test_ai_router()\n'''
new = '''def test_active_backend(name: str | None = None, *, timeout_seconds: int = 45) -> str:\n    \"\"\"Probe one backend without changing the operator-selected active backend.\"\"\"\n    settings = load_backend_settings()\n    backend_name = str(name or settings.active_backend or BACKEND_ROUTER)\n    if backend_name == BACKEND_OPENROUTER:\n        return OpenRouterBackend(settings).probe()\n    if backend_name == BACKEND_AGENT:\n        result = _AgentAIBackend().run(\n            AIRequest(\n                prompt=\"Відповідай тільки словом OK.\",\n                max_output_tokens=16,\n                task_timeout_seconds=max(3, int(timeout_seconds)),\n            )\n        )\n        return f\"Agent backend працює: {result.label}\"\n    from ...ai_router import test_ai_router\n\n    with _ROUTER_EXECUTION_LOCK:\n        return test_ai_router()\n'''
text = replace_once(text, old, new, "test_active_backend")
path.write_text(text, encoding="utf-8")


# 2. Move direct provider transport into the canonical ai_router module.
path = Path("content_agent/ai_router.py")
text = path.read_text(encoding="utf-8")
anchor = "from .paths import data_dir\n"
if "from .v2.ai.provider_api import" not in text:
    text = replace_once(
        text,
        anchor,
        anchor + "from .v2.ai.provider_api import ProviderAPIError, gemini_generate, openai_compatible_chat\n",
        "provider_api import",
    )
old_slots = '''MODEL_SLOTS: tuple[AIModelSlot, ...] = (\n    AIModelSlot(1, \"codex\", \"codex-chatgpt\", \"Codex / ChatGPT\", \"codex\"),\n    AIModelSlot(2, \"gemini\", \"gemini-3.5-flash\", \"Gemini 3.5 Flash / Google\", \"gemini\"),\n    AIModelSlot(3, \"nvidia\", \"nvidia/nemotron-3-ultra-550b-a55b\", \"Nemotron 3 Ultra 550B / NVIDIA\"),\n    AIModelSlot(4, \"nvidia\", \"nvidia/nemotron-3-super-120b-a12b\", \"Nemotron 3 Super 120B / NVIDIA\"),\n    AIModelSlot(5, \"groq\", \"openai/gpt-oss-120b\", \"GPT-OSS 120B / Groq\"),\n    AIModelSlot(6, \"groq\", \"qwen/qwen3.6-27b\", \"Qwen 3.6 27B / Groq\"),\n    AIModelSlot(7, \"cloudflare\", \"@cf/nvidia/nemotron-3-120b-a12b\", \"Nemotron 3 120B / Cloudflare\"),\n    AIModelSlot(8, \"cloudflare\", \"@cf/zai-org/glm-4.7-flash\", \"GLM-4.7 Flash / Cloudflare\"),\n    AIModelSlot(9, \"local\", \"local-model\", \"Локальний AI · Ollama → llama.cpp\", \"local\"),\n)'''
new_slots = '''MODEL_SLOTS: tuple[AIModelSlot, ...] = (\n    AIModelSlot(1, \"codex\", \"codex-chatgpt\", \"Codex / ChatGPT\", \"codex\"),\n    AIModelSlot(2, \"gemini\", \"gemini-2.5-flash-lite\", \"Gemini 2.5 Flash Lite / Google\", \"gemini\"),\n    AIModelSlot(3, \"nvidia\", \"nvidia/nemotron-3-super-120b-a12b\", \"Nemotron 3 Super 120B / NVIDIA\"),\n    AIModelSlot(4, \"groq\", \"openai/gpt-oss-120b\", \"GPT-OSS 120B / Groq\"),\n    AIModelSlot(5, \"groq\", \"qwen/qwen3-32b\", \"Qwen 3 32B / Groq\"),\n    AIModelSlot(6, \"cloudflare\", \"@cf/meta/llama-4-scout-17b-16e-instruct\", \"Llama 4 Scout / Cloudflare\"),\n    AIModelSlot(7, \"cloudflare\", \"@cf/qwen/qwen3-30b-a3b-fp8\", \"Qwen 3 30B / Cloudflare\"),\n    AIModelSlot(8, \"local\", \"local-model\", \"Локальний AI · Ollama → llama.cpp\", \"local\"),\n)'''
text = replace_once(text, old_slots, new_slots, "MODEL_SLOTS")

openai_re = re.compile(r"def _openai_call\(.*?\n\n(?=def _gemini_call\()", re.S)
openai_new = '''def _openai_call(\n    slot: AIModelSlot,\n    cfg: AIProviderSecrets,\n    prompt: str,\n    *,\n    max_output_tokens: int,\n    timeout_seconds: int,\n) -> str:\n    api_key = (\n        cfg.nvidia_api_key if slot.provider == \"nvidia\"\n        else cfg.groq_api_key if slot.provider == \"groq\"\n        else cfg.cloudflare_api_token if slot.provider == \"cloudflare\"\n        else \"\"\n    )\n    try:\n        reply = openai_compatible_chat(\n            slot.provider,\n            model=slot.model,\n            api_key=api_key,\n            account_id=cfg.cloudflare_account_id,\n            prompt=prompt,\n            max_output_tokens=max_output_tokens,\n            timeout_seconds=timeout_seconds,\n        )\n        return str(reply.text or \"\").strip()\n    except ProviderAPIError as exc:\n        raise AIModelError(str(exc), kind=exc.kind, retry_after=exc.retry_after) from exc\n\n\n'''
text, count = openai_re.subn(openai_new, text, count=1)
if count != 1:
    raise SystemExit("RC50 patch could not replace _openai_call")

gemini_re = re.compile(r"def _gemini_call\(.*?\n\n(?=def _classify_codex_error\()", re.S)
gemini_new = '''def _gemini_call(\n    slot: AIModelSlot,\n    cfg: AIProviderSecrets,\n    prompt: str,\n    *,\n    max_output_tokens: int,\n    timeout_seconds: int,\n) -> str:\n    try:\n        reply = gemini_generate(\n            model=slot.model,\n            api_key=cfg.gemini_api_key,\n            prompt=prompt,\n            max_output_tokens=max_output_tokens,\n            timeout_seconds=timeout_seconds,\n        )\n        return str(reply.text or \"\").strip()\n    except ProviderAPIError as exc:\n        raise AIModelError(str(exc), kind=exc.kind, retry_after=exc.retry_after) from exc\n\n\n'''
text, count = gemini_re.subn(gemini_new, text, count=1)
if count != 1:
    raise SystemExit("RC50 patch could not replace _gemini_call")
path.write_text(text, encoding="utf-8")

print("RC50 checkpoint 3 patch applied")
