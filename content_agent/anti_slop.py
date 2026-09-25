from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

_SEVERITY_RANK = {"note": 0, "minor": 1, "major": 2, "blocker": 3}
_INVISIBLE_RE = re.compile(r"[\u200B\u200C\u200D\u2060\uFEFF\u202A-\u202E\u2066-\u2069]")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")
_WORD_RE = re.compile(r"[A-Za-zА-Яа-яІіЇїЄєҐґ0-9’'-]+")


@dataclass(frozen=True, slots=True)
class SlopFinding:
    rule: str
    name: str
    severity: str
    count: int
    detail: str
    deduction: int


@dataclass(frozen=True, slots=True)
class SlopAssessment:
    score: int
    gate: int
    publishable: bool
    findings: tuple[SlopFinding, ...]
    sanitized_text: str

    @property
    def issues(self) -> tuple[str, ...]:
        return tuple(f"{item.name}: {item.detail}" for item in self.findings)


def sanitize_text(value: str) -> str:
    text = str(value or "")
    text = _INVISIBLE_RE.sub("", text)
    text = text.replace("\u00a0", " ").replace("\u202f", " ")
    text = "\n".join(re.sub(r"[ \t]{2,}", " ", line).rstrip() for line in text.splitlines())
    return text.strip()


def _load_rules(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _count_phrase(text: str, item: str) -> int:
    return len(re.findall(r"(?<![\w-])" + re.escape(item) + r"(?![\w-])", text, flags=re.I))


def _finding(rule: dict, count: int, detail: str) -> SlopFinding:
    points = int(rule.get("points", 0))
    # Repetition matters, but one tic must not erase the whole article.
    deduction = min(points * 2, points + max(0, count - 1) * max(1, points // 2))
    return SlopFinding(str(rule["id"]), str(rule["name"]), str(rule["severity"]), count, detail, deduction)


def assess_text(value: str, *, rules_path: str | Path, profile: str = "standard") -> SlopAssessment:
    raw = str(value or "")
    text = sanitize_text(raw)
    spec = _load_rules(Path(rules_path))
    gate = int((spec.get("profiles", {}).get(profile) or spec.get("profiles", {}).get("standard") or {"gate": 88})["gate"])
    findings: list[SlopFinding] = []

    for rule in spec.get("rules", []):
        kind = str(rule.get("kind") or "")
        count = 0
        examples: list[str] = []
        if kind in {"phrases", "density_phrases"}:
            for item in rule.get("items", []):
                n = _count_phrase(text, str(item))
                if n:
                    count += n
                    examples.append(str(item))
        elif kind in {"regex", "density_regex"}:
            for pattern in rule.get("patterns", []):
                matches = list(re.finditer(str(pattern), raw if rule.get("id") == "U1" else text, flags=re.I | re.M))
                if matches:
                    count += len(matches)
                    examples.extend(" ".join(m.group(0).split())[:80] for m in matches[:2])
        minimum = int(rule.get("min_count", 1))
        if count >= minimum:
            detail = f"{count}×" + (f" ({'; '.join(examples[:3])})" if examples else "")
            findings.append(_finding(rule, count, detail))

    sentences = [part.strip() for part in _SENTENCE_SPLIT.split(" ".join(text.split())) if part.strip()]
    lengths = [len(_WORD_RE.findall(sentence)) for sentence in sentences]

    if len(lengths) >= 4:
        for i in range(3, len(lengths)):
            group = lengths[i - 3:i + 1]
            if min(group) >= 8 and max(group) - min(group) <= 2:
                findings.append(SlopFinding("R1", "Метрономний ритм", "minor", 1, f"4 речення по {group} слів", 4))
                break
        for i in range(3, len(lengths)):
            group = lengths[i - 3:i + 1]
            if max(group) <= 6:
                findings.append(SlopFinding("R2", "Серія коротких ударних фраз", "minor", 1, f"4 речення по {group} слів", 4))
                break

    starters: list[str] = []
    for sentence in sentences:
        words = [w.casefold() for w in _WORD_RE.findall(sentence)[:2]]
        if words:
            starters.append(" ".join(words))
    if starters:
        top = max((starters.count(x), x) for x in set(starters))
        if top[0] >= 3:
            findings.append(SlopFinding("R3", "Повторювані початки речень", "minor", top[0], top[1], 4))

    questions = sum(1 for sentence in sentences if sentence.rstrip().endswith("?"))
    if questions >= 2:
        findings.append(SlopFinding("R4", "Надлишок риторичних питань", "minor", questions, f"{questions} питань", 4))

    # Collapse duplicate rules, keeping the strongest observation.
    by_rule: dict[str, SlopFinding] = {}
    for item in findings:
        previous = by_rule.get(item.rule)
        if previous is None or item.deduction > previous.deduction:
            by_rule[item.rule] = item
    final_findings = tuple(sorted(by_rule.values(), key=lambda x: (-_SEVERITY_RANK.get(x.severity, 0), x.rule)))
    score = max(0, 100 - sum(item.deduction for item in final_findings))
    blocker = any(item.severity == "blocker" for item in final_findings)
    publishable = score >= gate and not blocker
    return SlopAssessment(score, gate, publishable, final_findings, text)


def compact_feedback(assessment: SlopAssessment, limit: int = 5) -> str:
    if not assessment.findings:
        return ""
    return "; ".join(item.name + (f" ({item.detail})" if item.detail else "") for item in assessment.findings[: max(1, int(limit))])

RULES_PATH = Path(__file__).resolve().parent / "anti_slop_rules_uk.json"


def assess_ukrainian_slop(value: str, *, profile: str = "standard") -> SlopAssessment:
    return assess_text(value, rules_path=RULES_PATH, profile=profile)
