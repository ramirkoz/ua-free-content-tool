from __future__ import annotations

import re
from dataclasses import dataclass

from .contracts import AITask, QualityTier


@dataclass(frozen=True, slots=True)
class TaskRoute:
    task: AITask
    initial_tier: QualityTier
    max_tier: QualityTier
    max_attempts: int


_TIER_ORDER = (
    QualityTier.FAST_CHEAP,
    QualityTier.BALANCED,
    QualityTier.STRONG,
    QualityTier.PREMIUM,
)


def next_tier(value: QualityTier) -> QualityTier | None:
    try:
        index = _TIER_ORDER.index(value)
    except ValueError:
        return None
    return _TIER_ORDER[index + 1] if index + 1 < len(_TIER_ORDER) else None


def infer_task(prompt: str, *, max_output_tokens: int = 800) -> AITask:
    """Infer the internal job class. Users never choose a model or a task profile.

    Existing RC30 call sites intentionally keep their stable signatures. V2 maps
    those requests to task classes by the semantics already present in prompts.
    New V2 call sites may pass an explicit task later without changing backends.
    """
    text = str(prompt or "").casefold()
    if any(token in text for token in ("supervisor", "diagnostic", "інцидент", "діагност", "health snapshot")):
        return AITask.SUPERVISOR
    if any(token in text for token in ("дублікат", "duplicate", "одна й та сама подія", "same event")):
        return AITask.DUPLICATE
    if any(token in text for token in ("тема", "темою", "тематич", "topic", "схожих", "topic candidate", "topic match")):
        return AITask.TOPIC
    if any(token in text for token in ("fact guard", "fact-check", "перевір факти", "фактолог", "evidence")):
        return AITask.FACT
    if any(token in text for token in ("quality", "qa", "виправ", "repair", "редактор", "фінальн")):
        return AITask.QUALITY
    if any(token in text for token in ("рерайт", "rewrite", "перепиши", "готовий текст", "напиши", "автор")):
        return AITask.REWRITE
    if any(token in text for token in ("classif", "класиф", "визнач категор", "оцін", "score")):
        return AITask.CLASSIFY
    if int(max_output_tokens or 0) >= 700:
        return AITask.REWRITE
    return AITask.GENERIC


def complexity_score(prompt: str, *, max_output_tokens: int = 800) -> int:
    text = str(prompt or "")
    score = 0
    length = len(text)
    if length > 5000:
        score += 1
    if length > 11000:
        score += 1
    if len(re.findall(r"https?://", text, flags=re.I)) >= 3:
        score += 1
    if len(re.findall(r"(?<!\w)\d[\d\s.,:/%-]*", text)) >= 14:
        score += 1
    if any(token in text.casefold() for token in ("супереч", "conflict", "contradict", "кілька джерел", "multiple sources")):
        score += 1
    if int(max_output_tokens or 0) >= 1200:
        score += 1
    return min(score, 5)


def route_for(
    prompt: str,
    *,
    max_output_tokens: int = 800,
    strategy: str = "balanced",
    task: AITask | None = None,
) -> TaskRoute:
    # The caller may tag an internal task explicitly, but never a concrete model.
    # Complexity and quality tier are still selected by the program.
    resolved_task = task or infer_task(prompt, max_output_tokens=max_output_tokens)
    score = complexity_score(prompt, max_output_tokens=max_output_tokens)
    strategy = str(strategy or "balanced").casefold()

    if resolved_task in {AITask.TOPIC, AITask.DUPLICATE, AITask.CLASSIFY, AITask.SUPERVISOR}:
        start = QualityTier.FAST_CHEAP
        ceiling = QualityTier.STRONG
    elif resolved_task in {AITask.FACT, AITask.QUALITY}:
        start = QualityTier.STRONG
        ceiling = QualityTier.PREMIUM
    elif resolved_task == AITask.REWRITE:
        start = QualityTier.BALANCED if score < 3 else QualityTier.STRONG
        ceiling = QualityTier.PREMIUM
    else:
        start = QualityTier.BALANCED
        ceiling = QualityTier.STRONG

    if strategy == "economy":
        if start == QualityTier.STRONG and resolved_task not in {AITask.FACT, AITask.QUALITY}:
            start = QualityTier.BALANCED
        ceiling = QualityTier.STRONG
    elif strategy == "quality":
        if start == QualityTier.FAST_CHEAP:
            start = QualityTier.BALANCED
        elif start == QualityTier.BALANCED:
            start = QualityTier.STRONG
        ceiling = QualityTier.PREMIUM

    return TaskRoute(task=resolved_task, initial_tier=start, max_tier=ceiling, max_attempts=5)
