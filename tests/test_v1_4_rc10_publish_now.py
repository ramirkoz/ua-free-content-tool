from __future__ import annotations

import json
from datetime import datetime, timezone

from content_agent.database import _iso
from content_agent.database_v1_4_rc10 import Database


UTC = timezone.utc


def _seed_article(db: Database, *, suffix: str = "x") -> tuple[int, int]:
    now = _iso()
    with db.connect() as conn:
        source_id = int(
            conn.execute(
                "INSERT INTO sources(kind,name,url,created_at) VALUES('url',?,?,?)",
                (f"Source {suffix}", f"https://example.com/{suffix}", now),
            ).lastrowid
        )
        group_id = int(
            conn.execute(
                "INSERT INTO news_groups(canonical_title,created_at,updated_at) VALUES(?,?,?)",
                (f"Story {suffix}", now, now),
            ).lastrowid
        )
        article_id = int(
            conn.execute(
                """
                INSERT INTO articles(
                    source_id,group_id,external_id,content_hash,title,url,raw_text,discovered_at
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    source_id,
                    group_id,
                    f"ext-{suffix}",
                    f"hash-{suffix}",
                    f"Story {suffix}",
                    f"https://example.com/{suffix}/story",
                    "body",
                    now,
                ),
            ).lastrowid
        )
    return group_id, article_id


def _insert_normal_batch(db: Database, article_id: int, platform: str, scheduled_at: str) -> int:
    now = _iso()
    with db.connect() as conn:
        batch_id = int(
            conn.execute(
                """
                INSERT INTO publication_batches(article_id,scheduled_at,status,created_at,updated_at)
                VALUES(?,?,'pending',?,?)
                """,
                (article_id, scheduled_at, now, now),
            ).lastrowid
        )
        conn.execute(
            """
            INSERT INTO publication_targets(batch_id,platform,payload_text,status,progress_json,updated_at)
            VALUES(?,?,?,'pending','{}',?)
            """,
            (batch_id, platform, "normal", now),
        )
    return batch_id


def test_publish_now_does_not_move_normal_destination_schedule(tmp_path) -> None:
    db = Database(tmp_path / "content.sqlite3")
    _group, article_id = _seed_article(db, suffix="schedule")
    normal_at = "2026-09-03T15:00:00+00:00"
    normal_id = _insert_normal_batch(db, article_id, "telegram", normal_at)

    immediate = db.create_immediate_targets(
        article_id,
        {"threads": "now on threads"},
        display_title="Publish now",
    )
    assert immediate.created == ["threads"]

    # A publish-now row is not a scheduler slot for that destination.
    assert db.latest_scheduled_for_target("threads") is None
    assert db.scheduled_times_for_target("threads") == []
    assert db.latest_scheduled_for_target("telegram") == normal_at

    # Active queue listings hide immediate technical batches entirely.
    active = db.list_batches(statuses={"pending"})
    assert [batch.id for batch in active] == [normal_id]


def test_publish_now_is_claimed_before_ordinary_overdue_queue(tmp_path) -> None:
    db = Database(tmp_path / "content.sqlite3")
    _group1, normal_article = _seed_article(db, suffix="normal")
    _group2, immediate_article = _seed_article(db, suffix="immediate")
    normal_id = _insert_normal_batch(db, normal_article, "telegram", "2025-01-01T00:00:00+00:00")

    immediate = db.create_immediate_targets(
        immediate_article,
        {"threads": "publish me now"},
        display_title="Immediate",
    )
    immediate_id = immediate.batch_ids["threads"]

    claimed = db.claim_due_batch(owner="rc10-test", lease_seconds=60)
    assert claimed is not None
    assert claimed.id == immediate_id
    assert claimed.id != normal_id


def test_publish_now_does_not_duplicate_an_active_target_for_same_story(tmp_path) -> None:
    db = Database(tmp_path / "content.sqlite3")
    _group, article_id = _seed_article(db, suffix="active")
    _insert_normal_batch(db, article_id, "telegram", "2026-09-03T15:00:00+00:00")

    result = db.create_immediate_targets(
        article_id,
        {"telegram": "same story"},
        display_title="Same story",
    )
    assert result.created == []
    assert result.blocked_active == ["telegram"]


def test_terminal_publish_now_history_uses_real_request_time(tmp_path) -> None:
    db = Database(tmp_path / "content.sqlite3")
    _group, article_id = _seed_article(db, suffix="history")
    result = db.create_immediate_targets(
        article_id,
        {"telegram": "now"},
        display_title="History time",
    )
    batch_id = result.batch_ids["telegram"]

    with db.connect() as conn:
        conn.execute("UPDATE publication_targets SET status='sent' WHERE batch_id=?", (batch_id,))
        conn.execute("UPDATE publication_batches SET status='completed' WHERE id=?", (batch_id,))

    assert db.finalize_immediate_timestamp(batch_id) is True
    with db.connect() as conn:
        row = conn.execute(
            "SELECT b.scheduled_at,t.progress_json FROM publication_batches b JOIN publication_targets t ON t.batch_id=b.id WHERE b.id=?",
            (batch_id,),
        ).fetchone()
    progress = json.loads(str(row["progress_json"]))
    assert progress["publish_now"] is True
    assert str(row["scheduled_at"]) == progress["publish_now_requested_at"]
    assert datetime.fromisoformat(str(row["scheduled_at"])).tzinfo is not None
