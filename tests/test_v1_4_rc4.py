from __future__ import annotations

import inspect

from content_agent.topic_classifier_v1_4_rc4 import (
    TOPIC_CATEGORIES,
    TopicAssignmentStore,
    classify_topic_context,
)
from content_agent.ui.global_duplicates_dialog_v1_3_rc6 import default_cluster_selected
from content_agent.ui.v1_4_rc4_window import MainWindow, _decorate_destination_label


def _context(title: str, *articles: str, body: str = "") -> dict[str, object]:
    return {
        "canonical_title": title,
        "article_titles": list(articles),
        "body": body,
    }


def test_rc4_topic_uses_whole_event_and_keeps_geography_as_tag() -> None:
    decision = classify_topic_context(
        _context(
            "Логістичний центр Roshen під Києвом зруйновано після російської атаки",
            "Вночі Росія атакувала логістичний центр на Київщині дронами",
            "Кадри зруйнованого центру Roshen після удару БПЛА",
            body="Рятувальники працюють на місці удару. Під час атаки застосовувалися дрони.",
        )
    )
    assert decision.topic == "Війна"
    assert "Київщина" in decision.tags or "Київ" in decision.tags
    assert decision.confidence >= 70


def test_rc4_topic_does_not_turn_kyiv_into_a_topic() -> None:
    decision = classify_topic_context(
        _context(
            "У Києві перший тиждень навчального року пройде у змішаному форматі",
            "Школи Києва планують очно-дистанційне навчання",
            body="Освітні заклади готують укриття та графіки для учнів.",
        )
    )
    assert decision.topic == "Суспільство"
    assert "Київ" in decision.tags
    assert "Київ" not in TOPIC_CATEGORIES


def test_rc4_topic_separates_technology_from_location() -> None:
    decision = classify_topic_context(
        _context(
            "Meta спрощує Login with Facebook у сторонніх застосунках",
            "Facebook запускає one-tap sign-on на Android і Web",
            body="Оновлення SDK скорочує повторний вхід і змінює Limited Login.",
        )
    )
    assert decision.topic == "Технології"


def test_rc4_topic_cache_and_manual_override(tmp_path) -> None:
    store = TopicAssignmentStore(tmp_path / "topics.json")
    context = _context("NASA готує новий космічний телескоп", body="Дослідники перевіряють наукові прилади місії NASA.")
    automatic, changed = store.resolve(10, context)
    assert changed is True
    assert automatic.topic == "Наука"
    store.save()

    cached, changed = store.resolve(10, context)
    assert changed is False
    assert cached.topic == "Наука"

    store.set_manual(10, "Технології")
    manual, changed = store.resolve(10, context)
    assert changed is False
    assert manual.manual is True
    assert manual.topic == "Технології"


def test_rc4_destination_labels_always_show_network() -> None:
    assert _decorate_destination_label("Антон Козирєв", "threads") == "Антон Козирєв (Threads)"
    assert _decorate_destination_label("Антон Козирєв", "linkedin") == "Антон Козирєв (LinkedIn)"
    assert _decorate_destination_label("@enotzp", "telegram") == "@enotzp (Telegram)"
    assert _decorate_destination_label("@cf.uafree (Instagram)", "instagram") == "@cf.uafree (Instagram)"


def test_rc4_duplicate_review_only_preselects_high_confidence() -> None:
    assert default_cluster_selected(95) is True
    assert default_cluster_selected(90) is True
    assert default_cluster_selected(89) is False
    assert default_cluster_selected(77) is False


def test_rc4_queue_and_history_are_grouped_editorial_views() -> None:
    queue_source = inspect.getsource(MainWindow._build_queue_tab)
    history_source = inspect.getsource(MainWindow._build_history_tab)
    assert 'columns=("title", "next", "state")' in queue_source
    assert 'columns=("profile", "network", "schedule", "status", "error")' in queue_source
    assert 'columns=("title", "period", "result")' in history_source
    assert '"Розкладка по мережах"' in history_source
    assert MainWindow.VERSION_LABEL == "1.4.0-rc4"


def test_rc4_inbox_hides_internal_group_id() -> None:
    source = inspect.getsource(MainWindow._install_rc4_inbox)
    assert '("status", "title", "topic", "sources", "published", "score", "history")' in source
