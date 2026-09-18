from __future__ import annotations

from content_agent.anti_slop import assess_ukrainian_slop, sanitize_text
from content_agent.v2.supervisor.auto_update import select_release


def test_rc14_ua_anti_slop_rejects_machine_templates() -> None:
    text = (
        "Варто зазначити, що це важливий крок. "
        "Це дозволяє працювати швидше. Це дозволяє працювати краще. "
        "Таким чином, майбутнє вже настало."
    )
    result = assess_ukrainian_slop(text, profile="news")
    assert not result.publishable
    assert result.score < result.gate
    assert {f.rule for f in result.findings} >= {"S1", "S2", "S3"}


def test_rc14_ua_anti_slop_keeps_plain_news_copy() -> None:
    result = assess_ukrainian_slop(
        "Команда опублікувала нову версію. Вона виправляє помилку авторизації Google Drive і не змінює формат даних.",
        profile="news",
    )
    assert result.publishable
    assert result.score >= 90


def test_rc14_sanitizer_removes_hidden_controls() -> None:
    assert sanitize_text("тест\u200b текст\ufeff") == "тест текст"


def test_rc14_auto_update_selects_highest_verified_release() -> None:
    payload = [
        {"tag_name": "v2.0.0-rc14", "draft": False, "assets": []},
        {"tag_name": "v2.0.0-rc15", "draft": False, "assets": [
            {"name": "UA_FREE_Content_Tool_v2.0.0-rc15_Windows_Portable.zip", "digest": "sha256:" + "a" * 64}
        ]},
        {"tag_name": "v2.0.0-rc16", "draft": False, "assets": [
            {"name": "wrong.zip", "digest": "sha256:" + "b" * 64}
        ]},
    ]
    chosen = select_release(payload, current_version="2.0.0-rc14")
    assert chosen is not None
    assert chosen.version == "2.0.0-rc15"
    assert chosen.sha256 == "a" * 64


def test_rc14_auto_update_ignores_current_and_older() -> None:
    payload = [{"tag_name": "v2.0.0-rc14", "draft": False, "assets": [
        {"name": "UA_FREE_Content_Tool_v2.0.0-rc14_Windows_Portable.zip", "digest": "sha256:" + "a" * 64}
    ]}]
    assert select_release(payload, current_version="2.0.0-rc14") is None
