from __future__ import annotations

import json
import re
import socket
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class OllamaError(RuntimeError):
    pass


class OllamaTimeoutError(OllamaError):
    """Raised when a local model is simply too slow for an interactive rewrite."""


def _model_key(value: str) -> str:
    name = str(value or "").strip()
    return name[:-7] if name.endswith(":latest") else name


# Ollama behaves poorly when a background preload and a foreground generation hit
# the same small machine at once. Serializing local model operations prevents two
# 4B models from fighting over RAM and CPU while the UI merely reports "timed out".
_OLLAMA_OPERATION_LOCK = threading.RLock()


def _strip_code_fence(value: str) -> str:
    text = value.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _extract_jsonish_string(text: str, key: str) -> str:
    """Recover one string field from complete or truncated model JSON."""

    match = re.search(rf'(?is)["\']{re.escape(key)}["\']\s*:\s*"', text)
    if not match:
        return ""
    start = match.end()
    raw: list[str] = []
    escaped = False
    closed = False
    for char in text[start:]:
        if escaped:
            raw.append("\\" + char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            closed = True
            break
        raw.append(char)
    value = "".join(raw)
    escaped_value = value.replace("\r", "\\r").replace("\n", "\\n")
    try:
        return str(json.loads('"' + escaped_value + '"')).strip()
    except json.JSONDecodeError:
        value = re.sub(r"\\n", "\n", value)
        value = re.sub(r"\\r", "\r", value)
        value = re.sub(r"\\t", "\t", value)
        value = value.replace('\\"', '"').replace("\\\\", "\\")
        return value.strip() if closed or value else ""


def _fact_card_from_text(text: str, limit: int = 600) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    sentence_end = max(value.rfind(". ", 0, limit), value.rfind("! ", 0, limit), value.rfind("? ", 0, limit))
    if sentence_end >= 80:
        return value[: sentence_end + 1].strip()
    cut = value.rfind(" ", 0, limit - 1)
    if cut < 80:
        cut = limit - 1
    return value[:cut].rstrip(" ,;:-") + "…"


def _decode_rewrite_payload(response_text: str) -> dict[str, object]:
    text = _strip_code_fence(response_text)
    if not text:
        raise OllamaError("Ollama повернула порожній текст.")

    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        decoded = None
    if isinstance(decoded, dict):
        return decoded

    jsonish = text.lstrip().startswith("{") or bool(
        re.search(r'(?is)["\'](?:headline|fact_card|rewrite)["\']\s*:', text)
    )
    if jsonish:
        headline = _extract_jsonish_string(text, "headline")
        fact_card = _extract_jsonish_string(text, "fact_card")
        rewrite = _extract_jsonish_string(text, "rewrite")
        if rewrite:
            return {"headline": headline, "fact_card": fact_card or _fact_card_from_text(rewrite), "rewrite": rewrite}
        raise OllamaError(
            "Ollama повернула незавершену структуровану відповідь без тексту рерайту. "
            "Спробуйте повторити рерайт; сирий JSON не збережено."
        )

    headline = ""
    rewrite = ""
    fact_card = ""
    headline_match = re.search(r"(?im)^\s*(?:ЗАГОЛОВОК|HEADLINE)\s*:\s*(.+?)\s*$", text)
    text_match = re.search(r"(?ims)^\s*(?:ТЕКСТ|РЕРАЙТ|TEXT|ARTICLE)\s*:\s*(.+)\Z", text)
    facts_match = re.search(
        r"(?ims)^\s*(?:ФАКТИ|ФАКТ-КАРТКА|FACTS|FACT CARD)\s*:\s*(.+?)(?=^\s*(?:ТЕКСТ|РЕРАЙТ|TEXT|ARTICLE)\s*:|\Z)",
        text,
    )
    if headline_match:
        headline = headline_match.group(1).strip()
    if text_match:
        rewrite = text_match.group(1).strip()
    if facts_match:
        fact_card = facts_match.group(1).strip()
    if not rewrite:
        lines = [line.rstrip() for line in text.splitlines()]
        if lines and not headline:
            first = lines[0].strip()
            if 0 < len(first) <= 220:
                headline = first.removeprefix("ЗАГОЛОВОК:").strip()
                rewrite = "\n".join(lines[1:]).strip()
        if not rewrite:
            rewrite = text
    if not fact_card:
        fact_card = _fact_card_from_text(rewrite)
    return {"headline": headline, "fact_card": fact_card, "rewrite": rewrite}


class OllamaClient:
    def __init__(self, base_url: str, timeout: int = 240, load_timeout: int = 120):
        self.base_url = base_url.rstrip("/")
        self.timeout = max(20, int(timeout))
        self.load_timeout = max(20, int(load_timeout))
        parts = urlsplit(self.base_url)
        if parts.scheme != "http" or parts.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise OllamaError("Ollama має використовувати локальну loopback HTTP-адресу.")

    def _request(self, path: str, payload: dict[str, object] | None = None) -> dict[str, object]:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=data,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="GET" if payload is None else "POST",
        )
        try:
            with urlopen(request, timeout=min(self.load_timeout, 20)) as response:
                body = response.read(8 * 1024 * 1024)
        except HTTPError as exc:
            raise OllamaError(f"Ollama повернула HTTP {exc.code}.") from exc
        except (URLError, TimeoutError, socket.timeout) as exc:
            raise OllamaError("Ollama не відповідає або не запущена локально.") from exc
        try:
            result = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OllamaError("Ollama повернула некоректний JSON.") from exc
        if not isinstance(result, dict):
            raise OllamaError("Відповідь Ollama повинна бути JSON-об'єктом.")
        if result.get("error"):
            raise OllamaError(str(result["error"]))
        return result

    def list_models(self) -> list[str]:
        payload = self._request("/api/tags")
        models = payload.get("models", [])
        if not isinstance(models, list):
            return []
        return [str(item.get("name")) for item in models if isinstance(item, dict) and item.get("name")]

    def list_running_models(self) -> list[str]:
        payload = self._request("/api/ps")
        models = payload.get("models", [])
        if not isinstance(models, list):
            return []
        result: list[str] = []
        for item in models:
            if not isinstance(item, dict):
                continue
            value = item.get("name") or item.get("model")
            if value:
                result.append(str(value))
        return result

    def is_model_loaded(self, model: str) -> bool:
        wanted = _model_key(model)
        if not wanted:
            return False
        try:
            return any(_model_key(item) == wanted for item in self.list_running_models())
        except OllamaError:
            return False

    def preload_model(self, model: str) -> None:
        model = str(model or "").strip()
        if not model:
            raise OllamaError("Спочатку оберіть установлену модель Ollama.")
        with _OLLAMA_OPERATION_LOCK:
            if self.is_model_loaded(model):
                return
            payload = {
                "model": model,
                "prompt": "",
                "stream": False,
                "think": False,
                "keep_alive": "30m",
                "options": {"num_ctx": 2048, "num_predict": 1},
            }
            request = Request(
                self.base_url + "/api/generate",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                method="POST",
            )
            try:
                with urlopen(request, timeout=self.load_timeout) as response:
                    body = response.read(2 * 1024 * 1024)
            except HTTPError as exc:
                raise OllamaError(f"Ollama не завантажила модель «{model}»: HTTP {exc.code}.") from exc
            except (URLError, TimeoutError, socket.timeout) as exc:
                raise OllamaTimeoutError(
                    f"Модель «{model}» не завантажилася за {self.load_timeout} секунд. "
                    "Перевірте ollama ps та обсяг вільної оперативної пам'яті."
                ) from exc
            try:
                result = json.loads(body.decode("utf-8")) if body else {}
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise OllamaError("Ollama повернула некоректну відповідь під час завантаження моделі.") from exc
            if isinstance(result, dict) and result.get("error"):
                raise OllamaError(str(result["error"]))

    def generate_text(
        self,
        model: str,
        prompt: str,
        *,
        num_predict: int = 512,
        temperature: float = 0.05,
    ) -> str:
        if not model:
            raise OllamaError("Спочатку оберіть установлену модель Ollama.")
        with _OLLAMA_OPERATION_LOCK:
            self.preload_model(model)
            if len(prompt) <= 3_500:
                context_window = 1536
            elif len(prompt) <= 7_000:
                context_window = 2048
            else:
                context_window = 3072
            payload = {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "think": False,
                "keep_alive": "30m",
                "options": {
                    "temperature": float(temperature),
                    "top_p": 0.9,
                    "repeat_penalty": 1.04,
                    "num_ctx": context_window,
                    "num_predict": max(32, int(num_predict)),
                },
            }
            request = Request(
                self.base_url + "/api/generate",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                method="POST",
            )
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    body = response.read(8 * 1024 * 1024)
            except HTTPError as exc:
                raise OllamaError(f"Ollama повернула HTTP {exc.code}.") from exc
            except (URLError, TimeoutError, socket.timeout) as exc:
                raise OllamaTimeoutError(f"Ollama не завершила локальне AI-завдання за {self.timeout} секунд.") from exc
            try:
                result = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise OllamaError("Ollama повернула некоректний JSON-конверт.") from exc
            if not isinstance(result, dict):
                raise OllamaError("Відповідь Ollama повинна бути JSON-об'єктом.")
            if result.get("error"):
                raise OllamaError(str(result["error"]))
            return _strip_code_fence(str(result.get("response") or "").strip())

    def generate_json(
        self,
        model: str,
        prompt: str,
        schema: dict[str, object],
        *,
        num_predict: int = 384,
        temperature: float = 0.1,
    ) -> dict[str, object]:
        del schema
        if not model:
            raise OllamaError("Спочатку оберіть установлену модель Ollama.")
        with _OLLAMA_OPERATION_LOCK:
            self.preload_model(model)
            if len(prompt) <= 4_500:
                context_window = 2048
            elif len(prompt) <= 12_000:
                context_window = 4096
            else:
                context_window = 6144
            payload = {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "think": False,
                "keep_alive": "30m",
                "options": {
                    "temperature": float(temperature),
                    "top_p": 0.9,
                    "repeat_penalty": 1.06,
                    "num_ctx": context_window,
                    "num_predict": max(64, int(num_predict)),
                },
            }
            request = Request(
                self.base_url + "/api/generate",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                method="POST",
            )
            started = time.monotonic()
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    body = response.read(8 * 1024 * 1024)
            except HTTPError as exc:
                raise OllamaError(f"Ollama повернула HTTP {exc.code}.") from exc
            except (URLError, TimeoutError, socket.timeout) as exc:
                raise OllamaTimeoutError(f"Ollama не завершила один рерайт за {self.timeout} секунд.") from exc
            elapsed = time.monotonic() - started
            try:
                result = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise OllamaError("Ollama повернула некоректний JSON-конверт.") from exc
            if not isinstance(result, dict):
                raise OllamaError("Відповідь Ollama повинна бути JSON-об'єктом.")
            if result.get("error"):
                raise OllamaError(str(result["error"]))
            response_text = str(result.get("response") or "").strip()
            decoded = _decode_rewrite_payload(response_text)
            decoded["_elapsed_seconds"] = round(elapsed, 1)
            return decoded
