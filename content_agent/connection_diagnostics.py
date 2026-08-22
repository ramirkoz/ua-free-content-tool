from __future__ import annotations

from dataclasses import dataclass
import queue
import threading
import time
from typing import Callable

from .config import AppConfig
from .google_drive import (
    GoogleDriveError,
    GoogleDriveProfile,
    inspect_google_drive_connection,
)
from .platform_setup import (
    LinkedInProfile,
    MetaPage,
    MetaProfile,
    PlatformSetupError,
    TelegramProfile,
    ThreadsProfile,
    inspect_linkedin_token,
    inspect_meta_token,
    inspect_telegram_bot,
    inspect_threads_token,
)
from .trends import check_threads_keyword_access

STATUS_OK = "ok"
STATUS_REPLACE = "replace"
STATUS_ATTENTION = "attention"
STATUS_TEMPORARY = "temporary"
STATUS_NOT_CONFIGURED = "not_configured"

# The five live checks run in parallel. 45 seconds is deliberately longer than the
# longest normal platform probe (Telegram performs several 12 s requests), but it
# prevents one provider from making the whole diagnostics panel look frozen forever.
DIAGNOSTIC_HARD_TIMEOUT_SECONDS = 45.0


@dataclass(slots=True, frozen=True)
class ConnectionDiagnostic:
    key: str
    label: str
    status: str
    message: str

    @property
    def requires_user_action(self) -> bool:
        return self.status in {STATUS_REPLACE, STATUS_ATTENTION}


@dataclass(slots=True, frozen=True)
class ConnectionDiagnosticsReport:
    items: tuple[ConnectionDiagnostic, ...]
    meta_profile: MetaProfile | None = None
    meta_pages: tuple[MetaPage, ...] = ()
    threads_profile: ThreadsProfile | None = None
    linkedin_profile: LinkedInProfile | None = None
    telegram_profile: TelegramProfile | None = None
    google_profile: GoogleDriveProfile | None = None

    @property
    def action_items(self) -> tuple[ConnectionDiagnostic, ...]:
        return tuple(item for item in self.items if item.requires_user_action)

    @property
    def temporary_items(self) -> tuple[ConnectionDiagnostic, ...]:
        return tuple(item for item in self.items if item.status == STATUS_TEMPORARY)


@dataclass(slots=True, frozen=True)
class _ProbeResult:
    item: ConnectionDiagnostic
    meta_profile: MetaProfile | None = None
    meta_pages: tuple[MetaPage, ...] = ()
    threads_profile: ThreadsProfile | None = None
    linkedin_profile: LinkedInProfile | None = None
    telegram_profile: TelegramProfile | None = None
    google_profile: GoogleDriveProfile | None = None


_NETWORK_MARKERS = (
    "network request failed",
    "dns resolution failed",
    "no usable public address",
    "timed out",
    "timeout",
    "не відповів",
    "мереж",
    "dns",
)
_TOKEN_MARKERS = (
    "invalid oauth",
    "invalid access token",
    "invalid token",
    "token has expired",
    "expired token",
    "access token expired",
    "oauth token is invalid",
    "token revoked",
    "session has been invalidated",
    "error validating access token",
    "unauthorized",
    "недійсний",
    "простроч",
    "відкликан",
)
_PERMISSION_MARKERS = (
    "permission",
    "not enough",
    "insufficient",
    "pages_manage_posts",
    "pages_show_list",
    "administrator",
    "can_post_messages",
    "право публікувати",
    "не є адміністратором",
    "дозвол",
)


def _contains(message: str, markers: tuple[str, ...]) -> bool:
    lowered = message.casefold()
    return any(marker.casefold() in lowered for marker in markers)


def _platform_error_item(
    key: str,
    label: str,
    error: PlatformSetupError,
    *,
    permission_requires_new_token: bool = True,
) -> ConnectionDiagnostic:
    message = " ".join(str(error).split())
    if (
        error.http_status == 401
        or error.code in {102, 190}
        or (key == "telegram" and (error.http_status == 404 or error.code == 404))
        or _contains(message, _TOKEN_MARKERS)
    ):
        if key in {"facebook", "threads"}:
            guidance = (
                "Токен Meta прострочено, відкликано або він більше не належить цьому застосунку. "
                "Створіть новий токен. Після підключення програма спробує обміняти короткий токен на довготривалий. "
            )
            return ConnectionDiagnostic(
                key,
                label,
                STATUS_REPLACE,
                guidance + "Технічна відповідь Meta: " + message,
            )
        return ConnectionDiagnostic(key, label, STATUS_REPLACE, f"Токен треба замінити: {message}")
    if error.http_status == 403 or _contains(message, _PERMISSION_MARKERS):
        status = STATUS_REPLACE if permission_requires_new_token else STATUS_ATTENTION
        prefix = (
            "Потрібен новий токен або додаткові дозволи"
            if status == STATUS_REPLACE
            else "Потрібно виправити права доступу"
        )
        return ConnectionDiagnostic(key, label, status, f"{prefix}: {message}")
    if _contains(message, _NETWORK_MARKERS):
        return ConnectionDiagnostic(
            key,
            label,
            STATUS_TEMPORARY,
            f"Не вдалося перевірити через мережу або API; токен автоматично не відхилено: {message}",
        )
    return ConnectionDiagnostic(
        key,
        label,
        STATUS_TEMPORARY,
        f"Платформа не підтвердила підключення; токен автоматично не відхилено: {message}",
    )


def _not_configured(key: str, label: str, message: str) -> ConnectionDiagnostic:
    return ConnectionDiagnostic(key, label, STATUS_NOT_CONFIGURED, message)


def _probe_facebook(config: AppConfig) -> _ProbeResult:
    if not config.meta_user_access_token.strip():
        return _ProbeResult(_not_configured("facebook", "Facebook", "User Access Token не збережено."))
    try:
        profile, pages = inspect_meta_token(
            config.meta_user_access_token,
            config.meta_graph_version or "v24.0",
        )
        page_tuple = tuple(pages)
        return _ProbeResult(
            ConnectionDiagnostic(
                "facebook",
                "Facebook",
                STATUS_OK,
                f"Токен актуальний; доступно сторінок: {len(page_tuple)}. Page tokens оновлено з Meta.",
            ),
            meta_profile=profile,
            meta_pages=page_tuple,
        )
    except PlatformSetupError as exc:
        return _ProbeResult(_platform_error_item("facebook", "Facebook", exc))


def _probe_threads(config: AppConfig) -> _ProbeResult:
    if not config.threads_token.strip():
        return _ProbeResult(_not_configured("threads", "Threads", "Access token не збережено."))
    try:
        profile = inspect_threads_token(config.threads_token)
        trend_detail = ""
        trend_status = STATUS_OK
        if config.threads_trend_search_enabled:
            available, detail = check_threads_keyword_access(config.threads_token)
            if available:
                trend_detail = " Пошук трендів також працює."
            elif _contains(detail, _NETWORK_MARKERS):
                trend_status = STATUS_TEMPORARY
                trend_detail = f" Профіль працює, але пошук трендів тимчасово не перевірено: {detail}"
            else:
                trend_status = STATUS_REPLACE
                trend_detail = (
                    " Профіль працює, але для пошуку трендів потрібен токен із дозволом "
                    f"threads_keyword_search: {detail}"
                )
        return _ProbeResult(
            ConnectionDiagnostic(
                "threads",
                "Threads",
                trend_status,
                f"Профіль @{profile.username or profile.id} підтверджено.{trend_detail}",
            ),
            threads_profile=profile,
        )
    except PlatformSetupError as exc:
        return _ProbeResult(_platform_error_item("threads", "Threads", exc))


def _probe_linkedin(config: AppConfig) -> _ProbeResult:
    if not config.linkedin_token.strip():
        return _ProbeResult(_not_configured("linkedin", "LinkedIn", "Access Token не збережено."))
    try:
        profile = inspect_linkedin_token(config.linkedin_token)
        return _ProbeResult(
            ConnectionDiagnostic(
                "linkedin",
                "LinkedIn",
                STATUS_OK,
                f"Токен актуальний; профіль «{profile.name}» підтверджено.",
            ),
            linkedin_profile=profile,
        )
    except PlatformSetupError as exc:
        return _ProbeResult(_platform_error_item("linkedin", "LinkedIn", exc))


def _probe_telegram(config: AppConfig) -> _ProbeResult:
    if not config.telegram_bot_token.strip() or not config.telegram_chat_id.strip():
        return _ProbeResult(
            _not_configured("telegram", "Telegram", "Bot token або канал не налаштовано.")
        )
    try:
        profile = inspect_telegram_bot(config.telegram_bot_token, config.telegram_chat_id)
        return _ProbeResult(
            ConnectionDiagnostic(
                "telegram",
                "Telegram",
                STATUS_OK,
                f"Бот @{profile.username} має право публікувати в «{profile.target_title}».",
            ),
            telegram_profile=profile,
        )
    except PlatformSetupError as exc:
        return _ProbeResult(
            _platform_error_item(
                "telegram",
                "Telegram",
                exc,
                permission_requires_new_token=False,
            )
        )


def _probe_google_drive(config: AppConfig) -> _ProbeResult:
    if not config.google_client_id.strip() or not config.google_refresh_token.strip():
        return _ProbeResult(_not_configured("google_drive", "Google Drive", "Google Drive не підключено."))
    try:
        profile = inspect_google_drive_connection(
            config.google_client_id,
            config.google_client_secret,
            config.google_refresh_token,
        )
        account = profile.account_email or profile.display_name or "акаунт підтверджено"
        return _ProbeResult(
            ConnectionDiagnostic(
                "google_drive",
                "Google Drive",
                STATUS_OK,
                f"Refresh token актуальний; {account}.",
            ),
            google_profile=profile,
        )
    except GoogleDriveError as exc:
        message = " ".join(str(exc).split())
        if _contains(message, _NETWORK_MARKERS):
            status = STATUS_TEMPORARY
            detail = f"Не вдалося перевірити через мережу; токен автоматично не відхилено: {message}"
        elif _contains(message, _TOKEN_MARKERS) or "invalid_grant" in message.casefold():
            status = STATUS_REPLACE
            detail = f"Потрібно повторно підключити Google Drive: {message}"
        else:
            status = STATUS_ATTENTION
            detail = f"Потрібно перевірити доступ Google Drive: {message}"
        return _ProbeResult(ConnectionDiagnostic("google_drive", "Google Drive", status, detail))


_PROBES: tuple[tuple[str, str, Callable[[AppConfig], _ProbeResult]], ...] = (
    ("facebook", "Facebook", _probe_facebook),
    ("threads", "Threads", _probe_threads),
    ("linkedin", "LinkedIn", _probe_linkedin),
    ("telegram", "Telegram", _probe_telegram),
    ("google_drive", "Google Drive", _probe_google_drive),
)


def diagnose_connections(config: AppConfig) -> ConnectionDiagnosticsReport:
    """Run read-only live checks without allowing one platform to freeze all others.

    Each provider gets its own daemon thread and its own network timeouts. The aggregate
    diagnostic has a hard wall-clock bound, and a timed-out provider is reported as a
    temporary check failure rather than silently holding the Settings page forever.
    """

    result_queue: queue.Queue[tuple[str, _ProbeResult | BaseException]] = queue.Queue()

    def runner(key: str, probe: Callable[[AppConfig], _ProbeResult]) -> None:
        try:
            result_queue.put((key, probe(config)))
        except BaseException as exc:  # containment: diagnostics must never kill the UI worker
            result_queue.put((key, exc))

    threads: list[threading.Thread] = []
    for key, _label, probe in _PROBES:
        thread = threading.Thread(
            target=runner,
            args=(key, probe),
            name=f"connection-probe-{key}",
            daemon=True,
        )
        threads.append(thread)
        thread.start()

    deadline = time.monotonic() + DIAGNOSTIC_HARD_TIMEOUT_SECONDS
    results: dict[str, _ProbeResult] = {}
    while len(results) < len(_PROBES):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            key, payload = result_queue.get(timeout=min(0.25, remaining))
        except queue.Empty:
            continue
        if key in results:
            continue
        if isinstance(payload, _ProbeResult):
            results[key] = payload
        else:
            label = next(label for probe_key, label, _probe in _PROBES if probe_key == key)
            results[key] = _ProbeResult(
                ConnectionDiagnostic(
                    key,
                    label,
                    STATUS_TEMPORARY,
                    "Внутрішня помилка окремої перевірки; токен автоматично не відхилено: "
                    + " ".join(str(payload).split()),
                )
            )

    for key, label, _probe in _PROBES:
        if key not in results:
            results[key] = _ProbeResult(
                ConnectionDiagnostic(
                    key,
                    label,
                    STATUS_TEMPORARY,
                    f"Перевірка не завершилася за {int(DIAGNOSTIC_HARD_TIMEOUT_SECONDS)} с; токен автоматично не відхилено.",
                )
            )

    ordered = [results[key] for key, _label, _probe in _PROBES]
    return ConnectionDiagnosticsReport(
        items=tuple(result.item for result in ordered),
        meta_profile=results["facebook"].meta_profile,
        meta_pages=results["facebook"].meta_pages,
        threads_profile=results["threads"].threads_profile,
        linkedin_profile=results["linkedin"].linkedin_profile,
        telegram_profile=results["telegram"].telegram_profile,
        google_profile=results["google_drive"].google_profile,
    )
