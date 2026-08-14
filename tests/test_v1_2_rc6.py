from content_agent.config import AppConfig
from content_agent.global_duplicates_v1_3_rc6 import parse_duplicate_clusters
from content_agent.telegram_media_v1_3_rc6 import (
    extract_telegram_post_media,
    telegram_embed_url,
    telegram_post_parts,
)


def test_social_disabled_flags_override_stale_credentials() -> None:
    config = AppConfig(
        telegram_enabled=False,
        telegram_bot_token="token",
        telegram_chat_id="@channel",
        threads_enabled=False,
        threads_user_id="1",
        threads_token="token",
        linkedin_enabled=False,
        linkedin_author_urn="urn:li:person:1",
        linkedin_token="token",
        facebook_enabled=False,
        facebook_pages=[{"id": "1", "name": "Page", "access_token": "token"}],
    )
    assert not config.platform_ready("telegram")
    assert not config.platform_ready("threads")
    assert not config.platform_ready("linkedin")
    assert not config.platform_ready("facebook:1")


def test_telegram_embed_targets_exact_post() -> None:
    url = "https://t.me/example_channel/12345"
    assert telegram_post_parts(url) == ("example_channel", "12345")
    assert telegram_embed_url(url) == "https://t.me/example_channel/12345?embed=1&mode=tme"
    assert telegram_post_parts("https://t.me/s/example_channel") is None


def test_telegram_media_ignores_emoji_and_prefers_real_video() -> None:
    html = """
    <div class="tgme_widget_message">
      <span style="background-image:url('https://telegram.org/img/emoji/40/F09F94A5.png')"></span>
      <a class="tgme_widget_message_photo_wrap"
         style="background-image:url('https://cdn4.telesco.pe/file/photo123.jpg')"></a>
      <div class="tgme_widget_message_video_player">
        <video src="https://cdn4.telesco.pe/file/video123.mp4"></video>
      </div>
    </div>
    """
    items = extract_telegram_post_media(html, "https://t.me/example_channel/12345?embed=1&mode=tme", "Example")
    assert [item.kind for item in items][:1] == ["video"]
    assert any(item.url.endswith("photo123.jpg") for item in items)
    assert any(item.url.endswith("video123.mp4") for item in items)
    assert not any("emoji" in item.url.casefold() for item in items)


def test_global_duplicate_clusters_cannot_overlap() -> None:
    raw = (
        '{"clusters":['
        '{"group_ids":[1,2],"confidence":95,"reason":"same event"},'
        '{"group_ids":[2,3],"confidence":90,"reason":"overlap"},'
        '{"group_ids":[4,5],"confidence":40,"reason":"too weak"}'
        ']}'
    )
    clusters = parse_duplicate_clusters(raw, {1, 2, 3, 4, 5})
    assert len(clusters) == 1
    assert clusters[0].group_ids == (1, 2)
