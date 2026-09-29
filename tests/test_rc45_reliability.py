from __future__ import annotations

import json
import re
import tkinter as tk
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import content_agent.backup as backup
from content_agent.ai_router import AIRouterError, AIResult
from content_agent.fact_guard import FactGuardResult
from content_agent.rewrite_pipeline_v1_3 import RewriteCandidate
from content_agent.v2.storage.factory import create_database
from content_agent.v2.storage.reliable import Database as ReliableDatabase


def _seed_article(db: ReliableDatabase) -> tuple[int, int, int]:
    source_id = db.add_source("rss", "RC45 source", "https://example.com/feed")
    now = datetime.now(timezone.utc).isoformat()
    with db.connect() as con:
        group_id = int(con.execute("INSERT INTO news_groups(canonical_title,created_at,updated_at) VALUES(?,?,?)", ("RC45", now, now)).lastrowid)
        article_id = int(con.execute("INSERT INTO articles(source_id,group_id,external_id,content_hash,title,url,raw_text,discovered_at) VALUES(?,?,?,?,?,?,?,?)", (source_id, group_id, "rc45", "rc45-hash", "RC45", "https://example.com/a", "body", now)).lastrowid)
    return source_id, group_id, article_id


def test_create_database_is_active_reliable_composition(tmp_path: Path) -> None:
    db = create_database(tmp_path / "active.sqlite3")
    assert isinstance(db, ReliableDatabase)
    assert hasattr(db, "list_manual_topics")
    assert hasattr(db, "reconcile_external_successes")


def test_rc44_schema_backup_round_trip_restores_manual_topics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "content_agent.sqlite3"
    db = create_database(db_path)
    source_id = db.add_source("rss", "Backup source", "https://example.com/backup")
    topic_id = db.create_manual_topic("Новини")
    db.set_source_topic(source_id, topic_id)
    monkeypatch.setattr(backup, "database_path", lambda: db_path)
    monkeypatch.setattr(backup, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(backup, "backups_dir", lambda: tmp_path / "Backups")
    monkeypatch.setattr(backup, "config_path", lambda: tmp_path / "config.portable")
    monkeypatch.setattr(backup, "portable_key_path", lambda: tmp_path / "portable.key")
    monkeypatch.setattr(backup, "portable_mode", lambda: True)
    archive = backup.create_backup()
    assert archive.is_file()
    backup._validate_database(db_path)
    db.delete_manual_topic(topic_id)
    assert db.source_topic_rows()[0]["topic_name"] == ""
    result = backup.import_backup(archive)
    assert result.imported_database is True
    restored = create_database(db_path)
    rows = restored.source_topic_rows()
    assert rows[0]["topic_name"] == "Новини"
    assert rows[0]["topic_id"] is not None


def test_unknown_external_outcome_blocks_resume_and_reschedule(tmp_path: Path) -> None:
    db = create_database(tmp_path / "queue.sqlite3")
    _source_id, _group_id, article_id = _seed_article(db)
    scheduled = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    batch_id = db.create_batch(article_id, scheduled, {"telegram:test": "hello"})
    target_id = db.get_batch(batch_id).targets[0].id
    db.mark_target_failed(target_id, "Результат невідомий; перевірте платформу вручну")
    with pytest.raises(ValueError, match="Повтор заблоковано"):
        db.resume_batch(batch_id)
    with pytest.raises(ValueError, match="Повтор заблоковано"):
        db.reschedule_recoverable_batches({batch_id: (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()})


def test_started_without_completed_progress_blocks_retry(tmp_path: Path) -> None:
    db = create_database(tmp_path / "progress.sqlite3")
    _source_id, _group_id, article_id = _seed_article(db)
    scheduled = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    batch_id = db.create_batch(article_id, scheduled, {"facebook:page": "hello"})
    target_id = db.get_batch(batch_id).targets[0].id
    db.save_target_progress(target_id, {"facebook_started": True})
    db.mark_target_failed(target_id, "transport interrupted")
    with pytest.raises(ValueError, match="незавершений зовнішній запис"):
        db.resume_batch(batch_id)


def test_rc45_accept_gate_rejects_slop_even_when_fact_guard_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    from content_agent.anti_slop import SlopAssessment
    from content_agent import rewrite_pipeline_v1_4_rc27 as rc27
    route = AIResult("", "nvidia", "model", "route", 1, ())
    candidate = RewriteCandidate(headline="Заголовок", rewrite="Текст без фактичних помилок, але з машинним стилем.", model_fact_card="", route=route, guard=FactGuardResult(True, (), 100))
    monkeypatch.setattr(rc27, "assess_ukrainian_slop", lambda *_args, **_kwargs: SlopAssessment(50, 88, False, (), candidate.rewrite))
    accepted, kind, _detail, _slop = rc27._accept_candidate(candidate, language="uk")
    assert accepted is None
    assert kind == "slop"


def test_slop_failure_never_falls_into_fact_safe_repair(monkeypatch: pytest.MonkeyPatch) -> None:
    from content_agent.anti_slop import SlopAssessment
    from content_agent import rewrite_pipeline_v1_4_rc27 as rc27
    route = AIResult("HEADLINE: H\nTEXT: T", "nvidia", "model", "route", 1, ())
    candidate = RewriteCandidate(headline="H", rewrite="Текст", model_fact_card="", route=route, guard=FactGuardResult(True, (), 100))
    calls = {"router": 0}
    repair_prompts: list[str] = []
    def fake_router(*_args, **_kwargs):
        calls["router"] += 1
        if calls["router"] == 1:
            return route
        raise AIRouterError("no more routes")
    def fake_repair(_route, prompt, *_args, **_kwargs):
        repair_prompts.append(prompt)
        return candidate
    monkeypatch.setattr(rc27.rc17, "install_rc17_fact_guard", lambda: None)
    monkeypatch.setattr(rc27.base, "_router_call", fake_router)
    monkeypatch.setattr(rc27.base, "_candidate", lambda *_args, **_kwargs: candidate)
    monkeypatch.setattr(rc27.rc17, "_same_provider_repair", fake_repair)
    monkeypatch.setattr(rc27, "assess_ukrainian_slop", lambda *_args, **_kwargs: SlopAssessment(50, 88, False, (), "Текст"))
    with pytest.raises(AIRouterError):
        rc27.candidate_after_router_rc27("prompt", "local", object(), language="uk", max_candidates=1)
    assert any(prompt.startswith("HUMAN COPY REPAIR") for prompt in repair_prompts)
    assert not any(prompt.startswith("FACT-SAFE REPAIR") for prompt in repair_prompts)


def test_rc45_adds_no_new_versioned_runtime_layer() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    rc45_named = [path.relative_to(repo_root).as_posix() for path in (repo_root / "content_agent").rglob("*.py") if re.search(r"(?:^|_)rc45(?:_|\.|$)|window_rc45", path.name)]
    assert rc45_named == [], "RC45 must add behavior to stable services/components, not another *_rc45 runtime layer: " + repr(sorted(rc45_named))


def test_rc44_topic_filter_widgets_are_actually_managed() -> None:
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable")
    try:
        from tkinter import ttk
        from content_agent.v2.ui.manual_topics_window_rc44 import MainWindow
        tab = ttk.Frame(root); tab.pack(fill="both", expand=True)
        tree_frame = ttk.Frame(tab); tree_frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(tree_frame); tree.pack(fill="both", expand=True)
        window = object.__new__(MainWindow)
        # The active filter deliberately binds StringVar to the owning Tk root.
        # This characterization harness bypasses __init__, so provide the root
        # explicitly instead of relying on Tk's implicit default-root behavior.
        window.root = root
        window.groups_tree = tree
        window.refresh_groups = lambda: None
        window._refresh_inbox_filter_choices = lambda: None
        window.reset_manual_topic_filters = lambda: None
        MainWindow._install_manual_topic_inbox_filters(window)
        root.update_idletasks()
        assert window.inbox_source_filter_box.winfo_manager() == "pack"
        assert window.inbox_topic_filter_box.winfo_manager() == "pack"
        assert window._manual_topic_filter_bar.winfo_manager() == "pack"
        assert tab.pack_slaves()[0] is window._manual_topic_filter_bar
        assert tab.pack_slaves()[1] is tree_frame
    finally:
        root.destroy()
