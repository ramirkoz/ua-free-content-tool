from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Sequence

from .ai_router import AIRouterError
from .editorial_memory import EditorialExample
from .evidence_pack import EvidencePack
from .evidence_pack_v1_4_rc27 import build_evidence_pack_rc27
from .models import NewsGroup
from . import rewrite_pipeline_v1_3 as base
from . import rewrite_pipeline_v1_4_rc17 as rc17
from . import rewrite_pipeline_v1_4_rc26 as rc26

logger = logging.getLogger("content_agent.rewrite.rc27")
_BASE_LOCAL_PROMPT = base._local_prompt

_PUBLIC_HEADLINE = {"заголовок", "headline"}
_PUBLIC_TEXT = {"текст", "text", "рерайт", "article"}
_SERVICE_LABELS = {
    "факти", "facts", "fact card", "fact_card",
    "аналіз", "analysis", "пояснення", "explanation",
    "reasoning", "notes", "note", "примітки", "примітка",
    "commentary", "коментар", "metadata", "meta",
    "службова примітка", "службовий коментар", "службове",
    "fact-card", "факт-картка", "editor note", "редакторська примітка",
    "sources", "source", "джерела", "джерело", "conclusion", "висновок",
}
_ALL_LABELS = sorted(_PUBLIC_HEADLINE | _PUBLIC_TEXT | _SERVICE_LABELS, key=len, reverse=True)
_LABEL_PATTERN = "|".join(re.escape(label) for label in _ALL_LABELS)
_MARKER_RE = re.compile(
    rf"(?im)^[ \t]*(?:#{{1,6}}[ \t]*)?(?:[-*>][ \t]*)?"
    rf"(?:\*{{1,2}}|_{{1,2}})?[ \t]*(?P<label>{_LABEL_PATTERN})[ \t]*"
    rf"(?:\*{{1,2}}|_{{1,2}})?[ \t]*:[ \t]*(?:\*{{1,2}}|_{{1,2}})?[ \t]*"
)
_WRAPPER_RE = re.compile(
    r"(?is)<(?:think|analysis|reasoning)>.*?</(?:think|analysis|reasoning)>"
)


def _normalise_label(value: str) -> str:
    return " ".join(str(value or "").casefold().replace("_", " ").split())


def _strip_wrappers(raw: str) -> str:
    text = str(raw or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    text = _WRAPPER_RE.sub("", text).strip()
    text = re.sub(r"^```(?:json|markdown|text)?[ \t]*\n?", "", text, flags=re.I)
    text = re.sub(r"\n?```[ \t]*$", "", text, flags=re.I).strip()
    # Some models emit an opening reasoning tag and forget to close it.  If a
    # real public marker exists later, everything before that marker is service
    # chatter and can be discarded deterministically.
    if re.match(r"(?is)^\s*<(?:think|analysis|reasoning)>", text):
        marker = _MARKER_RE.search(text)
        if marker:
            text = text[marker.start() :].strip()
    return text


def _trim_service_tail(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    marker = _MARKER_RE.search(text)
    if marker:
        text = text[: marker.start()].rstrip()
    # Trailing XML-ish model reasoning is also never public copy.
    text = re.split(r"(?is)\n[ \t]*<(?:think|analysis|reasoning)>", text, maxsplit=1)[0]
    return text.strip()


def _headline_from_text(value: str) -> str:
    compact = " ".join(str(value or "").split())
    if not compact:
        return ""
    first = re.split(r"(?<=[.!?…])\s+", compact, maxsplit=1)[0]
    return first[:180].rstrip(" .!?…")


def _clean_headline(value: str) -> str:
    text = _trim_service_tail(value)
    # A headline must be one line even when the model puts commentary below it.
    line = next((row.strip() for row in text.splitlines() if row.strip()), "")
    line = re.sub(r"^[\-*#>\s]+", "", line).strip()
    return line[:240].strip()


def _marker_payload(text: str) -> dict[str, object] | None:
    markers = list(_MARKER_RE.finditer(text))
    if not markers:
        return None

    candidates: list[tuple[int, str, str]] = []
    last_headline: tuple[int, str] | None = None
    for index, marker in enumerate(markers):
        label = _normalise_label(marker.group("label"))
        next_start = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        body = text[marker.end() : next_start].strip()
        if label in _PUBLIC_HEADLINE:
            headline = _clean_headline(body)
            if headline:
                last_headline = (marker.start(), headline)
            continue
        if label not in _PUBLIC_TEXT:
            continue
        rewrite = _trim_service_tail(body)
        if not rewrite:
            continue
        headline = last_headline[1] if last_headline else _headline_from_text(rewrite)
        headline = _clean_headline(headline)
        if headline:
            candidates.append((marker.start(), headline, rewrite))

    if not candidates:
        return None
    # Models sometimes draft, critique, then emit a corrected final pair.  Use
    # the last complete public pair, not the first draft.
    _, headline, rewrite = candidates[-1]
    return {"headline": headline, "fact_card": "", "rewrite": rewrite}


def _canonical_json_payload(text: str) -> dict[str, object] | None:
    try:
        parsed = json.loads(base._clean_json_text(text))
    except json.JSONDecodeError:
        parsed = None
    canonical = rc26._canonical_payload(parsed)
    if canonical is None:
        # Reuse RC26's truncated/balanced-object recovery, then sanitize the
        # recovered public fields before old structural QA sees them.
        try:
            canonical = rc26.decode_payload_rc26(text)
        except Exception:
            canonical = None
    if canonical is None:
        return None
    headline = _clean_headline(str(canonical.get("headline") or ""))
    rewrite = _trim_service_tail(str(canonical.get("rewrite") or ""))
    if not headline and rewrite:
        headline = _headline_from_text(rewrite)
    if not headline or not rewrite:
        return None
    return {
        "headline": headline,
        "fact_card": str(canonical.get("fact_card") or "").strip(),
        "rewrite": rewrite,
    }


def decode_payload_rc27(raw: str) -> dict[str, object]:
    """Recover public copy deterministically and discard model service chatter.

    RC26 made envelopes tolerant, but its marker parser consumed everything from
    TEXT: to end-of-response.  A perfectly usable rewrite followed by ANALYSIS:
    was therefore rejected by the historical fail-closed QA.  RC27 separates
    public and service sections before QA, so formatting mistakes do not trigger
    another paid AI call.
    """

    text = _strip_wrappers(raw)
    if not text:
        raise AIRouterError("AI повернув порожню відповідь.")

    marker_payload = _marker_payload(text)
    if marker_payload is not None:
        return marker_payload

    json_payload = _canonical_json_payload(text)
    if json_payload is not None:
        return json_payload

    plain = _trim_service_tail(text)
    plain = re.sub(
        r"(?is)^\s*(?:ось|here(?:'s| is)|готовий|final)\s+(?:готовий\s+)?(?:рерайт|rewrite|текст|text)\s*[:\-]\s*",
        "",
        plain,
        count=1,
    ).strip()
    if plain and not plain.startswith(("{", "[")):
        compact = " ".join(plain.split())
        if len(compact) >= 40:
            headline = _headline_from_text(plain)
            if headline:
                return {"headline": headline, "fact_card": "", "rewrite": plain}

    raise AIRouterError("AI не повернув придатного публічного тексту рерайту.")


def _multi_source_instruction(evidence: EvidencePack, *, language: str) -> str:
    if evidence.source_count <= 1:
        return ""
    if language == "en":
        return (
            "\n8. This is a MERGED MULTI-SOURCE event. Do not paraphrase one source. "
            "Build the public copy from the shared factual core and useful non-conflicting details "
            "present across the dossier. Deduplicate repeated facts; preserve attribution for claims "
            "that are source-specific or uncertain."
        )
    return (
        "\n9. Це ЗВЕДЕНА ПОДІЯ З КІЛЬКОХ ДЖЕРЕЛ. Не переписуй одне джерело. "
        "Побудуй текст зі спільного фактичного ядра та корисних несуперечливих деталей з інших джерел. "
        "Повтори одного факту прибирай; твердження, яке належить конкретному джерелу або має невизначеність, атрибутуй."
    )


def cloud_prompt_rc27(
    group: NewsGroup,
    evidence: EvidencePack,
    examples: Sequence[EditorialExample],
    graph_memory: str,
    *,
    language: str,
) -> str:
    prompt = rc26.cloud_prompt_rc26(group, evidence, examples, graph_memory, language=language)
    merge_rule = _multi_source_instruction(evidence, language=language)
    # Put the merge rule immediately before the output contract/evidence area so
    # it is not lost inside long style-memory text.
    if not merge_rule:
        return prompt
    marker = "\n\nCURRENT SOURCE EVIDENCE PACK:" if language == "en" else "\n\nПОТОЧНИЙ SOURCE EVIDENCE PACK:"
    return prompt.replace(marker, merge_rule + marker, 1)



def local_prompt_rc27(evidence: EvidencePack, *, language: str) -> str:
    prompt = _BASE_LOCAL_PROMPT(evidence, language=language)
    rule = _multi_source_instruction(evidence, language=language)
    if not rule:
        return prompt
    marker = "\n\nCURRENT EVIDENCE:" if language == "en" else "\n\nПОТОЧНІ ДОКАЗИ:"
    return prompt.replace(marker, rule + marker, 1)


def candidate_after_router_rc27(
    prompt: str,
    local_prompt: str,
    evidence: EvidencePack,
    *,
    language: str,
    skip_providers: set[str] | None = None,
    max_candidates: int = 4,
    deadline: float | None = None,
    cancel_event: object | None = None,
):
    """Stable candidate loop: deterministic format recovery, no format re-query.

    Structural envelope mistakes are now fixed locally by ``decode_payload_rc27``.
    If a response truly contains no usable public text, skip that model and move
    to a fresh route.  Do not spend a second provider call merely to move labels.
    One Fact Guard repair remains available for a structurally valid draft with
    an actual factual problem.
    """

    rc17.install_rc17_fact_guard()
    provider_skip = set(skip_providers or set())
    model_skip: set[str] = set()
    failures: list[str] = []
    fact_repair_used = False
    attempts = max(1, min(6, int(max_candidates) + 1))

    for _ in range(attempts):
        if cancel_event is not None and bool(getattr(cancel_event, "is_set", lambda: False)()):
            raise AIRouterError("AI-рерайт скасовано.")
        remaining = rc17._remaining(deadline)
        if remaining is not None and remaining < 4:
            break
        try:
            route = base._router_call(
                prompt,
                local_prompt,
                skip_providers=provider_skip,
                skip_models=model_skip,
                task_timeout_seconds=(
                    min(base.REWRITE_PROFILE.task_timeout_seconds, remaining)
                    if remaining is not None
                    else None
                ),
                cancel_event=cancel_event,
            )
        except AIRouterError as exc:
            detail = " | ".join(failures[-3:])
            if detail:
                raise AIRouterError(
                    "AI Router не зміг отримати безпечний готовий рерайт. "
                    + detail
                    + f" | Router: {exc}"
                ) from exc
            raise

        provider = str(route.provider or "").casefold()
        try:
            candidate = base._candidate(route, evidence, language=language)
        except Exception as exc:
            failures.append(f"{route.label}: {exc}")
            # No same-provider FORMAT REPAIR here.  The local deterministic parser
            # already handled recoverable envelopes; retrying labels wastes quota
            # and was the live RC26 failure mode.
            if provider == "local":
                provider_skip.add("local")
            elif route.model:
                model_skip.add(str(route.model).casefold())
            elif provider:
                provider_skip.add(provider)
            continue

        if candidate.guard.allowed:
            return candidate

        guard_reason = "; ".join(candidate.guard.issues[:4])
        failures.append(f"{route.label}: Fact Guard: {guard_reason}")
        remaining = rc17._remaining(deadline)
        if (
            not fact_repair_used
            and provider in rc17._FACT_REPAIR_PROVIDERS
            and (remaining is None or remaining >= 16)
        ):
            fact_repair_used = True
            repair_prompt = (
                "FACT-SAFE REPAIR. Re-read CURRENT SOURCE EVIDENCE in the original task. "
                "The previous public rewrite is structurally usable but Fact Guard found: "
                + guard_reason[:700]
                + ". Correct or remove ONLY unsupported factual elements. Keep supported facts and attribution. "
                "Do not add anything new. Return HEADLINE:/TEXT: fields only; no analysis, explanation or notes.\n\n"
                "ORIGINAL TASK:\n"
                + prompt[:7000]
                + "\n\nPREVIOUS RESPONSE:\n"
                + str(route.text)[:2600]
            )
            try:
                repaired = rc17._same_provider_repair(
                    route,
                    repair_prompt,
                    evidence,
                    language=language,
                    timeout=min(24, remaining) if remaining is not None else 24,
                    cancel_event=cancel_event,
                )
                if repaired.guard.allowed:
                    return repaired
                failures.append(
                    f"{repaired.route.label} repair Fact Guard: "
                    + "; ".join(repaired.guard.issues[:3])
                )
            except Exception as repair_exc:
                failures.append(f"{route.label} fact repair: {repair_exc}")

        if provider == "local":
            provider_skip.add("local")
        elif route.model:
            model_skip.add(str(route.model).casefold())
        elif provider:
            provider_skip.add(provider)

    if deadline is not None and time.monotonic() >= deadline:
        failures.append("спільний ліміт часу рерайту вичерпано")
    raise AIRouterError(
        "AI-провайдери відповіли, але безпечний рерайт не пройшов post-AI QA. "
        + " | ".join(failures[-3:])
    )


def install_runtime() -> None:
    rc17.install_rc17_fact_guard()
    base.build_evidence_pack = build_evidence_pack_rc27
    base._decode_payload = decode_payload_rc27
    base._cloud_prompt = cloud_prompt_rc27
    base._local_prompt = local_prompt_rc27
    base._candidate_after_router = candidate_after_router_rc27
