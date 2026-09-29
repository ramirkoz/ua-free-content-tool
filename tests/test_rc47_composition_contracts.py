from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from content_agent.app.container import AppServices, build_services
from content_agent.config import AppConfig
from content_agent.database import Database as LegacyDatabase
from content_agent.v2.ai.contracts import AIRequest, UnifiedAIResult
from content_agent.v2.ai.gateway import AIGateway
from content_agent.v2.ai import service as ai_service
from content_agent.v2.publishing.outcomes import PublicationOutcome
from content_agent.v2.storage.factory import create_database
from content_agent.v2.storage.reliable import Database as ReliableDatabase


def _seed_queue(db) -> tuple[int, int]:
    source_id = db.add_source("rss", "RC47 source", "https://example.com/rc47-feed")
    now = datetime.now(timezone.utc).isoformat()
    with db.connect() as con:
        group_id = int(
            con.execute(
                "INSERT INTO news_groups(canonical_title,created_at,updated_at) VALUES(?,?,?)",
                ("RC47", now, now),
            ).lastrowid
        )
        article_id = int(
            con.execute(
                "INSERT INTO articles(source_id,group_id,external_id,content_hash,title,url,raw_text,discovered_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    source_id,
                    group_id,
                    "rc47",
                    "rc47-hash",
                    "RC47",
                    "https://example.com/rc47",
                    "body",
                    now,
                ),
            ).lastrowid
        )
    scheduled = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    batch_id = db.create_batch(article_id, scheduled, {"telegram:test": "hello"})
    target_id = db.get_batch(batch_id).targets[0].id
    return batch_id, target_id


def test_build_services_is_single_active_composition(tmp_path: Path) -> None:
    db = create_database(tmp_path / "composition.sqlite3")
    services = build_services(config=AppConfig(), database=db)
    assert isinstance(services, AppServices)
    assert services.db is db
    assert isinstance(services.db, ReliableDatabase)
    assert isinstance(services.ai, AIGateway)


def test_numbered_v2_migration_backfills_unknown_outcome(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    legacy = LegacyDatabase(path)
    batch_id, target_id = _seed_queue(legacy)
    legacy.mark_target_failed(target_id, "Результат невідомий; перевірте платформу вручну")

    db = create_database(path)
    with db.connect() as con:
        columns = {str(row[1]) for row in con.execute("PRAGMA table_info(publication_targets)").fetchall()}
        migrations = {str(row[0]) for row in con.execute("SELECT id FROM schema_migrations").fetchall()}
        outcome = str(con.execute("SELECT outcome FROM publication_targets WHERE id=?", (target_id,)).fetchone()[0])
    assert "outcome" in columns
    assert "0009_publication_target_outcome" in migrations
    assert outcome == PublicationOutcome.UNKNOWN.value
    with pytest.raises(ValueError, match="Повтор заблоковано"):
        db.resume_batch(batch_id)


def test_operator_confirmation_resolves_unknown_for_resume(tmp_path: Path) -> None:
    db = create_database(tmp_path / "resolved.sqlite3")
    batch_id, target_id = _seed_queue(db)
    db.mark_target_failed(target_id, "unknown outcome; перевірте платформу вручну")
    assert db.publication_target_outcome(target_id) is PublicationOutcome.UNKNOWN
    db.confirm_target_not_sent(target_id)
    assert db.publication_target_outcome(target_id) is PublicationOutcome.CONFIRMED_NOT_SENT
    db.resume_batch(batch_id)
    assert db.get_batch(batch_id).status == "pending"


def test_mark_target_sent_records_explicit_outcome(tmp_path: Path) -> None:
    db = create_database(tmp_path / "sent.sqlite3")
    _batch_id, target_id = _seed_queue(db)
    db.mark_target_sent(target_id, "remote-123")
    assert db.publication_target_outcome(target_id) is PublicationOutcome.SENT


def test_typed_ai_request_runs_through_backend_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[AIRequest] = []

    class FakeBackend:
        name = "fake"

        def run(self, request: AIRequest) -> UnifiedAIResult:
            seen.append(request)
            return UnifiedAIResult(
                text="OK",
                backend="fake",
                provider="fake-provider",
                model="fake-model",
                label="fake",
            )

    monkeypatch.setattr(ai_service, "load_backend_settings", lambda: SimpleNamespace(active_backend="fake"))
    monkeypatch.setattr(ai_service, "_backend_for", lambda _name, _settings: FakeBackend())
    request = AIRequest(
        prompt="test",
        task_timeout_seconds=17,
        skip_providers=("blocked",),
        skip_models=("old-model",),
    )
    result = ai_service.execute_request(request)
    assert result.text == "OK"
    assert seen == [request]


def test_rc47_adds_no_new_versioned_mainwindow_layer() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    forbidden = [
        path.relative_to(repo_root).as_posix()
        for path in (repo_root / "content_agent").rglob("*.py")
        if "window_rc47" in path.name.casefold()
    ]
    assert forbidden == []
