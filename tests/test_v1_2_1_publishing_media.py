from __future__ import annotations

import content_agent.comment_compat_v1_2_rc3 as compat
import content_agent.threads_comments_v1_2_rc3 as threads_mod
from content_agent.comment_compat_v1_2_rc3 import CompatibleTelegramPublisher
from content_agent.media_gallery_v1_2_rc4 import ImageGalleryPayload
from content_agent.models import MediaPayload
from content_agent.publication_text import THREADS_FUND_FOOTER
from content_agent.publishers import PublishContext
from content_agent.threads_comments_v1_2_rc3 import CommentedThreadsPublisher
from content_agent.ui.v1_2_rc8_window import MainWindow


def _image(index: int) -> MediaPayload:
    return MediaPayload(
        file_id=f"f{index}",
        name=f"photo{index}.jpg",
        kind="image",
        mime_type="image/jpeg",
        data=f"image-{index}".encode(),
        public_url=f"https://cdn.example/{index}.jpg",
    )


def _context(saved: list[dict[str, object]]) -> PublishContext:
    return PublishContext(before_write=lambda: None, save_progress=lambda value: saved.append(dict(value)))


def test_telegram_gallery_uses_one_media_group(monkeypatch) -> None:
    calls: list[tuple[str, str, str, int]] = []

    def fake_group(token: str, chat_id: str, text: str, gallery: ImageGalleryPayload) -> list[str]:
        calls.append((token, chat_id, text, len(gallery.items)))
        return [str(100 + i) for i in range(len(gallery.items))]

    monkeypatch.setattr(compat, "_telegram_send_media_group", fake_group)
    saved: list[dict[str, object]] = []
    gallery = ImageGalleryPayload([_image(i) for i in range(10)])
    result = CompatibleTelegramPublisher("token", "@channel").publish(
        "Текст з донатним блоком",
        {},
        _context(saved),
        gallery,
    )

    assert calls == [("token", "@channel", "Текст з донатним блоком", 10)]
    assert result.remote_id == "100"
    assert result.progress["telegram_album_completed"] is True
    assert result.progress["telegram_album_remote_ids"] == [str(100 + i) for i in range(10)]


def test_telegram_media_group_body_has_one_caption_and_ten_attachments() -> None:
    gallery = ImageGalleryPayload([_image(i) for i in range(10)])
    body, _content_type = compat._telegram_media_group_body("@channel", "Підпис", gallery)
    decoded = body.decode("utf-8", errors="ignore")
    for index in range(10):
        assert decoded.count(f'name="photo{index}";') == 1
    assert decoded.count('"caption":"Підпис"') == 1
    assert '"media":"attach://photo9"' in decoded


def test_threads_gallery_splits_overlong_text_and_auto_publishes_replies(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    seq = {"child": 0, "reply": 0}

    def fake_post(url: str, fields: dict[str, object], *, timeout: float = 45):
        del timeout
        calls.append((url, dict(fields)))
        if fields.get("is_carousel_item") == "true":
            seq["child"] += 1
            return {"id": f"child-{seq['child']}"}
        if fields.get("media_type") == "CAROUSEL":
            return {"id": "carousel-container"}
        if url.endswith("/threads_publish"):
            return {"id": "root-post"}
        if fields.get("media_type") == "TEXT":
            seq["reply"] += 1
            return {"id": f"reply-{seq['reply']}"}
        raise AssertionError(fields)

    monkeypatch.setattr(threads_mod, "_post_form", fake_post)
    monkeypatch.setattr(CommentedThreadsPublisher, "_wait_until_ready", lambda self, _id: None)

    text = ("Абзац новини. " * 55).strip()
    assert len(text) > 500
    gallery = ImageGalleryPayload([_image(1), _image(2)])
    saved: list[dict[str, object]] = []
    result = CommentedThreadsPublisher("user", "token").publish(text, {}, _context(saved), gallery)

    carousel = next(fields for _url, fields in calls if fields.get("media_type") == "CAROUSEL")
    text_replies = [fields for _url, fields in calls if fields.get("media_type") == "TEXT"]
    assert len(str(carousel["text"])) <= 500
    assert all(len(str(fields["text"])) <= 500 for fields in text_replies)
    assert text_replies[-1]["text"] == THREADS_FUND_FOOTER
    assert all(fields.get("auto_publish_text") == "true" for fields in text_replies)
    assert result.remote_id == "root-post"
    assert result.progress["threads_donation_comment_completed"] is True


def test_threads_legacy_unknown_donation_is_reconciled_when_container_is_published(monkeypatch) -> None:
    publisher = CommentedThreadsPublisher("user", "token")
    monkeypatch.setattr(
        threads_mod.SafeThreadsPublisher,
        "publish",
        lambda self, text, progress, context, media=None: threads_mod.PublishResult(
            remote_id="root-post", progress=progress
        ),
    )
    monkeypatch.setattr(publisher, "_container_status", lambda _container: "PUBLISHED")
    monkeypatch.setattr(
        threads_mod,
        "_post_form",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not publish again")),
    )
    saved: list[dict[str, object]] = []
    progress = {
        "threads_donation_container_id": "legacy-container",
        "threads_donation_publish_started": True,
        "threads_donation_comment_started": True,
        "threads_donation_comment_completed": False,
    }
    result = publisher.publish("Коротка новина", progress, _context(saved))
    assert result.remote_id == "root-post"
    assert result.progress["threads_donation_comment_completed"] is True
    assert result.progress["threads_donation_comment_id"] == "legacy-container"
    assert result.progress["threads_donation_publish_started"] is False


def test_media_selection_counter_shows_exact_selected_count() -> None:
    class FakeTree:
        def selection(self):
            return ("1", "2", "4", "7")

    class FakeButton:
        text = ""

        def configure(self, **kwargs):
            self.text = str(kwargs["text"])

    window = MainWindow.__new__(MainWindow)
    window.media_candidates_tree = FakeTree()
    window.media_add_selected_button = FakeButton()
    window._update_media_selection_counter()
    assert window.media_add_selected_button.text == "Використати вибране · обрано: 4"
