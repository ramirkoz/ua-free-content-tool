from __future__ import annotations

import http.client
import json
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .ollama_client import OllamaClient, OllamaError, OllamaTimeoutError

OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MANUAL_BASE_URL = "http://127.0.0.1:8080/v1"
DEFAULT_MANUAL_MODEL = "local-model"

_START_LOCK = threading.Lock()
_LAST_START_ATTEMPT = 0.0


class LocalAIRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class LocalAITarget:
    engine: str
    base_url: str
    model: str
    label: str
    executable: str = ""
    started_by_app: bool = False


def _normalize_model_name(value: str) -> str:
    text = str(value or "").strip()
    return text[:-7] if text.casefold().endswith(":latest") else text


def _looks_like_embedding_model(name: str) -> bool:
    lowered = str(name or "").casefold()
    return any(
        token in lowered
        for token in (
            "embed",
            "embedding",
            "nomic-embed",
            "mxbai-embed",
            "bge-",
            "snowflake-arctic-embed",
        )
    )


def _parameter_score(name: str) -> float:
    """Prefer capable newsroom models without blindly choosing the largest one."""

    lowered = str(name or "").casefold()
    matches = re.findall(r"(?<!\d)(\d+(?:\.\d+)?)\s*b(?:\b|[-_:])", lowered)
    if not matches:
        return 50.0
    try:
        size = max(float(value) for value in matches)
    except ValueError:
        return 50.0
    if 14 <= size <= 40:
        return 100.0 + min(size, 40) / 10.0
    if 7 <= size < 14:
        return 85.0 + size / 10.0
    if 3 <= size < 7:
        return 65.0 + size / 10.0
    if 40 < size <= 80:
        return 78.0 - (size - 40) / 10.0
    if size > 80:
        return 55.0
    return 35.0 + size


def choose_ollama_model(models: list[str], preferred: str = "") -> str:
    clean = [str(item or "").strip() for item in models if str(item or "").strip()]
    if not clean:
        return ""

    wanted = _normalize_model_name(preferred)
    if wanted and wanted.casefold() not in {"local-model", "auto", "automatic"}:
        for candidate in clean:
            if _normalize_model_name(candidate).casefold() == wanted.casefold():
                return candidate

    usable = [item for item in clean if not _looks_like_embedding_model(item)] or clean

    family_bonus = {
        "qwen": 18.0,
        "gpt-oss": 17.0,
        "deepseek": 15.0,
        "gemma": 13.0,
        "llama": 12.0,
        "mistral": 10.0,
    }

    def score(item: str) -> tuple[float, int]:
        lowered = item.casefold()
        bonus = max((value for key, value in family_bonus.items() if key in lowered), default=0.0)
        # Stable tie-break: keep the API order, which usually reflects the user's
        # most recently managed models, instead of inventing another preference.
        return (_parameter_score(item) + bonus, -usable.index(item))

    return max(usable, key=score)


def find_ollama_executable() -> Path | None:
    candidates: list[Path] = []
    from_path = shutil.which("ollama")
    if from_path:
        candidates.append(Path(from_path))

    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        candidates.extend(
            (
                Path(local_app_data) / "Programs" / "Ollama" / "ollama.exe",
                Path(local_app_data) / "Programs" / "Ollama" / "ollama",
            )
        )

    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def _list_ollama_models(timeout: int = 3) -> list[str]:
    connection = http.client.HTTPConnection("127.0.0.1", 11434, timeout=max(1, int(timeout)))
    try:
        connection.request("GET", "/api/tags", headers={"Accept": "application/json"})
        response = connection.getresponse()
        body = response.read(4 * 1024 * 1024)
    except OSError as exc:
        raise OllamaError("Ollama не відповідає або не запущена локально.") from exc
    finally:
        connection.close()
    if response.status >= 400:
        raise OllamaError(f"Ollama повернула HTTP {response.status}.")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OllamaError("Ollama повернула некоректний JSON.") from exc
    if not isinstance(payload, dict):
        raise OllamaError("Відповідь Ollama повинна бути JSON-об'єктом.")
    models = payload.get("models", [])
    if not isinstance(models, list):
        return []
    return [str(item.get("name")) for item in models if isinstance(item, dict) and item.get("name")]


def _hidden_popen(command: list[str], *, cwd: Path | None = None) -> subprocess.Popen[bytes]:
    kwargs: dict[str, object] = {
        "cwd": str(cwd) if cwd else None,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) | int(
            getattr(subprocess, "DETACHED_PROCESS", 0)
        )
        kwargs["creationflags"] = creationflags
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= int(getattr(subprocess, "STARTF_USESHOWWINDOW", 1))
        startupinfo.wShowWindow = int(getattr(subprocess, "SW_HIDE", 0))
        kwargs["startupinfo"] = startupinfo
    return subprocess.Popen(command, **kwargs)  # type: ignore[arg-type]


def start_installed_ollama(*, wait_seconds: float = 15.0) -> tuple[Path, bool]:
    """Start the already installed Ollama server without installing or pulling anything."""

    global _LAST_START_ATTEMPT
    executable = find_ollama_executable()
    if executable is None:
        raise LocalAIRuntimeError("Ollama не встановлена або ollama.exe не знайдено у PATH / LocalAppData.")

    with _START_LOCK:
        try:
            _list_ollama_models()
            return executable, False
        except OllamaError:
            pass

        now = time.monotonic()
        # If another worker has just started Ollama, wait for that same process
        # instead of creating several hidden servers that race for port 11434.
        should_launch = now - _LAST_START_ATTEMPT >= 20.0
        if should_launch:
            _LAST_START_ATTEMPT = now
            try:
                _hidden_popen([str(executable), "serve"], cwd=executable.parent)
            except OSError as exc:
                raise LocalAIRuntimeError(f"Не вдалося запустити встановлену Ollama: {exc}") from exc

    deadline = time.monotonic() + max(1.0, float(wait_seconds))
    last_error = ""
    while time.monotonic() < deadline:
        try:
            _list_ollama_models()
            return executable, should_launch
        except OllamaError as exc:
            last_error = str(exc)
            time.sleep(0.5)
    raise LocalAIRuntimeError(
        "Ollama встановлена, але локальний API 127.0.0.1:11434 не запустився"
        + (f": {last_error}" if last_error else ".")
    )


def resolve_local_target(
    *,
    preferred_model: str = "",
    manual_base_url: str = DEFAULT_MANUAL_BASE_URL,
    manual_model: str = DEFAULT_MANUAL_MODEL,
    auto_start_ollama: bool = True,
) -> LocalAITarget:
    """Resolve local AI in strict order: existing Ollama -> started Ollama -> manual llama.cpp.

    This function never installs Ollama and never downloads/pulls a model. Existing
    Ollama model storage is reused exactly as configured by the user.
    """

    started_by_app = False
    executable = find_ollama_executable()
    models: list[str] = []
    ollama_reachable = False
    try:
        models = _list_ollama_models()
        ollama_reachable = True
    except OllamaError:
        if auto_start_ollama and executable is not None:
            executable, started_by_app = start_installed_ollama()
            try:
                models = _list_ollama_models()
                ollama_reachable = True
            except OllamaError as exc:
                raise LocalAIRuntimeError(str(exc)) from exc

    if models:
        model = choose_ollama_model(models, preferred_model)
        if not model:
            raise LocalAIRuntimeError("Ollama працює, але не знайдено придатної генеративної моделі.")
        return LocalAITarget(
            engine="ollama",
            base_url=OLLAMA_BASE_URL,
            model=model,
            label=f"{model} / Ollama",
            executable=str(executable or ""),
            started_by_app=started_by_app,
        )

    if ollama_reachable and not models:
        # Do not pull a surprise multi-gigabyte model behind the user's back.
        # An explicitly configured manual llama.cpp endpoint may still be used.
        if not manual_base_url or _is_default_manual_target(manual_base_url, manual_model):
            raise LocalAIRuntimeError(
                "Ollama працює, але локальних моделей немає. Програма нічого не завантажує автоматично."
            )

    base_url = str(manual_base_url or "").strip()
    model = str(manual_model or "").strip()
    if not base_url or not model or _is_default_manual_target(base_url, model):
        if executable is None:
            raise LocalAIRuntimeError(
                "Локальний AI не знайдено: Ollama не встановлена, а запасний llama.cpp endpoint не налаштований."
            )
        raise LocalAIRuntimeError(
            "Ollama не дала доступної моделі, а запасний llama.cpp endpoint не налаштований."
        )
    _validate_loopback_url(base_url)
    return LocalAITarget(
        engine="llama.cpp",
        base_url=base_url,
        model=model,
        label=f"{model} / llama.cpp",
    )


def _is_default_manual_target(base_url: str, model: str) -> bool:
    return (
        str(base_url or "").strip().rstrip("/").casefold() == DEFAULT_MANUAL_BASE_URL.rstrip("/").casefold()
        and str(model or "").strip().casefold() in {"", DEFAULT_MANUAL_MODEL.casefold()}
    )


def _validate_loopback_url(base_url: str) -> None:
    parts = urlsplit(str(base_url or "").strip())
    if parts.scheme != "http" or parts.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise LocalAIRuntimeError("Локальний AI URL має бути loopback HTTP адресою.")


def _extract_openai_text(payload: object) -> str:
    if not isinstance(payload, dict):
        raise LocalAIRuntimeError("Локальний llama.cpp повернув неправильний JSON.")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise LocalAIRuntimeError("Локальний llama.cpp не повернув choices.")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise LocalAIRuntimeError("Локальний llama.cpp не повернув message.")
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    raise LocalAIRuntimeError("Локальний llama.cpp повернув порожній текст.")


def _generate_manual_openai(
    target: LocalAITarget,
    prompt: str,
    *,
    max_output_tokens: int,
    temperature: float,
) -> str:
    _validate_loopback_url(target.base_url)
    parts = urlsplit(target.base_url)
    port = parts.port or 80
    base_path = parts.path.rstrip("/")
    path = f"{base_path}/chat/completions" if base_path.endswith("/v1") else f"{base_path}/v1/chat/completions"
    payload = json.dumps(
        {
            "model": target.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": float(temperature),
            "max_tokens": max(64, min(4096, int(max_output_tokens))),
            "stream": False,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    connection = http.client.HTTPConnection(parts.hostname, port, timeout=120)
    try:
        connection.request("POST", path or "/v1/chat/completions", body=payload, headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        body = response.read(4 * 1024 * 1024)
    except OSError as exc:
        raise LocalAIRuntimeError("Запасний llama.cpp endpoint недоступний.") from exc
    finally:
        connection.close()
    if response.status == 413:
        raise LocalAIRuntimeError("Запит завеликий для локального llama.cpp endpoint.")
    if response.status >= 400:
        raise LocalAIRuntimeError(f"Локальний llama.cpp: HTTP {response.status}.")
    try:
        return _extract_openai_text(json.loads(body.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LocalAIRuntimeError("Локальний llama.cpp повернув неправильний JSON.") from exc


def generate_local_text(
    *,
    preferred_model: str,
    manual_base_url: str,
    manual_model: str,
    prompt: str,
    max_output_tokens: int = 4096,
    temperature: float = 0.05,
) -> tuple[str, LocalAITarget]:
    target = resolve_local_target(
        preferred_model=preferred_model,
        manual_base_url=manual_base_url,
        manual_model=manual_model,
        auto_start_ollama=True,
    )
    if target.engine == "ollama":
        try:
            text = OllamaClient(target.base_url, timeout=240, load_timeout=120).generate_text(
                target.model,
                prompt,
                num_predict=max(64, min(4096, int(max_output_tokens))),
                temperature=float(temperature),
            )
        except (OllamaError, OllamaTimeoutError) as exc:
            raise LocalAIRuntimeError(str(exc)) from exc
        if not text.strip():
            raise LocalAIRuntimeError("Ollama повернула порожній текст.")
        return text.strip(), target

    return (
        _generate_manual_openai(
            target,
            prompt,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
        ).strip(),
        target,
    )


def test_local_runtime(
    *,
    preferred_model: str = "",
    manual_base_url: str = DEFAULT_MANUAL_BASE_URL,
    manual_model: str = DEFAULT_MANUAL_MODEL,
) -> LocalAITarget:
    text, target = generate_local_text(
        preferred_model=preferred_model,
        manual_base_url=manual_base_url,
        manual_model=manual_model,
        prompt="Return exactly this text and nothing else: UA_FREE_LOCAL_OK",
        max_output_tokens=64,
        temperature=0.0,
    )
    if "UA_FREE_LOCAL_OK" not in text:
        raise LocalAIRuntimeError(f"{target.label} відповів, але контрольний текст не збігся.")
    return target
