from __future__ import annotations

"""RC27 balanced Evidence Pack for large merged groups.

The historical pack already gives every source an equal character share for
normal groups (<=12 sources).  RC26's large-group condenser, however, ranked
unique sentences globally and could spend most of the prompt on one verbose
source.  This module keeps duplicate collapse but selects facts greedily by
*new source coverage* before filling the remaining budget by factual value.
"""

from . import evidence_pack as base
from .evidence_pack import EvidencePack
from .models import Article, NewsGroup


def _distinctive_tokens(value: str) -> frozenset[str]:
    """Tokens whose spelling change may mean a different model/entity/version."""
    result: set[str] = set()
    for token in base._WORD_TOKEN_RE.findall(str(value or "")):
        clean = token.strip("-_")
        if len(clean) < 3:
            continue
        if any(ch.isdigit() for ch in clean) or (clean.isascii() and clean.upper() == clean and any(ch.isalpha() for ch in clean)):
            result.add(clean.casefold())
    return frozenset(result)


def _mergeable(left: str, right: str) -> bool:
    left_distinctive = _distinctive_tokens(left)
    right_distinctive = _distinctive_tokens(right)
    if left_distinctive != right_distinctive:
        return False
    return base._near_duplicate(left, right)


def _build_large_group_pack_balanced(
    articles: list[Article],
    *,
    max_chars: int,
) -> EvidencePack:
    candidates: list[tuple[float, int, int, str]] = []
    total_sentences = 0
    for article_index, article in enumerate(articles):
        sentences = base._sentences(article.raw_text)
        total_sentences += len(sentences)
        if not sentences:
            title = base._clean_text(article.title)
            if title:
                candidates.append((base._score_sentence(0, title), article_index, 0, title))
            continue
        for sentence_index, sentence in enumerate(sentences[:12]):
            candidates.append(
                (base._score_sentence(sentence_index, sentence), article_index, sentence_index, sentence)
            )

    if not candidates:
        return EvidencePack("", len(articles), 0, total_sentences, False)

    # One representative per near-duplicate factual statement.  Unlike RC26,
    # retain every source that supports the statement.  A shared fact can cover
    # many sources without repeating the same sentence twelve times.
    representatives: list[dict[str, object]] = []
    for score, article_index, sentence_index, sentence in sorted(
        candidates, key=lambda row: (-row[0], row[1], row[2])
    ):
        exact_key = " ".join(base._WORD_TOKEN_RE.findall(sentence.casefold()))
        matched = None
        for item in representatives:
            if exact_key == item["key"] or _mergeable(sentence, str(item["text"])):
                matched = item
                break
        if matched is not None:
            sources = matched["sources"]
            assert isinstance(sources, set)
            sources.add(article_index)
            matched["support"] = len(sources)
            # Keep the strongest wording/score as the displayed representative.
            if float(score) > float(matched["score"]):
                matched["text"] = sentence
                matched["score"] = float(score)
                matched["article"] = article_index
                matched["sentence"] = sentence_index
            continue
        representatives.append(
            {
                "text": sentence,
                "key": exact_key,
                "score": float(score),
                "support": 1,
                "sources": {article_index},
                "article": article_index,
                "sentence": sentence_index,
            }
        )

    prefix = "УНІКАЛЬНІ ФАКТИ ЗІ ЗВЕДЕНОЇ ГРУПИ:\n"
    budget = max(900, int(max_chars))
    used = len(prefix)
    chosen: list[dict[str, object]] = []
    remaining = list(representatives)
    covered_sources: set[int] = set()

    def row_text(item: dict[str, object]) -> str:
        return "• " + " ".join(str(item["text"]).split())

    # Coverage phase.  Prefer statements that add evidence from the greatest
    # number of not-yet-represented sources.  Shared facts naturally win because
    # they are independently supported, while one verbose source cannot consume
    # the whole dossier just by having more high-scoring sentences.
    while remaining:
        fitting = [
            item
            for item in remaining
            if used + len(row_text(item)) + (1 if chosen else 0) <= budget
        ]
        if not fitting:
            break
        best = max(
            fitting,
            key=lambda item: (
                len(set(item["sources"]) - covered_sources),
                min(20, int(item["support"])),
                float(item["score"]),
                -int(item["article"]),
                -int(item["sentence"]),
            ),
        )
        new_sources = set(best["sources"]) - covered_sources
        # Once every source represented by any remaining fact is already covered,
        # switch to the value-fill phase below.
        if not new_sources:
            break
        chosen.append(best)
        covered_sources.update(set(best["sources"]))
        used += len(row_text(best)) + (1 if len(chosen) > 1 else 0)
        remaining.remove(best)

    # Value phase.  Spend spare space on the strongest non-duplicate details.
    ranked_remaining = sorted(
        remaining,
        key=lambda item: (
            -(float(item["score"]) + min(28.0, 4.0 * (int(item["support"]) - 1))),
            int(item["article"]),
            int(item["sentence"]),
        ),
    )
    for item in ranked_remaining:
        row = row_text(item)
        addition = len(row) + (1 if chosen else 0)
        if used + addition > budget:
            continue
        chosen.append(item)
        covered_sources.update(set(item["sources"]))
        used += addition

    if not chosen:
        best = max(
            representatives,
            key=lambda item: (int(item["support"]), float(item["score"])),
        )
        body = base._clip_at_word(str(best["text"]), max(80, budget - len(prefix) - 2))
        chosen = [best] if body else []
        text = prefix + ("• " + body if body else "")
    else:
        # Keep final dossier readable and deterministic.  Facts from different
        # sources remain interleaved by their original source order rather than
        # model-score order.
        chosen.sort(key=lambda item: (int(item["article"]), int(item["sentence"])))
        text = prefix + "\n".join(row_text(item) for item in chosen)

    text = text[:budget].rstrip()
    return EvidencePack(
        text=text,
        source_count=len(articles),
        selected_sentences=len(chosen),
        total_sentences=total_sentences,
        truncated=len(chosen) < len(representatives),
    )


def build_evidence_pack_rc27(
    group: NewsGroup,
    *,
    max_chars: int = 7600,
    include_urls: bool = False,
) -> EvidencePack:
    articles = list(group.articles)
    if len(articles) <= base._LARGE_GROUP_THRESHOLD:
        return base.build_evidence_pack(group, max_chars=max_chars, include_urls=include_urls)
    # Large-group mode intentionally omits URLs, exactly as the historical
    # condenser did.  URLs are transport metadata, not factual evidence.
    return _build_large_group_pack_balanced(articles, max_chars=max_chars)
