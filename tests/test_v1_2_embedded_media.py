from __future__ import annotations

from content_agent.embedded_media import extract_embedded_media


def test_telegram_background_image_is_discovered() -> None:
    html = """
    <a class="tgme_widget_message_photo_wrap"
       style="background-image:url('/file/photo.jpg')"></a>
    """
    items = extract_embedded_media(html, "https://t.me/channel/42", "Telegram")
    assert len(items) == 1
    assert items[0].url == "https://t.me/file/photo.jpg"
    assert items[0].kind == "image"
    assert items[0].origin == "html:background-image"


def test_telegram_data_video_and_thumbnail_are_discovered() -> None:
    html = """
    <div data-video="https://cdn.example/clip.mp4"
         data-thumbnail="https://cdn.example/thumb.webp"></div>
    """
    items = extract_embedded_media(html, "https://t.me/channel/43", "Telegram")
    assert {(item.kind, item.url) for item in items} == {
        ("video", "https://cdn.example/clip.mp4"),
        ("image", "https://cdn.example/thumb.webp"),
    }


def test_largest_srcset_candidate_is_selected() -> None:
    html = """
    <img srcset="small.jpg 320w, medium.jpg 800w, large.jpg 1600w">
    """
    items = extract_embedded_media(html, "https://news.example/story", "News")
    assert [item.url for item in items] == ["https://news.example/large.jpg"]


def test_embedded_media_rejects_credentials_and_tracking_assets() -> None:
    html = """
    <div style="background-image:url('https://user:pass@example.com/secret.jpg')"></div>
    <div data-image="https://cdn.example/tracking-pixel.jpg"></div>
    """
    assert extract_embedded_media(html, "https://example.com", "News") == []
