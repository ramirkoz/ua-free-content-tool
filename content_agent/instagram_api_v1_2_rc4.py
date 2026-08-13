from __future__ import annotations

from dataclasses import dataclass

from .network import NetworkError, fetch_url


class InstagramError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class InstagramProfile:
    user_id: str
    username: str
    account_type: str
