from __future__ import annotations

from content_agent.collectors import normalize_telegram_preview_url, parse_rss, parse_telegram_preview


def test_parse_rss() -> None:
    xml = b"""<?xml version='1.0'?><rss><channel><item><title>News</title><link>https://example.com/n</link><guid>abc</guid><description><![CDATA[<p>Hello <b>world</b></p>]]></description></item></channel></rss>"""
    items = parse_rss(xml)
    assert len(items) == 1
    assert items[0].external_id == "abc"
    assert "Hello" in items[0].raw_text


def test_telegram_url_normalization() -> None:
    assert normalize_telegram_preview_url("@uafree_news") == "https://t.me/s/uafree_news"
    assert normalize_telegram_preview_url("https://t.me/uafree_news") == "https://t.me/s/uafree_news"


def test_parse_telegram_preview() -> None:
    html = '''
    <div class="tgme_widget_message_wrap js-widget_message_wrap">
      <div class="tgme_widget_message text_not_supported_wrap js-widget_message" data-post="uafree_news/42">
        <div class="tgme_widget_message_text js-message_text" dir="auto"><b>Заголовок</b><br>Текст новини</div>
        <time datetime="2026-07-24T10:00:00+00:00"></time>
      </div>
    </div>
    '''
    items = parse_telegram_preview(html)
    assert len(items) == 1
    assert items[0].external_id == "uafree_news/42"
    assert items[0].url.endswith("uafree_news/42")
    assert "Текст новини" in items[0].raw_text
