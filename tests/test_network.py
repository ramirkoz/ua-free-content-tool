from __future__ import annotations

import socket

import pytest

from content_agent.network import NetworkError, fetch_url, resolve_public


def test_rejects_non_http_scheme() -> None:
    with pytest.raises(NetworkError):
        fetch_url("file:///etc/passwd")


def test_rejects_nonstandard_port() -> None:
    with pytest.raises(NetworkError):
        fetch_url("https://example.com:8443/")


def test_private_dns_result_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
    )
    with pytest.raises(NetworkError):
        resolve_public("example.com", 443)


def test_cgnat_dns_result_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("100.64.0.1", 443))],
    )
    with pytest.raises(NetworkError):
        resolve_public("example.com", 443)
