from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Mapping, Sequence

from .database import Database
from .i18n import normalize_language, output_language_instruction
from .ollama_client import OllamaClient, OllamaError
from .scheduling import KYIV
from .publication_text import (
    EDITORIAL_TEXT_LIMIT,
    TELEGRAM_MEDIA_CAPTION_LIMIT,
    FUND_FOOTER,
    THREADS_FUND_FOOTER,
    compose_publication_text,
    source_suffix,
)

UTC = timezone.utc
QUEUE_900_MIGRATION_KEY = "queue_editorial_text_900_v1"


class QueueMigrationError(RuntimeError):
    pass


@dataclass(slots=True)
class QueueMigrationCandidate:
    batch_id: int
    group_id: int
    title: str
    scheduled_at: str
    batch_status: str
    old_text: str
    limit: int
    include_source_link: bool
    source_url: str
    has_media: bool
    targets: dict[int, tuple[str, str, str]] = field(default_factory=dict)

    @property
    def platforms(self) -> list[str]:
        return [row[0] for row in self.targets.values()]


@dataclass(slots=True)
class QueueMigrationScan:
    candidates: list[QueueMigrationCandidate]
    blockers: list[str]


def _utc_iso(value: datetime | None = None) -> str:
    return (value or datetime.now(UTC)).astimezone(UTC).isoformat(timespec="seconds")


def _strip_known_suffixes(payload: str, platform: str, *, include_source_link: bool, source_url: str) -> str:
    value = str(payload or "").strip()
    pieces: list[str] = []
    if include_source_link and source_url.strip():
        pieces.append(source_suffix(source_url))
    pieces.append(THREADS_FUND_FOOTER if platform == "threads" else FUND_FOOTER)
    for suffix in pieces:
        if value == suffix:
            return ""
        marker = "\n\n" + suffix
        if value.endswith(marker):
            value = value[: -len(marker)].rstrip()
    return value


def effective_editorial_limit(
    platforms: Iterable[str],
    *,
    include_source_link: bool,
    source_url: str,
    has_media: bool,
) -> int:
    """Return the safe canonical-text budget for all selected targets.

    The editorial limit is 900. Telegram media captions are the only narrower
    physical envelope once the UA FREE footer and optional source link are added.
    """

    limit = EDITORIAL_TEXT_LIMIT
    if has_media and any(str(platform) == "telegram" for platform in platforms):
        probe = compose_publication_text(
            "X",
            "telegram",
            include_source_link=include_source_link,
            source_url=source_url,
        )
        overhead = max(0, len(probe) - 1)
        limit = min(limit, TELEGRAM_MEDIA_CAPTION_LIMIT - overhead)
    return max(120, limit)


def scan_queue_for_900_migration(
    database: Database,
    *,
    now: datetime | None = None,
) -> QueueMigrationScan:
    instant = _utc_iso(now)
    blockers: list[str] = []
    candidates: list[QueueMigrationCandidate] = []
    with database.connect() as db:
        active_rows = db.execute(
            """
            SELECT b.id,b.status,b.scheduled_at FROM publication_batches b
            WHERE b.status IN ('pending','in_progress','paused')
            ORDER BY julianday(b.scheduled_at),b.id
            """
        ).fetchall()
        current_kyiv_date = (now or datetime.now(UTC)).astimezone(KYIV).date()
        for row in active_rows:
            status = str(row["status"])
            batch_id = int(row["id"])
            scheduled = str(row["scheduled_at"])
            try:
                scheduled_kyiv_date = datetime.fromisoformat(scheduled).astimezone(KYIV).date()
            except ValueError:
                scheduled_kyiv_date = None
            if status == "in_progress":
                blockers.append(f"Пакет #{batch_id} ще публікується.")
            elif scheduled_kyiv_date == current_kyiv_date:
                blockers.append(
                    f"Пакет #{batch_id} запланований ще на сьогодні. "
                    "Дочекайтеся його завершення у робочій FIX26."
                )
            elif status == "pending":
                due = db.execute(
                    "SELECT julianday(?)<=julianday(?)",
                    (scheduled, instant),
                ).fetchone()[0]
                if int(due or 0):
                    blockers.append(f"Пакет #{batch_id} уже прострочений або має запускатися зараз.")

        rows = db.execute(
            """
            SELECT b.id AS batch_id,b.status AS batch_status,b.scheduled_at,
                   a.group_id,g.canonical_title,g.rewrite_text,g.include_source_link,
                   g.media_file_id,a.url AS source_url,
                   t.id AS target_id,t.platform,t.status AS target_status,t.payload_text
            FROM publication_batches b
            JOIN articles a ON a.id=b.article_id
            JOIN news_groups g ON g.id=a.group_id
            JOIN publication_targets t ON t.batch_id=b.id
            WHERE b.status IN ('pending','paused')
              AND julianday(b.scheduled_at)>julianday(?)
            ORDER BY b.id,t.id
            """,
            (instant,),
        ).fetchall()

    grouped: dict[int, dict[str, object]] = {}
    for row in rows:
        batch_id = int(row["batch_id"])
        bucket = grouped.setdefault(
            batch_id,
            {
                "batch_id": batch_id,
                "batch_status": str(row["batch_status"]),
                "scheduled_at": str(row["scheduled_at"]),
                "group_id": int(row["group_id"]),
                "title": str(row["canonical_title"] or "Без заголовка"),
                "rewrite_text": str(row["rewrite_text"] or "").strip(),
                "include_source_link": bool(row["include_source_link"]),
                "source_url": str(row["source_url"] or ""),
                "has_media": bool(str(row["media_file_id"] or "").strip()),
                "targets": {},
            },
        )
        targets = bucket["targets"]
        assert isinstance(targets, dict)
        targets[int(row["target_id"])] = (
            str(row["platform"]),
            str(row["target_status"]),
            str(row["payload_text"] or ""),
        )

    for bucket in grouped.values():
        targets = bucket["targets"]
        assert isinstance(targets, dict)
        platforms = [row[0] for row in targets.values()]
        old_text = str(bucket["rewrite_text"] or "").strip()
        if not old_text:
            # Legacy queue packages can occasionally have only target payloads.
            preferred = next(
                ((platform, payload) for platform, _status, payload in targets.values() if platform == "telegram"),
                next(((platform, payload) for platform, _status, payload in targets.values()), ("telegram", "")),
            )
            old_text = _strip_known_suffixes(
                preferred[1],
                preferred[0],
                include_source_link=bool(bucket["include_source_link"]),
                source_url=str(bucket["source_url"]),
            )
        limit = effective_editorial_limit(
            platforms,
            include_source_link=bool(bucket["include_source_link"]),
            source_url=str(bucket["source_url"]),
            has_media=bool(bucket["has_media"]),
        )
        if len(old_text) <= limit:
            continue
        candidates.append(
            QueueMigrationCandidate(
                batch_id=int(bucket["batch_id"]),
                group_id=int(bucket["group_id"]),
                title=str(bucket["title"]),
                scheduled_at=str(bucket["scheduled_at"]),
                batch_status=str(bucket["batch_status"]),
                old_text=old_text,
                limit=limit,
                include_source_link=bool(bucket["include_source_link"]),
                source_url=str(bucket["source_url"]),
                has_media=bool(bucket["has_media"]),
                targets=targets,
            )
        )
    return QueueMigrationScan(candidates=candidates, blockers=blockers)


def build_queue_compression_prompt(text: str, limit: int, *, language: str = "uk") -> str:
    language = normalize_language(language)
    if language == "en":
        return f"""
{output_language_instruction(language)}
You are shortening an editor-approved news text. Return only the completed text,
without headings, explanations, JSON, or markdown.

STRICT REQUIREMENTS:
- no more than {int(limit)} characters including spaces and line breaks;
- preserve as many verified facts as possible;
- preserve names, positions, dates, numbers, geography, institutions, causes,
  consequences, and the meaning of quotations;
- add no new facts and do not change meaning or tone;
- remove repetition, filler introductions, generic phrases, and decoration;
- do not add a fundraising footer or source link; the application adds them.

APPROVED TEXT:
{text.strip()}
""".strip()
    return f"""
Ти стискаєш ВЖЕ СХВАЛЕНИЙ редактором український новинний текст.
Поверни лише готовий текст, без заголовків, пояснень, JSON і markdown.

ЖОРСТКІ УМОВИ:
- не більше {int(limit)} символів разом із пробілами та переносами;
- збережи максимум перевірених фактів;
- обов'язково збережи імена, посади, дати, числа, географію, назви установ,
  причини, наслідки та зміст цитат;
- не додавай жодного нового факту;
- не змінюй сенс і тональність;
- прибери повтори, вступну воду, загальні фрази й стилістичні прикраси;
- текст повністю українською;
- не додавай футер фонду або посилання на джерело: програма додасть їх сама.

СХВАЛЕНИЙ ТЕКСТ:
{text.strip()}
""".strip()


def _clean_generated_text(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()[1:-1]
        text = "\n".join(lines).strip()
    text = re.sub(r"(?is)^\s*(?:готовий текст|текст|рерайт)\s*:\s*", "", text).strip()
    return text.strip('"“”')


def compress_approved_text(
    text: str,
    limit: int,
    *,
    primary_client: OllamaClient,
    primary_model: str,
    fallback_client: OllamaClient | None = None,
    fallback_model: str = "",
    language: str = "uk",
) -> tuple[str, str, bool]:
    if not str(primary_model or "").strip():
        raise QueueMigrationError(
            "No primary Ollama model is selected in Settings."
            if normalize_language(language) == "en"
            else "У налаштуваннях не вибрана основна модель Ollama."
        )
    language = normalize_language(language)
    prompt = build_queue_compression_prompt(text, limit, language=language)
    attempts: list[tuple[OllamaClient, str, bool]] = [(primary_client, primary_model, False)]
    if fallback_client is not None and fallback_model.strip() and fallback_model.strip() != primary_model.strip():
        attempts.append((fallback_client, fallback_model.strip(), True))
    errors: list[str] = []
    for client, model, is_fallback in attempts:
        try:
            result = _clean_generated_text(client.generate_text(model, prompt, num_predict=512, temperature=0.05))
        except OllamaError as exc:
            errors.append(f"{model}: {exc}")
            continue
        if not result:
            errors.append(f"{model}: модель повернула порожній текст")
            continue
        if len(result) > int(limit):
            errors.append(f"{model}: {len(result)} символів при ліміті {limit}")
            continue
        return result, model, is_fallback
    raise QueueMigrationError("; ".join(errors) or "Ollama не створила придатний скорочений текст.")


def critical_fact_warnings(old_text: str, new_text: str, *, language: str = "uk") -> list[str]:
    """Flag conspicuous losses for human review without pretending to understand facts."""

    warnings: list[str] = []
    old_numbers = set(re.findall(r"(?<!\w)\d[\d\s.,:/%-]*", old_text))
    new_numbers = set(re.findall(r"(?<!\w)\d[\d\s.,:/%-]*", new_text))
    missing_numbers = sorted(item.strip() for item in old_numbers - new_numbers if item.strip())
    if missing_numbers:
        warnings.append(
            ("numbers may be missing: " if normalize_language(language) == "en" else "можливо втрачено числа: ")
            + ", ".join(missing_numbers[:8])
        )
    old_acronyms = set(re.findall(r"\b[А-ЯІЇЄҐA-Z]{2,}\b", old_text))
    new_acronyms = set(re.findall(r"\b[А-ЯІЇЄҐA-Z]{2,}\b", new_text))
    missing_acronyms = sorted(old_acronyms - new_acronyms)
    if missing_acronyms:
        warnings.append(
            ("names/acronyms may be missing: " if normalize_language(language) == "en" else "можливо втрачено назви/абревіатури: ")
            + ", ".join(missing_acronyms[:8])
        )
    return warnings


def build_target_payloads(candidate: QueueMigrationCandidate, new_text: str) -> dict[int, str]:
    value = str(new_text or "").strip()
    if not value or len(value) > candidate.limit:
        raise QueueMigrationError(
            f"Пакет #{candidate.batch_id}: текст має {len(value)} символів при ліміті {candidate.limit}."
        )
    payloads: dict[int, str] = {}
    for target_id, (platform, status, _old_payload) in candidate.targets.items():
        if status == "sent":
            continue
        payload = compose_publication_text(
            value,
            platform,
            include_source_link=candidate.include_source_link,
            source_url=candidate.source_url,
        )
        if platform == "telegram" and candidate.has_media and len(payload) > TELEGRAM_MEDIA_CAPTION_LIMIT:
            raise QueueMigrationError(
                f"Пакет #{candidate.batch_id}: готовий підпис Telegram має {len(payload)} символів."
            )
        payloads[target_id] = payload
    return payloads
