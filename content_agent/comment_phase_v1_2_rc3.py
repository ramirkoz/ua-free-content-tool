from __future__ import annotations

from dataclasses import dataclass

from .publishers import PublishContext, PublishError


@dataclass(frozen=True, slots=True)
class CommentPhaseKeys:
    prefix: str

    @property
    def main_started(self) -> str:
        return self.prefix + "_main_started"

    @property
    def main_completed(self) -> str:
        return self.prefix + "_main_completed"

    @property
    def main_id(self) -> str:
        return self.prefix + "_main_id"

    @property
    def comment_started(self) -> str:
        return self.prefix + "_comment_started"

    @property
    def comment_completed(self) -> str:
        return self.prefix + "_comment_completed"

    @property
    def comment_id(self) -> str:
        return self.prefix + "_comment_id"


def unknown_phase_error(platform: str, phase: str) -> PublishError:
    return PublishError(
        f"{platform}: результат етапу «{phase}» невідомий. Автоматичний повтор запису "
        "заблоковано, щоб не створити дубль. Перевірте платформу вручну.",
        retryable=False,
        outcome_unknown=True,
    )


def begin_phase(
    progress: dict[str, object],
    context: PublishContext,
    *,
    started_key: str,
    completed_key: str,
) -> dict[str, object]:
    if bool(progress.get(started_key)) and not bool(progress.get(completed_key)):
        raise PublishError(
            "Попередній мережевий запис почався без підтвердження завершення. "
            "Автоматичний повтор заблоковано.",
            retryable=False,
            outcome_unknown=True,
        )
    updated = {**progress, started_key: True, completed_key: False}
    context.save_progress(updated)
    context.before_write()
    return updated


def finish_phase(
    progress: dict[str, object],
    context: PublishContext,
    *,
    completed_key: str,
    id_key: str,
    remote_id: str,
) -> dict[str, object]:
    value = str(remote_id or "").strip()
    if not value:
        raise PublishError(
            "Платформа не повернула ID після запису. Результат вважається невідомим, повтор заблоковано.",
            retryable=False,
            outcome_unknown=True,
        )
    updated = {**progress, completed_key: True, id_key: value}
    context.save_progress(updated)
    return updated
