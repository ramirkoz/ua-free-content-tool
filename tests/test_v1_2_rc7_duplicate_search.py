from __future__ import annotations

from types import SimpleNamespace

import pytest

from content_agent import global_duplicates_v1_2_2_rc7 as dup
from content_agent.models import Article, NewsGroup


def _group(group_id: int, title: str, text: str, minute: int = 0) -> NewsGroup:
    article = Article(
        id=group_id,
        source_id=group_id,
        title=title,
        url=f"https://example.com/{group_id}",
        raw_text=text,
        status="new",
        published_at=f"2026-08-17T10:{minute % 60:02d}:00+00:00",
        source_name="test",
    )
    return NewsGroup(
        id=group_id,
        canonical_title=title,
        status="new",
        created_at="2026-08-17T10:00:00+00:00",
        updated_at="2026-08-17T10:00:00+00:00",
        source_count=1,
        include_source_link=True,
        articles=[article],
    )


def test_rc7_finds_visible_zaporizhzhia_duplicate_in_large_inbox(monkeypatch: pytest.MonkeyPatch) -> None:
    groups = [
        _group(i, f"Окрема новина номер {i}", f"Самостійна подія номер {i} без зв'язку з іншими матеріалами.", i)
        for i in range(1, 1001)
    ]
    groups[41] = _group(
        42,
        "Антон Бриль заблокував рахунки освіти Запоріжжя через судову справу",
        "Через судову справу заблоковано рахунки закладів освіти Запоріжжя.",
        38,
    )
    groups[36] = _group(
        37,
        "Через бізнесмена Антона Бриля заблокували рахунки всієї освіти Запоріжжя. Через суд",
        "Йдеться про блокування рахунків освіти Запоріжжя у тій самій судовій справі.",
        38,
    )

    monkeypatch.setattr(dup, "run_ai", lambda *a, **k: (_ for _ in ()).throw(dup.AIRouterError("offline")))
    result = dup.find_global_duplicate_clusters(groups, deadline_seconds=10)
    assert any({37, 42} <= set(cluster.group_ids) for cluster in result)


def test_rc7_dense_medium_frequency_noise_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    groups: list[NewsGroup] = []
    for i in range(1, 1001):
        bucket = i % 40
        title = f"Подія {i} сектор {bucket} регіон тест"
        noise = " ".join(f"маркер{(bucket + step) % 40}" for step in range(12))
        groups.append(_group(i, title, f"{noise} унікальний текст {i}", i))
    groups[100] = _group(101, "Пожежа на складі у Києві 17 серпня", "Пожежа на складі у Києві, рятувальники локалізували вогонь.")
    groups[700] = _group(701, "У Києві 17 серпня сталася пожежа на складі", "Рятувальники локалізували пожежу на тому самому складі у Києві.")

    monkeypatch.setattr(dup, "run_ai", lambda *a, **k: (_ for _ in ()).throw(dup.AIRouterError("offline")))
    result = dup.find_global_duplicate_clusters(groups, deadline_seconds=10)
    assert any({101, 701} <= set(cluster.group_ids) for cluster in result)


def test_rc7_ai_none_does_not_erase_manual_review_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    groups = [
        _group(1, "Ракета влучила у склад у місті", "Ракета влучила у склад о 10:00, пожежу локалізували."),
        _group(2, "У місті ракета влучила у склад", "О 10:00 ракета влучила у той самий склад, пожежу локалізували."),
    ]

    def fake_run_ai(prompt: str, **kwargs):
        kwargs["validator"]("NONE")
        return SimpleNamespace(text="NONE")

    monkeypatch.setattr(dup, "run_ai", fake_run_ai)
    result = dup.find_global_duplicate_clusters(groups, deadline_seconds=10)
    assert any({1, 2} <= set(cluster.group_ids) for cluster in result)
    assert "локальні кандидати" in dup.last_duplicate_search_label()
