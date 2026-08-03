from __future__ import annotations

import tempfile
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_agent.database import Database
from content_agent.models import CollectedArticle
from content_agent.publishers import PublishContext, PublishResult, Publisher, PublisherFactory
from content_agent.worker import PublicationWorker


class SmokePublisher(Publisher):
    def publish(self, text: str, progress: dict[str, object], context: PublishContext) -> PublishResult:
        context.before_write()
        if not text:
            raise RuntimeError("Empty payload")
        return PublishResult("smoke-remote-id", progress)


class SmokeFactory(PublisherFactory):
    def __init__(self) -> None:
        from content_agent.config import AppConfig

        super().__init__(AppConfig())

    def create(self, platform: str) -> Publisher:
        return SmokePublisher()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="uafree-smoke-") as temp:
        db = Database(Path(temp) / "smoke.sqlite3")
        source = db.add_source("rss", "Fixture", "https://example.com/feed")
        db.insert_collected(source, [CollectedArticle("1", "Title", "https://example.com/a", "Raw text", None)], enforce_today=False)
        article = db.list_articles()[0]
        db.save_rewrite(
            article.id,
            headline="Headline",
            fact_card="Facts",
            rewrite_text="Rewrite",
            platform_texts={"telegram": "TG", "facebook": "FB", "threads": "TH", "linkedin": "LI"},
        )
        batch = db.create_batch(
            article.id,
            (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
            {"telegram": "TG", "facebook:1": "FB", "facebook:2": "FB", "threads": "TH", "linkedin": "LI"},
        )
        result = PublicationWorker(db, SmokeFactory()).run_once()
        current = db.get_batch(batch)
        assert result.completed and current.status == "completed"
        assert all(target.status == "sent" for target in current.targets)
    print("PASS local end-to-end smoke")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
