from content_agent.editorial_memory import rank_topic_candidates
from content_agent.topic_search import build_topic_prompt, index_topic_candidate_rows


def test_malformed_legacy_group_ids_are_skipped() -> None:
    rows = [
        {"group_id": "19…", "title": "legacy", "text": "старий кривий запис"},
        {"group_id": "19•", "title": "legacy2", "text": "ще один кривий запис"},
        {"group_id": "71115", "title": "valid", "text": "військові підрозділи продовжують навчання"},
        {"group_id": 71118, "title": "valid2", "text": "військові підрозділи провели навчання"},
    ]
    rows_by_id, skipped = index_topic_candidate_rows(rows)
    assert set(rows_by_id) == {71115, 71118}
    assert skipped == ["19…", "19•"]


def test_topic_pipeline_keeps_valid_rows_with_malformed_legacy_rows_present() -> None:
    rows = [
        {"group_id": "19…", "title": "legacy", "text": "старий кривий запис"},
        {"group_id": "71115", "title": "valid", "text": "військові підрозділи продовжують навчання"},
        {"group_id": 71118, "title": "valid2", "text": "військові підрозділи провели навчання"},
    ]
    ranked = rank_topic_candidates("військові підрозділи провели навчання", rows, limit=10)
    assert all(item.group_id in {71115, 71118} for item in ranked)

    prompt = build_topic_prompt("Навчання військових", "військові підрозділи провели навчання", rows)
    assert "ID 71115" in prompt
    assert "ID 71118" in prompt
    assert "19…" not in prompt
