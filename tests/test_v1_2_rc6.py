import os

from content_agent import codex_engine_v1_3
from content_agent.config import AppConfig
from content_agent.global_duplicates_v1_3_rc6 import build_global_duplicate_prompt, parse_duplicate_clusters
from content_agent.models import Article, NewsGroup
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


def test_global_prompt_contains_every_new_group() -> None:
    groups = []
    for group_id in (10, 20, 30):
        article = Article(
            id=group_id,
            source_id=1,
            title=f"Title {group_id}",
            url=f"https://t.me/example/{group_id}",
            raw_text=f"Unique text for group {group_id}",
            status="new",
        )
        groups.append(
            NewsGroup(
                id=group_id,
                canonical_title=f"Group {group_id}",
                status="new",
                created_at="2026-08-14T08:00:00+00:00",
                updated_at="2026-08-14T08:00:00+00:00",
                source_count=1,
                articles=[article],
            )
        )
    prompt = build_global_duplicate_prompt(groups)
    for group_id in (10, 20, 30):
        assert f"ID={group_id}" in prompt
        assert f"Unique text for group {group_id}" in prompt


def test_codex_subprocess_proxy_hides_console_on_windows(monkeypatch) -> None:
    if os.name != "nt":
        return
    captured = {}

    def fake_popen(*args, **kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(codex_engine_v1_3.subprocess, "Popen", fake_popen)
    proxy = codex_engine_v1_3._HiddenSubprocessProxy(codex_engine_v1_3.subprocess)
    proxy.Popen(["codex.exe", "app-server"])
    assert int(captured.get("creationflags", 0)) & int(codex_engine_v1_3.subprocess.CREATE_NO_WINDOW)


def test_global_duplicate_large_inbox_is_split_into_bounded_batches() -> None:
    from content_agent.global_duplicates_v1_3_rc6 import build_global_duplicate_batches

    groups = []
    for group_id in range(1, 61):
        article = Article(
            id=group_id,
            source_id=1,
            title=f"Title {group_id}",
            url=f"https://example.com/{group_id}",
            raw_text=(f"Company Alpha event {group_id % 9} details and update " * 30),
            status="new",
        )
        groups.append(
            NewsGroup(
                id=group_id,
                canonical_title=f"Company Alpha update {group_id % 9} item {group_id}",
                status="new",
                created_at="2026-08-17T08:00:00+00:00",
                updated_at="2026-08-17T08:00:00+00:00",
                source_count=1,
                articles=[article],
            )
        )
    batches = build_global_duplicate_batches(groups)
    assert len(batches) > 1
    assert all(2 <= len(batch) <= 20 for batch in batches)
    assert all(len(build_global_duplicate_prompt(batch)) <= 8000 for batch in batches)


def test_global_duplicate_prompt_caps_feedback_and_graph_memory() -> None:
    groups = []
    for group_id in (1, 2):
        groups.append(
            NewsGroup(
                id=group_id,
                canonical_title=f"Group {group_id}",
                status="new",
                created_at="2026-08-17T08:00:00+00:00",
                updated_at="2026-08-17T08:00:00+00:00",
                source_count=1,
                articles=[Article(id=group_id, source_id=1, title="x", url="https://e/x", raw_text="text " * 500, status="new")],
            )
        )
    feedback = [
        {"decision": "merged", "anchor_text": "A" * 1000, "candidate_text": "B" * 1000}
        for _ in range(100)
    ]
    prompt = build_global_duplicate_prompt(groups, feedback=feedback, graph_memory="M" * 10000)
    assert len(prompt) <= 8000
    assert prompt.count("ОБ'ЄДНАНО") <= 12
