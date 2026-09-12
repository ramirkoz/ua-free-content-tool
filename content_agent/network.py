from __future__ import annotations

import http.client
import ipaddress
import json
import queue
import socket
import ssl
import threading
from dataclasses import dataclass
from typing import Callable, Iterable
from urllib.parse import urljoin, urlsplit

from .security import redact_url


class NetworkError(RuntimeError):
    pass


@dataclass(slots=True)
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes
    final_url: str

    def json(self) -> object:
        try:
            return json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise NetworkError("Remote endpoint returned invalid JSON.") from exc


def _is_public_ip(value: str) -> bool:
    # is_global also rejects shared CGNAT space (100.64.0.0/10),
    # documentation ranges and other non-routable special-use networks.
    return ipaddress.ip_address(value).is_global


def resolve_public(host: str, port: int) -> list[str]:
    try:
        rows = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise NetworkError(f"DNS resolution failed for {host}.") from exc
    addresses: list[str] = []
    for row in rows:
        address = row[4][0]
        if not _is_public_ip(address):
            raise NetworkError(f"Blocked non-public address for {host}.")
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise NetworkError(f"No usable public address for {host}.")
    return addresses

@dataclass(slots=True)
class _DNSRequest:
    resolver: Callable[[str, int], list[str]]
    host: str
    port: int
    done: threading.Event
    result: list[str] | None = None
    error: BaseException | None = None


_DNS_QUEUE: queue.Queue[_DNSRequest] = queue.Queue(maxsize=32)
_DNS_WORKERS_LOCK = threading.Lock()
_DNS_WORKERS_STARTED = False
_DNS_WORKER_COUNT = 4
_DNS_STATS_LOCK = threading.Lock()
_DNS_TIMEOUTS = 0
_DNS_REJECTIONS = 0


def _dns_worker() -> None:
    while True:
        request = _DNS_QUEUE.get()
        try:
            try:
                request.result = request.resolver(request.host, request.port)
            except BaseException as exc:
                request.error = exc
            finally:
                request.done.set()
        finally:
            _DNS_QUEUE.task_done()


def _ensure_dns_workers() -> None:
    global _DNS_WORKERS_STARTED
    if _DNS_WORKERS_STARTED:
        return
    with _DNS_WORKERS_LOCK:
        if _DNS_WORKERS_STARTED:
            return
        for index in range(_DNS_WORKER_COUNT):
            threading.Thread(
                target=_dns_worker,
                name=f"dns-worker-{index + 1}",
                daemon=True,
            ).start()
        _DNS_WORKERS_STARTED = True


def dns_resolver_stats() -> dict[str, int]:
    with _DNS_STATS_LOCK:
        return {
            "workers": _DNS_WORKER_COUNT if _DNS_WORKERS_STARTED else 0,
            "queued": _DNS_QUEUE.qsize(),
            "timeouts": _DNS_TIMEOUTS,
            "rejections": _DNS_REJECTIONS,
        }


def _resolve_with_timeout(
    resolver: Callable[[str, int], list[str]],
    host: str,
    port: int,
    timeout: float,
) -> list[str]:
    """Bound DNS without creating one abandoned thread per timed-out lookup.

    Windows ``getaddrinfo`` cannot be cancelled portably. RC5 spawned an
    unbounded daemon thread for every lookup, so pathological resolver stalls
    could accumulate native thread/handle resources. RC6 uses four fixed daemon
    workers and a bounded queue. At worst DNS service degrades; the process no
    longer creates an unlimited number of resolver threads.
    """
    global _DNS_TIMEOUTS, _DNS_REJECTIONS
    _ensure_dns_workers()
    request = _DNSRequest(resolver=resolver, host=host, port=port, done=threading.Event())
    try:
        _DNS_QUEUE.put(request, timeout=0.1)
    except queue.Full as exc:
        with _DNS_STATS_LOCK:
            _DNS_REJECTIONS += 1
        raise NetworkError(f"DNS resolver busy for {host}; bounded queue is full.") from exc

    dns_timeout = max(0.05, min(float(timeout), 12.0))
    if not request.done.wait(dns_timeout):
        with _DNS_STATS_LOCK:
            _DNS_TIMEOUTS += 1
        raise NetworkError(f"DNS resolution timed out for {host} after {dns_timeout:.0f} seconds.")
    if request.error is not None:
        error = request.error
        if isinstance(error, NetworkError):
            raise error
        if isinstance(error, OSError) and getattr(error, "errno", None) == 24:
            raise NetworkError("Local resource exhaustion: too many open files.") from error
        raise NetworkError(f"DNS resolution failed for {host}.") from error
    if not request.result:
        raise NetworkError(f"No DNS result for {host}.")
    return request.result


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, pinned_ip: str, port: int, timeout: float):
        super().__init__(host=host, port=port, timeout=timeout)
        self._pinned_ip = pinned_ip

    def connect(self) -> None:
        self.sock = socket.create_connection((self._pinned_ip, self.port), self.timeout, self.source_address)
        if self._tunnel_host:
            self._tunnel()


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, pinned_ip: str, port: int, timeout: float):
        context = ssl.create_default_context()
        super().__init__(host=host, port=port, timeout=timeout, context=context)
        self._pinned_ip = pinned_ip
        self._server_hostname = host

    def connect(self) -> None:
        raw = socket.create_connection((self._pinned_ip, self.port), self.timeout, self.source_address)
        self.sock = self._context.wrap_socket(raw, server_hostname=self._server_hostname)


def _content_type(headers: dict[str, str]) -> str:
    return headers.get("content-type", "").split(";", 1)[0].strip().lower()


def fetch_url(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: float = 30.0,
    max_bytes: int = 5 * 1024 * 1024,
    allowed_content_types: Iterable[str] | None = None,
    max_redirects: int = 4,
    allow_http_errors: bool = False,
    resolver: Callable[[str, int], list[str]] = resolve_public,
) -> HttpResponse:
    current = url
    request_headers = {"User-Agent": "UAFreeContentTool-Stabilization/2026.07.24", "Accept": "*/*"}
    if headers:
        request_headers.update(headers)

    for redirect_index in range(max_redirects + 1):
        try:
            parts = urlsplit(current)
        except ValueError as exc:
            raise NetworkError("Invalid URL.") from exc
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise NetworkError("Only absolute HTTP/HTTPS URLs are allowed.")
        if parts.username or parts.password or parts.fragment:
            raise NetworkError("URL credentials and fragments are not allowed.")
        port = parts.port or (443 if parts.scheme == "https" else 80)
        if port not in {80, 443}:
            raise NetworkError("Only ports 80 and 443 are allowed.")
        host = parts.hostname.lower().rstrip(".")
        addresses = _resolve_with_timeout(resolver, host, port, timeout)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        host_header = host if port in {80, 443} else f"{host}:{port}"
        outgoing_headers = dict(request_headers)
        outgoing_headers["Host"] = host_header

        # Do not pin the whole request to only the first DNS answer. Google and
        # other large endpoints often return both IPv6 and IPv4 addresses; a
        # Windows host may have IPv6 DNS answers while the actual route is broken.
        # Connect to the first reachable public address *before* sending the HTTP
        # request. Once any bytes may have been sent, we deliberately do not retry
        # another address here because POST uploads must not be duplicated after an
        # ambiguous transport failure.
        connection: http.client.HTTPConnection | None = None
        connect_errors: list[BaseException] = []
        for pinned_ip in addresses:
            if parts.scheme == "https":
                candidate: http.client.HTTPConnection = _PinnedHTTPSConnection(host, pinned_ip, port, timeout)
            else:
                candidate = _PinnedHTTPConnection(host, pinned_ip, port, timeout)
            try:
                candidate.connect()
            except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
                connect_errors.append(exc)
                candidate.close()
                continue
            connection = candidate
            break
        if connection is None:
            raise NetworkError(
                f"Network connection failed for {host}: no reachable address among {len(addresses)} DNS result(s)."
            ) from (connect_errors[-1] if connect_errors else None)
        try:
            connection.request(method, path, body=body, headers=outgoing_headers)
            response = connection.getresponse()
            response_headers = {key.lower(): value for key, value in response.getheaders()}
            if response.status in {301, 302, 303, 307, 308}:
                location = response_headers.get("location")
                response.read(8192)
                if not location:
                    raise NetworkError("Redirect response has no Location header.")
                if redirect_index >= max_redirects:
                    raise NetworkError("Too many redirects.")
                current = urljoin(current, location)
                if response.status == 303:
                    method, body = "GET", None
                continue
            data = response.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise NetworkError("Remote response exceeds the configured size limit.")
            if response.status >= 400 and not allow_http_errors:
                raise NetworkError(f"Remote request failed with HTTP {response.status}: {redact_url(current)}")
            if allowed_content_types:
                actual = _content_type(response_headers)
                normalized = {value.lower() for value in allowed_content_types}
                if actual not in normalized:
                    raise NetworkError(f"Unexpected content type: {actual or '<missing>'}.")
            return HttpResponse(response.status, response_headers, data, current)
        except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
            if isinstance(exc, OSError) and getattr(exc, "errno", None) == 24:
                raise NetworkError("Local resource exhaustion: too many open files.") from exc
            raise NetworkError(f"Network request failed: {redact_url(current)}") from exc
        finally:
            connection.close()
    raise NetworkError("Unreachable redirect state.")
