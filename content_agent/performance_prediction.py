from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from statistics import mean

from .models import NewsGroup
from .news_logic import event_similarity
from .scheduling import KYIV, parse_iso


@dataclass(slots=True)
class PerformancePrediction:
    available: bool
    score: int = 0
    confidence: int = 0
    sample_size: int = 0
    comparable_count: int = 0
    metric_target_count: int = 0
    platform_scores: dict[str, int] = field(default_factory=dict)
    top_matches: list[dict[str, object]] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class _TargetSample:
    row_id: int
    group_id: int
    platform: str
    value: float


@dataclass(slots=True)
class _RowSample:
    row_id: int
    group_id: int
    title: str
    text: str
    published_at: str
    platform_percentiles: dict[str, float]

    @property
    def score(self) -> float:
        return mean(self.platform_percentiles.values()) if self.platform_percentiles else 0.5


def _platform_family(platform: str) -> str:
    value = str(platform or "").strip().lower()
    return "facebook" if value.startswith("facebook:") else value


def _metric_number(metrics: dict[str, object], *names: str) -> int:
    for name in names:
        value = metrics.get(name)
        if isinstance(value, (int, float)):
            return max(0, int(value))
    return 0


def _observation_scale(published_at: str, checked_at: str) -> float:
    published = parse_iso(published_at)
    checked = parse_iso(checked_at)
    if published is None or checked is None:
        return 1.0
    hours = max(12.0, min(168.0, (checked.astimezone(KYIV) - published.astimezone(KYIV)).total_seconds() / 3600.0))
    return 24.0 / hours


def _performance_value(row: dict[str, object], target: dict[str, object]) -> float | None:
    progress = target.get("progress")
    if not isinstance(progress, dict):
        return None
    metrics = progress.get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        return None

    recognized = {
        "views", "likes", "reactions", "shares", "reposts", "quotes", "comments", "replies"
    }
    if not any(name in metrics for name in recognized):
        return None

    views = _metric_number(metrics, "views")
    likes = _metric_number(metrics, "likes", "reactions")
    shares = _metric_number(metrics, "shares", "reposts", "quotes")
    comments = _metric_number(metrics, "comments", "replies")
    scale = _observation_scale(
        str(row.get("published_at") or row.get("scheduled_at") or ""),
        str(progress.get("metrics_checked_at") or ""),
    )
    views_rate = views * scale
    interaction_rate = (likes + 2.0 * comments + 3.0 * shares) * scale

    # Log scaling stops one viral outlier from flattening the whole local history.
    if "views" in metrics:
        return math.log1p(views_rate) + 2.6 * math.log1p(interaction_rate)
    return 3.2 * math.log1p(interaction_rate)


def _percentile(value: float, values: list[float]) -> float:
    if not values:
        return 0.5
    if len(values) == 1:
        return 0.5
    lower = sum(item < value for item in values)
    equal = sum(item == value for item in values)
    return (lower + 0.5 * equal) / len(values)


def _recency_weight(published_at: str, now: datetime) -> float:
    parsed = parse_iso(published_at)
    if parsed is None:
        return 0.7
    age_days = max(0.0, (now - parsed.astimezone(KYIV)).total_seconds() / 86400.0)
    return 1.0 / (1.0 + age_days / 120.0)


def _label(score: int) -> str:
    if score >= 75:
        return "високий потенціал"
    if score >= 58:
        return "вище середнього"
    if score >= 42:
        return "середній потенціал"
    if score >= 25:
        return "нижче середнього"
    return "низький потенціал"


def predict_historical_performance(
    group: NewsGroup,
    history_rows: list[dict[str, object]],
    *,
    now: datetime | None = None,
    minimum_rows: int = 5,
) -> PerformancePrediction:
    """Estimate relative future performance from this installation's own history.

    The score is a percentile-like 0..100 value relative to the user's previous
    publications. Missing platform metrics are ignored rather than treated as zero.
    """

    current_title = (group.headline or group.canonical_title or "").strip()
    current_text = (group.rewrite_text or group.combined_text or "").strip()
    current_group_id = int(group.id)

    raw_targets: list[_TargetSample] = []
    row_payloads: dict[int, dict[str, object]] = {}
    for row in history_rows:
        try:
            row_id = int(row.get("batch_id") or 0)
            group_id = int(row.get("group_id") or 0)
        except (TypeError, ValueError):
            continue
        if row_id <= 0 or group_id == current_group_id:
            continue
        row_payloads[row_id] = row
        targets = row.get("targets")
        for target in targets if isinstance(targets, list) else []:
            if not isinstance(target, dict) or str(target.get("status")) != "sent":
                continue
            value = _performance_value(row, target)
            if value is None:
                continue
            raw_targets.append(
                _TargetSample(
                    row_id=row_id,
                    group_id=group_id,
                    platform=_platform_family(str(target.get("platform") or "")),
                    value=value,
                )
            )

    values_by_platform: dict[str, list[float]] = {}
    for sample in raw_targets:
        values_by_platform.setdefault(sample.platform, []).append(sample.value)

    row_platforms: dict[int, dict[str, list[float]]] = {}
    for sample in raw_targets:
        row_platforms.setdefault(sample.row_id, {}).setdefault(sample.platform, []).append(
            _percentile(sample.value, values_by_platform[sample.platform])
        )

    rows: list[_RowSample] = []
    for row_id, platforms in row_platforms.items():
        payload = row_payloads[row_id]
        rows.append(
            _RowSample(
                row_id=row_id,
                group_id=int(payload.get("group_id") or 0),
                title=str(payload.get("headline") or "").strip(),
                text=str(payload.get("rewrite_text") or "").strip(),
                published_at=str(payload.get("published_at") or payload.get("scheduled_at") or ""),
                platform_percentiles={key: mean(values) for key, values in platforms.items()},
            )
        )

    if len(rows) < max(1, int(minimum_rows)):
        return PerformancePrediction(
            available=False,
            sample_size=len(rows),
            metric_target_count=len(raw_targets),
            note=(
                f"Недостатньо історичних публікацій зі статистикою: {len(rows)}. "
                f"Потрібно щонайменше {max(1, int(minimum_rows))}."
            ),
        )

    now_value = (now or datetime.now(KYIV)).astimezone(KYIV)
    ranked: list[tuple[_RowSample, float, float]] = []
    for row in rows:
        similarity = event_similarity(current_title, current_text, row.title, row.text)
        # A small baseline lets the whole history establish "normal" performance;
        # topical matches receive much more influence.
        weight = (0.08 + similarity ** 1.7) * _recency_weight(row.published_at, now_value)
        ranked.append((row, similarity, weight))
    ranked.sort(key=lambda item: item[1], reverse=True)

    weighted_total = sum(row.score * weight for row, _similarity, weight in ranked)
    total_weight = sum(weight for _row, _similarity, weight in ranked)
    score = int(round(100.0 * (weighted_total / total_weight if total_weight else 0.5)))
    score = max(0, min(100, score))

    comparable = [item for item in ranked if item[1] >= 0.10]
    top = ranked[: min(5, len(ranked))]
    average_top_similarity = mean(item[1] for item in top) if top else 0.0
    platform_count = len(values_by_platform)
    confidence = int(
        round(
            min(
                92.0,
                12.0
                + min(34.0, len(rows) * 2.0)
                + min(24.0, len(comparable) * 4.0)
                + min(16.0, average_top_similarity * 55.0)
                + min(6.0, platform_count * 2.0),
            )
        )
    )

    platform_scores: dict[str, int] = {}
    for platform in sorted(values_by_platform):
        numerator = 0.0
        denominator = 0.0
        for row, _similarity, weight in ranked:
            percentile = row.platform_percentiles.get(platform)
            if percentile is None:
                continue
            numerator += percentile * weight
            denominator += weight
        if denominator:
            platform_scores[platform] = max(0, min(100, int(round(100.0 * numerator / denominator))))

    top_matches = [
        {
            "batch_id": row.row_id,
            "headline": row.title,
            "similarity": int(round(similarity * 100)),
            "performance": int(round(row.score * 100)),
        }
        for row, similarity, _weight in top
    ]

    return PerformancePrediction(
        available=True,
        score=score,
        confidence=confidence,
        sample_size=len(rows),
        comparable_count=len(comparable),
        metric_target_count=len(raw_targets),
        platform_scores=platform_scores,
        top_matches=top_matches,
        note=f"{_label(score)} відносно власної історії публікацій",
    )
