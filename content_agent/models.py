from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class Source:
    id: int | None
    kind: str
    name: str
    url: str
    enabled: bool = True
    last_checked_at: str | None = None


@dataclass(slots=True)
class CollectedArticle:
    external_id: str
    title: str
    url: str
    raw_text: str
    published_at: str | None = None


@dataclass(slots=True)
class Article:
    id: int
    source_id: int
    title: str
    url: str
    raw_text: str
    status: str
    rewrite_text: str = ""
    fact_card: str = ""
    headline: str = ""
    discovered_at: str = ""
    published_at: str | None = None
    group_id: int | None = None
    source_name: str = ""


@dataclass(slots=True)
class NewsGroup:
    id: int
    canonical_title: str
    status: str
    created_at: str
    updated_at: str
    source_count: int = 0
    first_published_at: str | None = None
    last_published_at: str | None = None
    headline: str = ""
    fact_card: str = ""
    rewrite_text: str = ""
    ai_draft_text: str = ""
    platform_texts: dict[str, str] = field(default_factory=dict)
    include_source_link: bool = False
    media_drive_url: str = ""
    media_file_id: str = ""
    media_name: str = ""
    media_kind: str = ""
    media_mime: str = ""
    media_size: int = 0
    explosiveness_score: int = 0
    explosiveness_confidence: int = 0
    explosiveness_details: dict[str, Any] = field(default_factory=dict)
    recommended_platforms: list[str] = field(default_factory=list)
    articles: list[Article] = field(default_factory=list)

    @property
    def primary_url(self) -> str:
        return next((item.url for item in self.articles if item.url), "")

    @property
    def combined_text(self) -> str:
        blocks: list[str] = []
        for index, article in enumerate(self.articles, start=1):
            label = article.source_name or f"Джерело {index}"
            blocks.append(
                f"ДЖЕРЕЛО {index}: {label}\n"
                f"ЗАГОЛОВОК: {article.title}\n"
                f"ЧАС: {article.published_at or 'не визначено'}\n"
                f"URL: {article.url}\n"
                f"ТЕКСТ:\n{article.raw_text}"
            )
        return "\n\n---\n\n".join(blocks)


@dataclass(slots=True)
class RewriteResult:
    headline: str
    fact_card: str
    rewrite: str
    platform_texts: dict[str, str] = field(default_factory=dict)
    source_count_used: int = 1
    source_count_total: int = 1
    auto_compacted: bool = False


@dataclass(slots=True)
class MediaPayload:
    file_id: str
    name: str
    kind: str
    mime_type: str
    data: bytes
    public_url: str


@dataclass(slots=True)
class PublicationTarget:
    id: int
    batch_id: int
    platform: str
    status: str
    remote_id: str | None = None
    last_error: str | None = None
    progress: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PublicationBatch:
    id: int
    article_id: int
    scheduled_at: str
    status: str
    lease_owner: str | None
    lease_until: str | None
    attempts: int
    targets: list[PublicationTarget] = field(default_factory=list)
    cleanup_error: str | None = None


@dataclass(slots=True)
class QueueUpdateResult:
    batch_id: int
    scheduled_at: str
    status: str
    created: bool = False
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    already_sent: list[str] = field(default_factory=list)


def utc_iso(dt: datetime) -> str:
    return dt.astimezone().isoformat(timespec="seconds")
