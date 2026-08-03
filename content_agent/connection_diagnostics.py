from __future__ import annotations

from dataclasses import dataclass

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
        return ConnectionDiagnostic(
            key,
            label,
            STATUS_REPLACE,
            f"Токен треба замінити: {message}",
        )
    if error.http_status == 403 or _contains(message, _PERMISSION_MARKERS):
        status = STATUS_REPLACE if permission_requires_new_token else STATUS_ATTENTION
        prefix = "Потрібен новий токен або додаткові дозволи" if status == STATUS_REPLACE else "Потрібно виправити права доступу"
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


def diagnose_connections(config: AppConfig) -> ConnectionDiagnosticsReport:
    """Run read-only live checks for every configured publishing connection.

    A platform outage or malformed response is deliberately not treated as proof that
    a token is bad. ``replace`` is reserved for explicit authorization failures, while
    ``attention`` covers roles such as a Telegram bot that is not a channel admin.
    """

    items: list[ConnectionDiagnostic] = []
    meta_profile: MetaProfile | None = None
    meta_pages: tuple[MetaPage, ...] = ()
    threads_profile: ThreadsProfile | None = None
    linkedin_profile: LinkedInProfile | None = None
    telegram_profile: TelegramProfile | None = None
    google_profile: GoogleDriveProfile | None = None

    # Facebook user token also refreshes the Page tokens returned by /me/accounts.
    if not config.meta_user_access_token.strip():
        items.append(_not_configured("facebook", "Facebook", "User Access Token не збережено."))
    else:
        try:
            meta_profile, pages = inspect_meta_token(
                config.meta_user_access_token,
                config.meta_graph_version or "v24.0",
            )
            meta_pages = tuple(pages)
            items.append(
                ConnectionDiagnostic(
                    "facebook",
                    "Facebook",
                    STATUS_OK,
                    f"Токен актуальний; доступно сторінок: {len(meta_pages)}. Page tokens оновлено з Meta.",
                )
            )
        except PlatformSetupError as exc:
            items.append(_platform_error_item("facebook", "Facebook", exc))

    if not config.threads_token.strip():
        items.append(_not_configured("threads", "Threads", "Access token не збережено."))
    else:
        try:
            threads_profile = inspect_threads_token(config.threads_token)
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
            items.append(
                ConnectionDiagnostic(
                    "threads",
                    "Threads",
                    trend_status,
                    f"Профіль @{threads_profile.username or threads_profile.id} підтверджено.{trend_detail}",
                )
            )
        except PlatformSetupError as exc:
            items.append(_platform_error_item("threads", "Threads", exc))

    if not config.linkedin_token.strip():
        items.append(_not_configured("linkedin", "LinkedIn", "Access Token не збережено."))
    else:
        try:
            linkedin_profile = inspect_linkedin_token(config.linkedin_token)
            items.append(
                ConnectionDiagnostic(
                    "linkedin",
                    "LinkedIn",
                    STATUS_OK,
                    f"Токен актуальний; профіль «{linkedin_profile.name}» підтверджено.",
                )
            )
        except PlatformSetupError as exc:
            items.append(_platform_error_item("linkedin", "LinkedIn", exc))

    if not config.telegram_bot_token.strip() or not config.telegram_chat_id.strip():
        items.append(
            _not_configured(
                "telegram",
                "Telegram",
                "Bot token або канал не налаштовано.",
            )
        )
    else:
        try:
            telegram_profile = inspect_telegram_bot(
                config.telegram_bot_token,
                config.telegram_chat_id,
            )
            items.append(
                ConnectionDiagnostic(
                    "telegram",
                    "Telegram",
                    STATUS_OK,
                    f"Бот @{telegram_profile.username} має право публікувати в «{telegram_profile.target_title}».",
                )
            )
        except PlatformSetupError as exc:
            # Missing channel-admin rights do not require rotating a perfectly good bot token.
            items.append(
                _platform_error_item(
                    "telegram",
                    "Telegram",
                    exc,
                    permission_requires_new_token=False,
                )
            )

    if not config.google_client_id.strip() or not config.google_refresh_token.strip():
        items.append(_not_configured("google_drive", "Google Drive", "Google Drive не підключено."))
    else:
        try:
            google_profile = inspect_google_drive_connection(
                config.google_client_id,
                config.google_client_secret,
                config.google_refresh_token,
            )
            account = google_profile.account_email or google_profile.display_name or "акаунт підтверджено"
            items.append(
                ConnectionDiagnostic(
                    "google_drive",
                    "Google Drive",
                    STATUS_OK,
                    f"Refresh token актуальний; {account}.",
                )
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
            items.append(ConnectionDiagnostic("google_drive", "Google Drive", status, detail))

    return ConnectionDiagnosticsReport(
        items=tuple(items),
        meta_profile=meta_profile,
        meta_pages=meta_pages,
        threads_profile=threads_profile,
        linkedin_profile=linkedin_profile,
        telegram_profile=telegram_profile,
        google_profile=google_profile,
    )
