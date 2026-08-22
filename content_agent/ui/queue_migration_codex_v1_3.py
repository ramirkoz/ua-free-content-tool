from __future__ import annotations

import threading

from ..ai_router_v1_2_1 import last_ai_result_label, run_ai
from ..queue_migration import critical_fact_warnings
from .queue_migration_dialog import QueueMigrationDialog


def run_codex(prompt: str) -> str:
    """Backward-compatible test seam; production routing still goes through AI Router."""
    return run_ai(prompt).text


_ROUTER_RUN_CODEX = run_codex


class CodexQueueMigrationDialog(QueueMigrationDialog):
    """Legacy class name; queue migration now uses the automatic AI Router."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.generate_button.configure(text="Переробити всі через AI Router")

    @staticmethod
    def _compress_with_codex(text: str, limit: int, language: str) -> str:
        language_rule = "українською" if language == "uk" else "англійською"
        prompt = f"""
Скороти вже схвалений редактором новинний текст до максимум {limit} символів разом із пробілами.

ПРАВИЛА:
- Пиши {language_rule}.
- Не додавай жодних нових фактів, оцінок або пояснень.
- Збережи імена, назви, дати, числа, місця, причини та наслідки настільки повно, наскільки дозволяє ліміт.
- Не додавай заголовок, службові секції, markdown, лапки навколо всього тексту чи коментар від себе.
- Поверни ТІЛЬКИ готовий скорочений текст.
- Результат не може перевищувати {limit} символів.

ПОЧАТКОВИЙ ТЕКСТ:
{text}
""".strip()
        def validate(raw: str) -> None:
            value = str(raw or "").strip()
            if not value:
                raise RuntimeError("AI повернув порожній текст.")
            if len(value) > limit:
                raise RuntimeError(f"AI перевищив ліміт: {len(value)} / {limit} символів.")

        # Historical tests monkeypatch the old module-level ``run_codex`` seam.
        # Production never uses it: the default path below always goes through
        # AI Router so quota/auth/model failures can fall through automatically.
        if run_codex is not _ROUTER_RUN_CODEX:
            result = run_codex(prompt).strip()
            validate(result)
            return result

        routed = run_ai(prompt, validator=validate)
        result = routed.text.strip()
        validate(result)
        return result

    def _generate_all(self) -> None:
        self._save_current()
        self._set_busy(True, "AI Router послідовно стискає тексти. Черга та планувальник залишаються вимкненими.")

        def runner() -> None:
            results: dict[int, tuple[str, str, bool]] = {}
            errors: dict[int, str] = {}
            for index, batch_id in enumerate(self.order, start=1):
                candidate = self.candidates[batch_id]
                try:
                    text = self._compress_with_codex(candidate.old_text, candidate.limit, self.language)
                    warnings = critical_fact_warnings(candidate.old_text, text, language=self.language)
                    if warnings:
                        self.parent.after(
                            0,
                            lambda w="; ".join(warnings): self.warning_var.set(w),
                        )
                    engine = last_ai_result_label()
                    results[batch_id] = (text, engine, engine != "Codex / ChatGPT")
                except Exception as exc:
                    errors[batch_id] = str(exc)
                self.parent.after(
                    0,
                    lambda i=index, total=len(self.order), bid=batch_id: self.status_var.set(
                        self.t(f"Оброблено {i}/{total}: пакет #{bid}.")
                    ),
                )

            def finish() -> None:
                for batch_id, (text, model, used_fallback) in results.items():
                    self.drafts[batch_id] = text
                    self.models[batch_id] = model + (" (запасна)" if used_fallback else "")
                    self.errors.pop(batch_id, None)
                    self._refresh_row(batch_id)
                for batch_id, error in errors.items():
                    self.errors[batch_id] = error
                    self._refresh_row(batch_id)
                if self.current_batch_id is not None:
                    self._load_candidate(self.current_batch_id)
                self._set_busy(
                    False,
                    "Стискання через AI Router завершено. Перегляньте кожен текст і за потреби виправте вручну.",
                )

            self.parent.after(0, finish)

        threading.Thread(target=runner, name="queue-900-migration-ai-router", daemon=True).start()
