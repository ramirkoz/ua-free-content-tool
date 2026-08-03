from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from content_agent.database import DATABASE_SCHEMA_VERSION, Database
from content_agent.models import CollectedArticle
from content_agent.scheduling import KYIV


def _today() -> str:
    return datetime.now(KYIV).isoformat()


def test_database_rejects_non_today_collected_items(tmp_path: Path) -> None:
    db = Database(tmp_path / "db.sqlite3")
    source = db.add_source("rss", "Test", "https://example.com/feed")
    yesterday = (datetime.now(KYIV) - timedelta(days=1)).isoformat()
    assert db.insert_collected(
        source,
        [CollectedArticle("old", "Old", "https://example.com/old", "old body", yesterday)],
    ) == 0
    assert db.list_groups() == []


def test_database_keeps_paraphrased_sources_in_separate_blocks_until_manual_merge(tmp_path: Path) -> None:
    db = Database(tmp_path / "db.sqlite3")
    first = db.add_source("telegram", "One", "@channel_one")
    second = db.add_source("rss", "Two", "https://example.com/feed")
    assert db.insert_collected(
        first,
        [CollectedArticle(
            "one/1",
            "У Запоріжжі пролунали вибухи",
            "https://t.me/channel_one/1",
            "У місті було гучно після атаки дронів. Деталь першого джерела.",
            _today(),
        )],
    ) == 1
    assert db.insert_collected(
        second,
        [CollectedArticle(
            "two-1",
            "Росіяни атакували Запоріжжя дронами",
            "https://example.com/1",
            "Ворог завдав удару по обласному центру. Деталь другого джерела.",
            _today(),
        )],
    ) == 1
    groups = db.list_groups()
    assert len(groups) == 2
    assert {group.source_count for group in groups} == {1}
    target, source = groups
    assert db.merge_groups(target.id, [target.id, source.id]) == 1
    merged = db.get_group(target.id)
    assert merged.source_count == 2
    assert "Деталь першого джерела" in merged.combined_text
    assert "Деталь другого джерела" in merged.combined_text


def test_rejected_group_does_not_absorb_later_similar_event(tmp_path: Path) -> None:
    db = Database(tmp_path / "db.sqlite3")
    first = db.add_source("rss", "One", "https://example.com/one")
    second = db.add_source("rss", "Two", "https://example.com/two")
    db.insert_collected(first, [CollectedArticle(
        "a", "Кабмін ухвалив постанову про виплати ВПО", "https://example.com/a",
        "Уряд затвердив нові виплати переселенцям.", _today(),
    )])
    group_id = db.list_groups()[0].id
    db.set_group_status(group_id, "rejected")
    db.insert_collected(second, [CollectedArticle(
        "b", "Уряд змінив правила допомоги переселенцям", "https://example.com/b",
        "Кабінет Міністрів прийняв рішення щодо грошової допомоги ВПО.", _today(),
    )])
    active = db.list_groups()
    assert len(active) == 1
    assert active[0].id != group_id
    rejected = db.list_groups(status="rejected")
    assert [group.id for group in rejected] == [group_id]
    assert db.get_group(group_id).source_count == 1


def test_r7_database_migrates_in_place(tmp_path: Path) -> None:
    path = tmp_path / "r7.sqlite3"
    con = sqlite3.connect(path)
    try:
        con.executescript(
            """
            PRAGMA foreign_keys=ON;
            CREATE TABLE sources (
              id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, name TEXT NOT NULL,
              url TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, last_checked_at TEXT,
              created_at TEXT NOT NULL, UNIQUE(kind,url)
            );
            CREATE TABLE articles (
              id INTEGER PRIMARY KEY AUTOINCREMENT, source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
              external_id TEXT NOT NULL, content_hash TEXT NOT NULL, title TEXT NOT NULL, url TEXT NOT NULL,
              raw_text TEXT NOT NULL, published_at TEXT, discovered_at TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'new', headline TEXT NOT NULL DEFAULT '', fact_card TEXT NOT NULL DEFAULT '',
              rewrite_text TEXT NOT NULL DEFAULT '', platform_texts_json TEXT NOT NULL DEFAULT '{}',
              UNIQUE(source_id,external_id), UNIQUE(content_hash)
            );
            CREATE TABLE publication_batches (
              id INTEGER PRIMARY KEY AUTOINCREMENT, article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
              scheduled_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', lease_owner TEXT, lease_until TEXT,
              attempts INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE publication_targets (
              id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id INTEGER NOT NULL REFERENCES publication_batches(id) ON DELETE CASCADE,
              platform TEXT NOT NULL, payload_text TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', remote_id TEXT,
              last_error TEXT, progress_json TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL,
              UNIQUE(batch_id,platform)
            );
            PRAGMA user_version=1;
            """
        )
        now = _today()
        con.execute(
            "INSERT INTO sources(kind,name,url,created_at) VALUES('rss','Old','https://example.com/feed',?)",
            (now,),
        )
        con.execute(
            """INSERT INTO articles(source_id,external_id,content_hash,title,url,raw_text,published_at,discovered_at,
            status,headline,fact_card,rewrite_text,platform_texts_json)
            VALUES(1,'legacy','hash','Legacy title','https://example.com/a','Legacy body',?,?,
            'draft','Saved title','Saved facts','Saved rewrite','{"telegram":"Saved TG"}')""",
            (now, now),
        )
        con.commit()
    finally:
        con.close()

    db = Database(path)
    backups = list((tmp_path / "backups").glob("UA_FREE_pre_R8_schema_1_*.zip"))
    assert len(backups) == 1
    with db.connect() as migrated:
        assert migrated.execute("PRAGMA user_version").fetchone()[0] == DATABASE_SCHEMA_VERSION
        article_columns = {row[1] for row in migrated.execute("PRAGMA table_info(articles)")}
        batch_columns = {row[1] for row in migrated.execute("PRAGMA table_info(publication_batches)")}
        assert "group_id" in article_columns
        assert "cleanup_error" in batch_columns
    groups = db.list_groups()
    assert len(groups) == 1
    group = db.get_group(groups[0].id)
    assert group.rewrite_text == "Saved rewrite"
    assert group.platform_texts["telegram"] == "Saved TG"


def test_startup_archives_old_unqueued_blocks(tmp_path: Path) -> None:
    db = Database(tmp_path / "db.sqlite3")
    source = db.add_source("rss", "Old", "https://example.com/old-feed")
    old = (datetime.now(KYIV) - timedelta(days=1)).isoformat()
    db.insert_collected(
        source,
        [CollectedArticle("old-1", "Учорашня новина", "https://example.com/old", "Старий текст", old)],
        enforce_today=False,
    )
    assert len(db.list_groups()) == 1
    assert db.archive_stale_groups() == 1
    assert db.list_groups() == []
    assert len(db.list_groups(status="archived")) == 1
