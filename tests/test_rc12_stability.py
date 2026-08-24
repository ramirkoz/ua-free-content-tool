from __future__ import annotations

from dataclasses import dataclass

from content_agent.models import MediaPayload
from content_agent.publishers import PublishContext, PublishError, PublishResult
from content_agent.publisher_factory_v1_3_1_rc8 import Rc8ThreadsPublisher
import content_agent.publisher_factory_v1_3_1_rc8 as factory_module


class FakeInner:
    user_id = "u1"
    token = "t1"

    def __init__(self):
        self.calls = []

    def publish(self, text, progress, context, media=None):
        self.calls.append((text, dict(progress), media))
        ids = list(progress.get("remote_ids") or [])
        assert ids == ["root-123"]
        updated = dict(progress)
        updated["published_parts"] = updated.get("total_parts", 1)
        updated["remote_ids"] = ["root-123", "reply-2"] if updated["published_parts"] > 1 else ["root-123"]
        context.save_progress(updated)
        return PublishResult(remote_id="root-123", progress=updated)


def _context(saved):
    return PublishContext(before_write=lambda: None, save_progress=lambda value: saved.append(dict(value)))


def test_rc12_reconciles_multi_part_root_and_resumes(monkeypatch):
    inner = FakeInner()
    pub = Rc8ThreadsPublisher(inner, donation_text="", enabled=False)
    monkeypatch.setattr(factory_module, "_threads_recent_match", lambda *_: ("root-123", "https://threads.net/t/root"))
    saved = []
    long_text = ("Перше речення про подію. " * 30).strip()
    exc = PublishError("The requested resource does not exist", retryable=False)
    exc.code = 24
    exc.subcode = 4279009

    result = pub._reconcile_root_and_resume(long_text, {}, _context(saved), exc, None)

    assert result is not None
    assert result.remote_id == "root-123"
    assert result.progress["threads_reconciled"] is True
    assert result.progress["published_parts"] == result.progress["total_parts"]
    assert inner.calls
    assert inner.calls[0][1]["published_parts"] == 1
    assert inner.calls[0][1]["remote_ids"] == ["root-123"]


def test_rc12_reconciliation_is_bounded_to_unique_exact_match(monkeypatch):
    class Response:
        status = 200
        body = b"x"
        def json(self):
            return {"data": [
                {"id": "1", "text": "Same text", "permalink": "p1"},
                {"id": "2", "text": "  same   text  ", "permalink": "p2"},
            ]}
    monkeypatch.setattr(factory_module, "fetch_url", lambda *a, **k: Response())
    assert factory_module._threads_recent_match("u", "t", "same text") is None
