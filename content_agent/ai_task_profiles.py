from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AITaskProfile:
    name: str
    cloud_evidence_chars: int
    local_evidence_chars: int
    cloud_output_tokens: int
    local_output_tokens: int
    cloud_timeout_seconds: int
    local_timeout_seconds: int
    task_timeout_seconds: int
    second_pass_threshold: int


REWRITE_PROFILE = AITaskProfile(
    name="rewrite",
    cloud_evidence_chars=7600,
    local_evidence_chars=4300,
    cloud_output_tokens=1200,
    local_output_tokens=320,
    cloud_timeout_seconds=90,
    local_timeout_seconds=120,
    task_timeout_seconds=150,
    second_pass_threshold=84,
)

TOPIC_PROFILE = AITaskProfile(
    name="topic",
    cloud_evidence_chars=5200,
    local_evidence_chars=4200,
    cloud_output_tokens=900,
    local_output_tokens=260,
    cloud_timeout_seconds=70,
    local_timeout_seconds=90,
    task_timeout_seconds=120,
    second_pass_threshold=0,
)
