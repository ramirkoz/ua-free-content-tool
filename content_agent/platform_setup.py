from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlencode, urlsplit

from .network import NetworkError, fetch_url


class PlatformSetupError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: int = 0,
        subcode: int = 0,
        http_status: int = 0,
    ):
        super().__init__(message)
        self.code = code
        self.subcode = subcode
        self.http_status = http_status


@dataclass(slots=True, frozen=True)
class MetaPage:
    id: str
    name: str
    access_token: str


@dataclass(slots=True, frozen=True)
class MetaProfile:
    id: str
    name: str


@dataclass(slots=True, frozen=True)
class MetaDeviceSession:
    code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int


@dataclass(slots=True, frozen=True)
class TokenLifecycleResult:
    access_token: str
    expires_in: int
    token_type: str = "bearer"


@dataclass(slots=True, frozen=True)
class ThreadsProfile:
    id: str
    username: str
    name: str


@dataclass(slots=True, frozen=True)
class LinkedInProfile:
    author_urn: str
    name: str
    access_token: str
    expires_in: int


@dataclass(slots=True, frozen=True)
class TelegramProfile:
    username: str
    display_name: str
    target_title: str
    chat_type: str = ""
    member_status: str = ""
    can_post_messages: bool = False


def _int_value(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _json_response(response_body: bytes, *, http_status: int = 200) -> dict[str, object]:
    try:
        payload = json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PlatformSetupError(
            "Платформа повернула пошкоджену відповідь.",
            http_status=http_status,
        ) from exc
    if not isinstance(payload, dict):
        raise PlatformSetupError(
            "Платформа повернула неочікуваний формат відповіді.",
            http_status=http_status,
        )

    error = payload.get("error")
    if error:
        if isinstance(error, dict):
            message = str(
                error.get("message")
                or error.get("error_user_msg")
                or error.get("error_description")
                or error
            )
            raise PlatformSetupError(
                message,
                code=_int_value(error.get("code")),
                subcode=_int_value(error.get("error_subcode")),
                http_status=http_status,
            )
        message = str(payload.get("error_description") or error)
        raise PlatformSetupError(message, http_status=http_status)

    if payload.get("ok") is False:
        raise PlatformSetupError(
            str(payload.get("description") or "Платформа відхилила запит."),
            code=_int_value(payload.get("error_code")),
            http_status=http_status,
        )

    # LinkedIn and several OAuth endpoints may return an error object without an
    # ``error`` field, for example {"status":403,"serviceErrorCode":100,
    # "message":"Not enough permissions ..."}. Treat that as an error instead
    # of later blaming a valid token for a missing profile id.
    payload_status = _int_value(payload.get("status"))
    service_error = _int_value(payload.get("serviceErrorCode"))
    if http_status >= 400 or payload_status >= 400 or service_error:
        message = str(
            payload.get("message")
            or payload.get("detail")
            or payload.get("error_description")
            or f"Платформа повернула HTTP {http_status or payload_status}."
        )
        raise PlatformSetupError(
            message,
            code=service_error or _int_value(payload.get("code")),
            http_status=payload_status if payload_status >= 400 else http_status,
        )
    return payload


def _post_form(
    url: str,
    fields: dict[str, object],
    *,
    allow_http_errors: bool = True,
) -> dict[str, object]:
    response = fetch_url(
        url,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        body=urlencode({key: str(value) for key, value in fields.items()}).encode("utf-8"),
        timeout=60,
        max_bytes=2 * 1024 * 1024,
        allowed_content_types={"application/json", "text/javascript"},
        max_redirects=0,
        allow_http_errors=allow_http_errors,
    )
    return _json_response(response.body, http_status=response.status)


def _get_json(
    url: str,
    *,
    bearer: str = "",
    timeout: float = 12.0,
) -> dict[str, object]:
    headers = {"Accept": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    response = fetch_url(
        url,
        headers=headers,
        timeout=timeout,
        max_bytes=2 * 1024 * 1024,
        allowed_content_types={"application/json", "text/javascript"},
        max_redirects=0,
        allow_http_errors=True,
    )
    return _json_response(response.body, http_status=response.status)


def exchange_facebook_long_lived_token(
    user_token: str,
    app_id: str,
    app_secret: str,
    graph_version: str,
) -> TokenLifecycleResult:
    """Exchange a short-lived Facebook user token for a long-lived token.

    Meta's documented exchange requires the app id, app secret and a still-valid
    user token. The secret is never logged and is stored only in the encrypted
    application configuration.
    """
    token = user_token.strip()
    app = app_id.strip()
    secret = app_secret.strip()
    if not token or not app or not secret:
        raise PlatformSetupError(
            "Для довготривалого Facebook-токена потрібні Meta App ID, App Secret і чинний User Access Token."
        )
    query = urlencode(
        {
            "grant_type": "fb_exchange_token",
            "client_id": app,
            "client_secret": secret,
            "fb_exchange_token": token,
        }
    )
    try:
        payload = _get_json(
            f"https://graph.facebook.com/{graph_version}/oauth/access_token?{query}",
            timeout=20,
        )
    except NetworkError as exc:
        raise PlatformSetupError(str(exc)) from exc
    value = str(payload.get("access_token") or "")
    if not value:
        raise PlatformSetupError("Meta не повернула довготривалий Facebook-токен.")
    return TokenLifecycleResult(
        value,
        max(0, _int_value(payload.get("expires_in"))),
        str(payload.get("token_type") or "bearer"),
    )


def exchange_threads_long_lived_token(
    token: str,
    app_secret: str,
) -> TokenLifecycleResult:
    """Exchange a short-lived Threads token for a 60-day token."""
    value = token.strip()
    secret = app_secret.strip()
    if not value or not secret:
        raise PlatformSetupError(
            "Для довготривалого Threads-токена потрібні чинний Threads token і Meta App Secret."
        )
    query = urlencode(
        {
            "grant_type": "th_exchange_token",
            "client_secret": secret,
            "access_token": value,
        }
    )
    try:
        payload = _get_json(
            f"https://graph.threads.net/access_token?{query}",
            timeout=20,
        )
    except NetworkError as exc:
        raise PlatformSetupError(str(exc)) from exc
    exchanged = str(payload.get("access_token") or "")
    if not exchanged:
        raise PlatformSetupError("Meta не повернула довготривалий Threads-токен.")
    return TokenLifecycleResult(
        exchanged,
        max(0, _int_value(payload.get("expires_in"))),
        str(payload.get("token_type") or "bearer"),
    )


def refresh_threads_long_lived_token(token: str) -> TokenLifecycleResult:
    """Refresh a valid long-lived Threads token before it expires."""
    value = token.strip()
    if not value:
        raise PlatformSetupError("Вставте Threads access token.")
    query = urlencode(
        {
            "grant_type": "th_refresh_token",
            "access_token": value,
        }
    )
    try:
        payload = _get_json(
            f"https://graph.threads.net/refresh_access_token?{query}",
            timeout=20,
        )
    except NetworkError as exc:
        raise PlatformSetupError(str(exc)) from exc
    refreshed = str(payload.get("access_token") or "")
    if not refreshed:
        raise PlatformSetupError("Meta не повернула оновлений Threads-токен.")
    return TokenLifecycleResult(
        refreshed,
        max(0, _int_value(payload.get("expires_in"))),
        str(payload.get("token_type") or "bearer"),
    )


def begin_meta_device_login(
    app_id: str,
    client_token: str,
    graph_version: str,
) -> MetaDeviceSession:
    app_id = app_id.strip()
    client_token = client_token.strip()
    if not app_id or not client_token:
        raise PlatformSetupError("Вставте Meta App ID і Meta Client Token.")
    try:
        payload = _post_form(
            f"https://graph.facebook.com/{graph_version}/device/login",
            {
                "access_token": f"{app_id}|{client_token}",
                "scope": "pages_show_list,pages_read_engagement,pages_manage_posts",
            },
        )
    except NetworkError as exc:
        raise PlatformSetupError(str(exc)) from exc
    code = str(payload.get("code") or "")
    user_code = str(payload.get("user_code") or "")
    if not code or not user_code:
        raise PlatformSetupError("Meta не повернула код входу.")
    return MetaDeviceSession(
        code=code,
        user_code=user_code,
        verification_uri=str(payload.get("verification_uri") or "https://www.facebook.com/device"),
        verification_uri_complete=str(payload.get("verification_uri_complete") or ""),
        expires_in=max(60, int(payload.get("expires_in") or 600)),
        interval=max(3, int(payload.get("interval") or 5)),
    )


def load_meta_pages(user_token: str, graph_version: str) -> list[MetaPage]:
    user_token = user_token.strip()
    if not user_token:
        raise PlatformSetupError("Вставте Facebook User Access Token.")
    query = urlencode({"fields": "id,name,access_token", "limit": "100"})
    url = f"https://graph.facebook.com/{graph_version}/me/accounts?{query}"
    pages: list[MetaPage] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    for _page_number in range(100):
        if url in seen_urls:
            raise PlatformSetupError("Meta повернула циклічну пагінацію сторінок.")
        seen_urls.add(url)
        try:
            payload = _get_json(url, bearer=user_token)
        except NetworkError as exc:
            raise PlatformSetupError(str(exc)) from exc
        data = payload.get("data")
        if not isinstance(data, list):
            raise PlatformSetupError("Meta не повернула список сторінок.")
        for item in data:
            if not isinstance(item, dict):
                continue
            page_id = str(item.get("id") or "")
            name = str(item.get("name") or page_id)
            token = str(item.get("access_token") or "")
            if page_id and token and page_id not in seen_ids:
                seen_ids.add(page_id)
                pages.append(MetaPage(page_id, name, token))
        paging = payload.get("paging")
        next_url = str(paging.get("next") or "") if isinstance(paging, dict) else ""
        if not next_url:
            break
        parsed = urlsplit(next_url)
        if parsed.scheme != "https" or parsed.hostname not in {"graph.facebook.com", "graph-video.facebook.com"}:
            raise PlatformSetupError("Meta повернула небезпечну адресу наступної сторінки.")
        url = next_url
    else:
        raise PlatformSetupError("Meta повернула надто багато сторінок пагінації.")
    if not pages:
        raise PlatformSetupError(
            "Meta не повернула сторінки. Перевірте права pages_show_list і pages_manage_posts."
        )
    return pages


def inspect_meta_token(
    user_token: str,
    graph_version: str,
) -> tuple[MetaProfile, list[MetaPage]]:
    value = user_token.strip()
    if not value:
        raise PlatformSetupError("Вставте Facebook User Access Token.")
    query = urlencode({"fields": "id,name"})
    try:
        payload = _get_json(
            f"https://graph.facebook.com/{graph_version}/me?{query}",
            bearer=value,
        )
        pages = load_meta_pages(value, graph_version)
    except NetworkError as exc:
        raise PlatformSetupError(str(exc)) from exc
    profile_id = str(payload.get("id") or "")
    if not profile_id:
        raise PlatformSetupError("Facebook не повернув ID користувача.")
    return MetaProfile(profile_id, str(payload.get("name") or profile_id)), pages


def complete_meta_device_login(
    session: MetaDeviceSession,
    app_id: str,
    client_token: str,
    graph_version: str,
    *,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[str, list[MetaPage]]:
    app_access_token = f"{app_id.strip()}|{client_token.strip()}"
    deadline = clock() + session.expires_in
    interval = session.interval
    pending_codes = {1349172}
    slow_codes = {1349173}
    declined_codes = {1349174}
    expired_codes = {1349152}
    while clock() < deadline:
        try:
            payload = _post_form(
                f"https://graph.facebook.com/{graph_version}/device/login_status",
                {"access_token": app_access_token, "code": session.code},
                allow_http_errors=True,
            )
        except PlatformSetupError as exc:
            message = str(exc)
            lowered = message.lower()
            states = {exc.code, exc.subcode}
            if states & pending_codes or "pending" in lowered:
                sleeper(interval)
                continue
            if states & slow_codes or "slow" in lowered:
                interval += 5
                sleeper(interval)
                continue
            if states & declined_codes or "declin" in lowered:
                raise PlatformSetupError("Вхід у Facebook відхилено.") from exc
            if states & expired_codes or "expir" in lowered:
                raise PlatformSetupError("Код Facebook прострочено. Запустіть підключення ще раз.") from exc
            raise
        user_token = str(payload.get("access_token") or "")
        if user_token:
            return user_token, load_meta_pages(user_token, graph_version)
        sleeper(interval)
    raise PlatformSetupError("Час очікування підтвердження Facebook минув.")


def inspect_threads_token(token: str) -> ThreadsProfile:
    token = token.strip()
    if not token:
        raise PlatformSetupError("Вставте Threads access token.")
    query = urlencode({"fields": "id,username,name"})
    try:
        payload = _get_json(
            f"https://graph.threads.net/me?{query}",
            bearer=token,
            timeout=12,
        )
    except PlatformSetupError as exc:
        if "failed to decode" in str(exc).lower():
            raise PlatformSetupError(
                "Meta не змогла розпізнати Threads User Access Token. "
                "Створіть токен саме кнопкою Generate Threads Access Token, "
                "скопіюйте його повністю та повторіть перевірку."
            ) from exc
        raise
    except NetworkError as exc:
        raise PlatformSetupError(str(exc)) from exc
    profile_id = str(payload.get("id") or "")
    if not profile_id:
        raise PlatformSetupError("Threads не повернув ID профілю.")
    username = str(payload.get("username") or "")
    return ThreadsProfile(profile_id, username, str(payload.get("name") or username or profile_id))



def inspect_linkedin_token(token: str) -> LinkedInProfile:
    value = token.strip()
    if not value:
        raise PlatformSetupError("Вставте LinkedIn Access Token.")
    try:
        profile_payload = _get_json(
            "https://api.linkedin.com/v2/userinfo",
            bearer=value,
        )
    except PlatformSetupError as exc:
        lowered = str(exc).lower()
        if exc.http_status == 401 or any(
            marker in lowered
            for marker in ("invalid token", "expired token", "token has expired", "oauth token is invalid")
        ):
            raise PlatformSetupError(
                "LinkedIn-токен недійсний, прострочений або відкликаний. "
                "Створіть новий токен і повторіть перевірку. "
                f"Відповідь LinkedIn: {exc}",
                code=exc.code,
                http_status=exc.http_status,
            ) from exc
        if exc.http_status == 403 or "permission" in lowered or "not enough" in lowered:
            raise PlatformSetupError(
                "LinkedIn відхилив доступ до профілю. Переконайтеся, що застосунок має продукт "
                "Sign In with LinkedIn using OpenID Connect, а токен створений із дозволами "
                "openid, profile та w_member_social. Потім створіть новий токен. "
                f"Відповідь LinkedIn: {exc}",
                code=exc.code,
                http_status=exc.http_status,
            ) from exc
        raise PlatformSetupError(
            f"LinkedIn не підтвердив токен: {exc}",
            code=exc.code,
            http_status=exc.http_status,
        ) from exc
    except NetworkError as exc:
        raise PlatformSetupError(str(exc)) from exc
    person_id = str(profile_payload.get("sub") or "")
    if not person_id:
        keys = ", ".join(sorted(str(key) for key in profile_payload)) or "немає полів"
        raise PlatformSetupError(
            "LinkedIn повернув відповідь без ID профілю (поле sub). Токен автоматично не відхилено; "
            "це може бути збій або зміна формату API. Поля відповіді: " + keys
        )
    return LinkedInProfile(
        author_urn=f"urn:li:person:{person_id}",
        name=str(profile_payload.get("name") or person_id),
        access_token=value,
        expires_in=0,
    )


def inspect_telegram_bot(token: str, target: str) -> TelegramProfile:
    token = token.strip()
    target = target.strip()
    if not token or not target:
        raise PlatformSetupError("Вставте Telegram bot token і @назву каналу.")
    try:
        me = _get_json(f"https://api.telegram.org/bot{token}/getMe")
        chat_query = urlencode({"chat_id": target})
        chat = _get_json(f"https://api.telegram.org/bot{token}/getChat?{chat_query}")
    except NetworkError as exc:
        raise PlatformSetupError(str(exc)) from exc
    me_result = me.get("result")
    chat_result = chat.get("result")
    if not isinstance(me_result, dict) or not isinstance(chat_result, dict):
        raise PlatformSetupError("Telegram не підтвердив бота або канал.")

    bot_id = str(me_result.get("id") or "")
    if not bot_id:
        raise PlatformSetupError("Telegram не повернув ID бота.")
    member_query = urlencode({"chat_id": target, "user_id": bot_id})
    try:
        member_payload = _get_json(
            f"https://api.telegram.org/bot{token}/getChatMember?{member_query}"
        )
    except NetworkError as exc:
        raise PlatformSetupError(str(exc)) from exc
    member = member_payload.get("result")
    if not isinstance(member, dict):
        raise PlatformSetupError("Telegram не повернув права бота в каналі.")

    username = str(me_result.get("username") or "")
    display_name = " ".join(
        part
        for part in (
            str(me_result.get("first_name") or ""),
            str(me_result.get("last_name") or ""),
        )
        if part
    )
    target_title = str(chat_result.get("title") or chat_result.get("username") or target)
    chat_type = str(chat_result.get("type") or "")
    member_status = str(member.get("status") or "")
    can_post_messages = bool(member.get("can_post_messages"))

    if chat_type == "channel":
        if member_status not in {"administrator", "creator"}:
            raise PlatformSetupError(
                f"Бот @{username or bot_id} бачить канал «{target_title}», але не є адміністратором. "
                "Додайте його адміністратором каналу з правом публікувати повідомлення.",
                http_status=403,
            )
        if member_status != "creator" and not can_post_messages:
            raise PlatformSetupError(
                f"Бот @{username or bot_id} є адміністратором каналу «{target_title}», "
                "але не має права публікувати повідомлення (can_post_messages).",
                http_status=403,
            )
    elif member_status in {"left", "kicked", "restricted"}:
        raise PlatformSetupError(
            f"Бот @{username or bot_id} не може надсилати повідомлення до «{target_title}». "
            "Перевірте його участь і права.",
            http_status=403,
        )

    return TelegramProfile(
        username,
        display_name or username,
        target_title,
        chat_type,
        member_status,
        can_post_messages or member_status == "creator" or chat_type != "channel",
    )

