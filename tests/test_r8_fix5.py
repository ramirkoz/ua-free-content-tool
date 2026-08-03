from __future__ import annotations

from types import SimpleNamespace

from content_agent.config import AppConfig
from content_agent.ui import main_window
from content_agent.ui.main_window import MainWindow


class DummyVar:
    def __init__(self, value: str = ""):
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


class NoWriteDatabase:
    def set_group_media(self, *_args, **_kwargs) -> None:
        raise AssertionError("Медіа не можна прив'язувати без відкритого блоку")


def test_media_verification_works_without_open_news_group(monkeypatch) -> None:
    window = MainWindow.__new__(MainWindow)
    window.current_group_id = None
    window.media_url_var = DummyVar(
        "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz_12345/view?usp=drive_link"
    )
    window.media_status_var = DummyVar("Медіа не додано")
    window.config = AppConfig(
        google_client_id="client.apps.googleusercontent.com",
        google_client_secret="secret",
        google_refresh_token="refresh",
    )
    window.db = NoWriteDatabase()

    class FakeClient:
        def __init__(self, *_args: str):
            pass

        def inspect_media(self, file_id: str) -> object:
            assert file_id == "1AbCdEfGhIjKlMnOpQrStUvWxYz_12345"
            return SimpleNamespace(
                public_direct=True,
                can_delete=True,
                can_share=True,
                file_id=file_id,
                name="test-photo.jpg",
                kind="image",
                mime_type="image/jpeg",
                size=1024 * 1024,
            )

    monkeypatch.setattr(main_window, "GoogleDriveClient", FakeClient)

    def run_async(action, success=None, **_kwargs):
        result = action()
        if success:
            success(result)

    window.run_async = run_async  # type: ignore[method-assign]
    window.verify_media()

    status = window.media_status_var.get()
    assert status.startswith("✓ Перевірено: IMAGE · test-photo.jpg")
    assert "Відкрийте блок новини" in status


def test_invalid_drive_link_reports_error_instead_of_silent_tk_callback() -> None:
    window = MainWindow.__new__(MainWindow)
    window.current_group_id = None
    window.media_url_var = DummyVar("https://example.com/not-drive")
    window.media_status_var = DummyVar("Медіа не додано")
    window.config = AppConfig(
        google_client_id="client.apps.googleusercontent.com",
        google_refresh_token="refresh",
    )
    errors: list[str] = []
    window._show_error = lambda exc: errors.append(str(exc))  # type: ignore[method-assign]

    window.verify_media()

    assert errors == ["Потрібне посилання саме на файл Google Drive."]
