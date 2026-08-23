from __future__ import annotations

from pathlib import Path

from content_agent.donation_settings_v1_3_1_rc8 import (
    DonationSettings,
    load_donation_settings,
    save_donation_settings,
    strip_known_donation_blocks,
    with_inline_donation,
)
from content_agent.inbox_layout_v1_3_1_rc8 import DEFAULT_WIDTHS, load_widths, save_widths
from content_agent.publisher_factory_v1_3_1_rc8 import Rc8ThreadsPublisher
from content_agent.publishers import PublishContext, PublishError
from content_agent.rc8_topics import central_topic


def test_central_topic_returns_one_compact_label() -> None:
    assert central_topic("У Києві змінили правила руху") == "Київ"
    assert central_topic("НАТО погодило новий пакет допомоги") == "Міжнародка"
    assert central_topic("Верховна Рада проголосувала за закон") == "Політика"
    assert central_topic("ЗСУ знищили російський дрон") == "Війна"
    assert central_topic("OpenAI представила нову AI-модель") == "Технології"
    assert central_topic("У Львові відкрили новий центр") == "Україна"
    assert central_topic("Абсолютно нейтральна дивина без маркерів") == "Інше"


def test_donation_settings_default_is_opt_in(tmp_path: Path) -> None:
    path = tmp_path / "donation.json"
    settings = load_donation_settings(path)
    assert settings.targets == []
    assert settings.text

    saved = save_donation_settings(
        DonationSettings(text="Новий донатний текст", targets=["telegram", "facebook:123"]),
        path,
    )
    loaded = load_donation_settings(path)
    assert loaded == saved
    assert loaded.enabled_for("telegram") is True
    assert loaded.enabled_for("threads") is False


def test_donation_text_replaces_only_legacy_footer() -> None:
    legacy = (
        "Текст новини\n\n"
        "Підтримайте збір Благодійного фонду UA FREE на потреби ЗСУ. "
        "Донат і всі реквізити: https://uafree.org/donate/\n\n"
        "Джерело: https://example.com/news"
    )
    clean = strip_known_donation_blocks(legacy)
    assert "Підтримайте збір" not in clean
    assert clean.endswith("Джерело: https://example.com/news")

    result = with_inline_donation(clean, "НОВИЙ ДОНАТ", True)
    assert result == "Текст новини\n\nНОВИЙ ДОНАТ\n\nДжерело: https://example.com/news"
    assert with_inline_donation(legacy, "НОВИЙ ДОНАТ", False) == clean


def test_inbox_layout_roundtrip_and_sane_bounds(tmp_path: Path) -> None:
    path = tmp_path / "layout.json"
    assert load_widths(path) == DEFAULT_WIDTHS
    saved = save_widths({**DEFAULT_WIDTHS, "title": 910, "sources": 5}, path)
    loaded = load_widths(path)
    assert loaded == saved
    assert loaded["title"] == 910
    assert loaded["sources"] >= 38


class _DonationFailingThreadsInner:
    user_id = "user"
    token = "token"

    def publish(self, text, progress, context, media=None):
        del text, media
        progress = {
            **progress,
            "remote_ids": ["threads-root-1"],
            "published_parts": 1,
            "total_parts": 1,
            "threads_donation_comment_started": True,
        }
        context.save_progress(progress)
        raise PublishError("Threads · донатна відповідь: API rejected the reply", retryable=False)


def test_threads_donation_failure_does_not_fail_confirmed_main_post() -> None:
    saved: list[dict[str, object]] = []
    context = PublishContext(
        before_write=lambda: None,
        save_progress=lambda progress: saved.append(dict(progress)),
    )
    publisher = Rc8ThreadsPublisher(
        _DonationFailingThreadsInner(),  # type: ignore[arg-type]
        donation_text="Підтримайте UA FREE",
        enabled=True,
    )
    result = publisher.publish("Основний текст", {}, context)
    assert result.remote_id == "threads-root-1"
    assert result.progress["donation_status"] == "failed"
    assert "донат" in str(result.progress["donation_error"]).casefold()
    assert saved[-1]["donation_status"] == "failed"
