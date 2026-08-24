from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, quote, urlencode, urlsplit

from .network import NetworkError, fetch_url

_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
_OPENID_SCOPES = "openid email"
_ALLOWED_MIME_PREFIXES = ("image/", "video/")
_MAX_MEDIA_BYTES = 200 * 1024 * 1024


class GoogleDriveError(RuntimeError):
    pass


@dataclass(slots=True)
class GoogleAuthorization:
    refresh_token: str
    access_token: str
    account_email: str


@dataclass(slots=True, frozen=True)
class GoogleDriveProfile:
    account_email: str
    display_name: str


@dataclass(slots=True)
class DriveMediaInfo:
    file_id: str
    name: str
    mime_type: str
    size: int
    kind: str
    can_download: bool
    can_delete: bool
    can_share: bool
    public_url: str
    public_direct: bool


def extract_drive_file_id(value: str) -> str:
    raw = value.strip()
    if not raw:
        raise GoogleDriveError("Вставте посилання на файл Google Drive.")
    parts = urlsplit(raw if "://" in raw else "https://" + raw)
    host = (parts.hostname or "").lower()
    if host not in {
        "drive.google.com",
        "www.drive.google.com",
        "drive.usercontent.google.com",
        "docs.google.com",
    }:
        raise GoogleDriveError("Потрібне посилання саме на файл Google Drive.")
    query = parse_qs(parts.query)
    for key in ("id", "file_id"):
        candidate = (query.get(key) or [""])[0]
        if candidate:
            return _validate_file_id(candidate)
    segments = [item for item in parts.path.split("/") if item]
    if "d" in segments:
        index = segments.index("d")
        if index + 1 < len(segments):
            return _validate_file_id(segments[index + 1])
    if segments and segments[0] in {"open", "uc", "download"}:
        candidate = (query.get("id") or [""])[0]
        if candidate:
            return _validate_file_id(candidate)
    raise GoogleDriveError("Не вдалося визначити ID файла з посилання Google Drive.")


def _validate_file_id(value: str) -> str:
    candidate = value.strip()
    if not candidate or len(candidate) > 200 or not all(ch.isalnum() or ch in "-_" for ch in candidate):
        raise GoogleDriveError("Google Drive file ID має неправильний формат.")
    return candidate


def public_download_url(file_id: str) -> str:
    return "https://drive.google.com/uc?" + urlencode({"export": "download", "id": _validate_file_id(file_id)})


def _post_form(url: str, fields: dict[str, str], *, timeout: float = 45.0) -> dict[str, object]:
    body = urlencode(fields).encode("utf-8")
    response = fetch_url(
        url,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        body=body,
        max_bytes=2 * 1024 * 1024,
        allowed_content_types={"application/json", "text/javascript"},
        timeout=timeout,
        max_redirects=0,
        allow_http_errors=True,
    )
    payload = response.json() if response.body else {}
    if response.status >= 400 or not isinstance(payload, dict):
        message: object = None
        if isinstance(payload, dict):
            message = payload.get("error_description")
            if not message:
                error = payload.get("error")
                if isinstance(error, dict):
                    message = error.get("message") or error.get("status") or error
                else:
                    message = error
        raise GoogleDriveError(str(message or "Google OAuth відхилив запит."))
    return payload


def authorize_google_drive(client_id: str, client_secret: str, timeout_seconds: int = 240) -> GoogleAuthorization:
    client_id = client_id.strip()
    client_secret = client_secret.strip()
    if not client_id:
        raise GoogleDriveError("Вкажіть Google OAuth Client ID типу Desktop app.")

    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    result: dict[str, str] = {}
    ready = threading.Event()

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            query = parse_qs(urlsplit(self.path).query)
            if (query.get("state") or [""])[0] != state:
                result["error"] = "Google OAuth повернув неправильний state."
            elif query.get("error"):
                result["error"] = str((query.get("error") or ["access_denied"])[0])
            else:
                result["code"] = str((query.get("code") or [""])[0])
            body = (
                "<html><meta charset='utf-8'><body style='font-family:Segoe UI;padding:40px'>"
                "<h2>Google Drive підключено</h2><p>Поверніться до UA FREE Content Tool. Це вікно можна закрити.</p>"
                "</body></html>"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            ready.set()

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), CallbackHandler)
    server.timeout = 1.0
    redirect_uri = f"http://127.0.0.1:{server.server_port}/oauth2callback"
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": f"{_OPENID_SCOPES} {_DRIVE_SCOPE}",
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    webbrowser.open(auth_url, new=2)
    deadline = time.monotonic() + timeout_seconds
    try:
        while time.monotonic() < deadline and not ready.is_set():
            server.handle_request()
    finally:
        server.server_close()
    if not ready.is_set():
        raise GoogleDriveError("Час очікування авторизації Google Drive минув.")
    if result.get("error"):
        raise GoogleDriveError(f"Google Drive не підключено: {result['error']}")
    code = result.get("code", "")
    if not code:
        raise GoogleDriveError("Google OAuth не повернув код авторизації.")

    fields = {
        "client_id": client_id,
        "code": code,
        "code_verifier": verifier,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }
    if client_secret:
        fields["client_secret"] = client_secret
    token_payload = _post_form("https://oauth2.googleapis.com/token", fields)
    access_token = str(token_payload.get("access_token", ""))
    refresh_token = str(token_payload.get("refresh_token", ""))
    if not access_token or not refresh_token:
        raise GoogleDriveError("Google не повернув довготривалий refresh token. Повторіть підключення.")
    email = ""
    try:
        response = fetch_url(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            max_bytes=512 * 1024,
            allowed_content_types={"application/json"},
            timeout=30,
            max_redirects=0,
        )
        payload = response.json()
        if isinstance(payload, dict):
            email = str(payload.get("email", ""))
    except NetworkError:
        pass
    return GoogleAuthorization(refresh_token=refresh_token, access_token=access_token, account_email=email)


def refresh_access_token(
    client_id: str,
    client_secret: str,
    refresh_token: str,
    *,
    timeout: float = 45.0,
) -> str:
    fields = {
        "client_id": client_id.strip(),
        "refresh_token": refresh_token.strip(),
        "grant_type": "refresh_token",
    }
    if client_secret.strip():
        fields["client_secret"] = client_secret.strip()
    payload = _post_form("https://oauth2.googleapis.com/token", fields, timeout=timeout)
    access_token = str(payload.get("access_token", ""))
    if not access_token:
        raise GoogleDriveError("Не вдалося оновити доступ Google Drive.")
    return access_token


def inspect_google_drive_connection(
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> GoogleDriveProfile:
    client_id = client_id.strip()
    refresh_token = refresh_token.strip()
    if not client_id or not refresh_token:
        raise GoogleDriveError("Google Drive ще не підключено.")
    access_token = refresh_access_token(client_id, client_secret, refresh_token, timeout=12)
    response = fetch_url(
        "https://www.googleapis.com/drive/v3/about?fields=user(displayName,emailAddress)",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        max_bytes=512 * 1024,
        allowed_content_types={"application/json"},
        timeout=12,
        max_redirects=0,
        allow_http_errors=True,
    )
    payload = response.json() if response.body else {}
    if response.status >= 400 or not isinstance(payload, dict):
        message = "Google Drive відхилив перевірку доступу."
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                message = str(error.get("message") or message)
            elif error:
                message = str(error)
        raise GoogleDriveError(message)
    user = payload.get("user")
    if not isinstance(user, dict):
        raise GoogleDriveError("Google Drive не повернув дані підключеного акаунта.")
    return GoogleDriveProfile(
        account_email=str(user.get("emailAddress") or ""),
        display_name=str(user.get("displayName") or ""),
    )


def _kind_from_mime(mime_type: str) -> str:
    if mime_type.startswith("image/"):
        return "image"
    if mime_type.startswith("video/"):
        return "video"
    raise GoogleDriveError(f"Підтримуються лише фото і відео, отримано {mime_type or 'невідомий тип'}.")


def probe_public_media(file_id: str) -> tuple[bool, str]:
    """Check the unauthenticated URL that Threads will fetch.

    Google Drive sometimes answers HEAD with HTML even though a ranged GET returns
    the media bytes. Try both so a valid inherited/public permission is not rejected
    merely because Drive chose a different redirect path that day.
    """
    url = public_download_url(file_id)
    attempts = (
        ("HEAD", {"Accept": "image/*,video/*"}, 1024),
        ("GET", {"Accept": "image/*,video/*", "Range": "bytes=0-65535"}, 128 * 1024),
    )
    for method, headers, max_bytes in attempts:
        try:
            response = fetch_url(
                url,
                method=method,
                headers=headers,
                max_bytes=max_bytes,
                timeout=30,
                max_redirects=6,
                allow_http_errors=True,
            )
        except NetworkError:
            continue
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if response.status < 400 and content_type.startswith(_ALLOWED_MIME_PREFIXES):
            return True, content_type
    return False, ""


class GoogleDriveClient:
    def __init__(self, client_id: str, client_secret: str, refresh_token: str):
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self.refresh_token = refresh_token.strip()
        if not self.client_id or not self.refresh_token:
            raise GoogleDriveError("Google Drive не підключено в налаштуваннях.")
        self._access_token = ""

    def _token(self) -> str:
        if not self._access_token:
            self._access_token = refresh_access_token(
                self.client_id, self.client_secret, self.refresh_token, timeout=15
            )
        return self._access_token

    def inspect_media(self, file_id: str, *, probe_public: bool = True) -> DriveMediaInfo:
        file_id = _validate_file_id(file_id)
        fields = "id,name,mimeType,size,trashed,capabilities(canDownload,canDelete,canShare)"
        url = f"https://www.googleapis.com/drive/v3/files/{quote(file_id)}?" + urlencode(
            {"fields": fields, "supportsAllDrives": "true"}
        )
        response = fetch_url(
            url,
            headers={"Authorization": f"Bearer {self._token()}", "Accept": "application/json"},
            max_bytes=2 * 1024 * 1024,
            allowed_content_types={"application/json"},
            timeout=20,
            max_redirects=0,
            allow_http_errors=True,
        )
        payload = response.json() if response.body else {}
        if response.status >= 400 or not isinstance(payload, dict):
            raise GoogleDriveError("Google Drive не дозволив відкрити цей файл.")
        if payload.get("trashed"):
            raise GoogleDriveError("Файл уже перебуває в кошику Google Drive.")
        mime_type = str(payload.get("mimeType", "")).lower()
        kind = _kind_from_mime(mime_type)
        size = int(payload.get("size", 0) or 0)
        if size <= 0:
            raise GoogleDriveError("Google Drive не повідомив розмір медіафайла.")
        if size > _MAX_MEDIA_BYTES:
            raise GoogleDriveError("Медіафайл перевищує ліміт програми 200 МБ.")
        capabilities = payload.get("capabilities") if isinstance(payload.get("capabilities"), dict) else {}
        public_direct = False
        if probe_public:
            public_direct, public_type = probe_public_media(file_id)
            if public_direct and public_type and public_type != mime_type:
                mime_type = public_type
                kind = _kind_from_mime(mime_type)
        return DriveMediaInfo(
            file_id=file_id,
            name=str(payload.get("name", "media")),
            mime_type=mime_type,
            size=size,
            kind=kind,
            can_download=bool(capabilities.get("canDownload", True)),
            can_delete=bool(capabilities.get("canDelete", False)),
            can_share=bool(capabilities.get("canShare", False)),
            public_url=public_download_url(file_id),
            public_direct=public_direct,
        )


    def ensure_public_for_threads(self, info: DriveMediaInfo) -> str:
        """Temporarily grant anyone-reader access when Threads needs a URL.

        Returns the permission ID created by the program, or an empty string when
        the file was already publicly reachable through an inherited/direct grant.
        Only a permission created here may later be revoked by this program.
        """
        if info.public_direct:
            return ""
        # Generic publication preflight intentionally skips the expensive public
        # URL probe. Threads performs it only when this target actually runs.
        public_now, _content_type = probe_public_media(info.file_id)
        if public_now:
            return ""
        if not info.can_share:
            raise GoogleDriveError(
                "Для Threads потрібне зовнішнє посилання, але підключений Google-акаунт "
                "не може тимчасово відкрити доступ до цього файла."
            )
        body = b'{"type":"anyone","role":"reader","allowFileDiscovery":false}'
        response = fetch_url(
            f"https://www.googleapis.com/drive/v3/files/{quote(_validate_file_id(info.file_id))}/permissions?"
            + urlencode({"fields": "id", "supportsAllDrives": "true"}),
            method="POST",
            headers={
                "Authorization": f"Bearer {self._token()}",
                "Accept": "application/json",
                "Content-Type": "application/json; charset=utf-8",
            },
            body=body,
            max_bytes=2 * 1024 * 1024,
            allowed_content_types={"application/json"},
            timeout=45,
            max_redirects=0,
            allow_http_errors=True,
        )
        payload = response.json() if response.body else {}
        if response.status >= 400 or not isinstance(payload, dict) or not payload.get("id"):
            raise GoogleDriveError(
                f"Не вдалося тимчасово відкрити медіафайл для Threads (HTTP {response.status})."
            )
        permission_id = str(payload["id"])
        for _attempt in range(6):
            public, _content_type = probe_public_media(info.file_id)
            if public:
                return permission_id
            time.sleep(0.5)
        try:
            self.remove_permission(info.file_id, permission_id)
        except GoogleDriveError:
            pass
        raise GoogleDriveError(
            "Google Drive створив тимчасовий доступ, але зовнішнє медіапосилання ще не стало доступним для Threads."
        )

    def remove_permission(self, file_id: str, permission_id: str) -> None:
        if not permission_id:
            return
        response = fetch_url(
            f"https://www.googleapis.com/drive/v3/files/{quote(_validate_file_id(file_id))}/permissions/"
            f"{quote(permission_id)}?supportsAllDrives=true",
            method="DELETE",
            headers={
                "Authorization": f"Bearer {self._token()}",
                "Accept": "application/json",
            },
            max_bytes=2 * 1024 * 1024,
            timeout=45,
            max_redirects=0,
            allow_http_errors=True,
        )
        if response.status not in {200, 204, 404}:
            raise GoogleDriveError(
                f"Не вдалося закрити тимчасовий публічний доступ до медіафайла (HTTP {response.status})."
            )

    def download_media(self, info: DriveMediaInfo) -> bytes:
        if not info.can_download:
            raise GoogleDriveError("Google Drive забороняє завантаження цього файла.")
        response = fetch_url(
            f"https://www.googleapis.com/drive/v3/files/{quote(info.file_id)}?alt=media&supportsAllDrives=true",
            headers={"Authorization": f"Bearer {self._token()}", "Accept": info.mime_type},
            max_bytes=min(_MAX_MEDIA_BYTES, max(info.size + 1024, 2 * 1024 * 1024)),
            timeout=45,
            max_redirects=2,
        )
        if not response.body:
            raise GoogleDriveError("Google Drive повернув порожній медіафайл.")
        return response.body

    def delete_file(self, file_id: str) -> None:
        response = fetch_url(
            f"https://www.googleapis.com/drive/v3/files/{quote(_validate_file_id(file_id))}?supportsAllDrives=true",
            method="DELETE",
            headers={
                "Authorization": f"Bearer {self._token()}",
                "Accept": "application/json",
            },
            max_bytes=2 * 1024 * 1024,
            timeout=45,
            max_redirects=0,
            allow_http_errors=True,
        )
        if response.status not in {200, 204}:
            raise GoogleDriveError(
                f"Не вдалося безповоротно видалити медіафайл із Google Drive (HTTP {response.status})."
            )
