from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from content_agent.database import Database
from content_agent.models import CollectedArticle, RewriteResult
from content_agent.publishers import PublishContext, PublishResult, Publisher, PublisherFactory
from content_agent.worker import PublicationWorker


class AlwaysPublisher(Publisher):
    def publish(self, text: str, progress: dict[str, object], context: PublishContext) -> PublishResult:
        context.before_write()
        return PublishResult(remote_id="ok", progress={})


class AlwaysFactory(PublisherFactory):
    def __init__(self):
        from content_agent.config import AppConfig

        super().__init__(AppConfig())

    def create(self, platform: str) -> Publisher:
        return AlwaysPublisher()


def test_local_end_to_end_without_external_network(tmp_path: Path) -> None:
    db = Database(tmp_path / "content.sqlite3")
    source_id = db.add_source("rss", "Local fixture", "https://example.com/feed")
    assert db.insert_collected(
        source_id,
        [CollectedArticle("external", "Original", "https://example.com/a", "Original full text", None)],
        enforce_today=False,
    ) == 1
    article = db.list_articles()[0]
    rewrite = RewriteResult(
        headline="Український заголовок",
        fact_card="Факти перевірено за наданим текстом.",
        rewrite="Повністю переписаний український матеріал.",
        platform_texts={"telegram": "TG", "facebook": "FB", "threads": "TH", "linkedin": "LI"},
    )
    db.save_rewrite(
        article.id,
        headline=rewrite.headline,
        fact_card=rewrite.fact_card,
        rewrite_text=rewrite.rewrite,
        platform_texts=rewrite.platform_texts,
    )
    batch_id = db.create_batch(
        article.id,
        (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
        {"telegram": "TG", "facebook:1": "FB", "facebook:2": "FB", "threads": "TH", "linkedin": "LI"},
    )
    result = PublicationWorker(db, AlwaysFactory()).run_once()
    assert result.completed is True
    batch = db.get_batch(batch_id)
    assert batch.status == "completed"
    assert all(target.status == "sent" for target in batch.targets)



def test_settings_ui_uses_single_linkedin_token_field() -> None:
    import inspect
    from content_agent.ui.main_window import MainWindow

    source = inspect.getsource(MainWindow._build_settings_tab)
    assert 'settings_vars["linkedin_token"]' in source
    assert 'settings_vars["linkedin_client_id"]' not in source
    assert 'Відкрити Token Generator' in source
    assert 'Перевірити токен' in source
