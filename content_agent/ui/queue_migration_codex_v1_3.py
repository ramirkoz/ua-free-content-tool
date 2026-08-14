from __future__ import annotations

import threading

from ..codex_engine_v1_3 import run_codex
from ..queue_migration import critical_fact_warnings
from .queue_migration_dialog import QueueMigrationDialog


class CodexQueueMigrationDialog(QueueMigrationDialog):
    """RC5 queue migration uses Codex/ChatGPT instead of local Ollama."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.generate_button.configure(text="Переробити всі через Codex / ChatGPT")

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
        result = run_codex(prompt).strip()
        if not result:
            raise RuntimeError("Codex повернув порожній текст.")
        if len(result) > limit:
            raise RuntimeError(f"Codex перевищив ліміт: {len(result)} / {limit} символів.")
        return result

    def _generate_all(self) -> None:
        self._save_current()
        self._set_busy(True, "Codex послідовно стискає тексти. Черга та планувальник залишаються вимкненими.")

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
                    results[batch_id] = (text, "Codex / ChatGPT", False)
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
                    "Стискання через Codex завершено. Перегляньте кожен текст і за потреби виправте вручну.",
                )

            self.parent.after(0, finish)

        threading.Thread(target=runner, name="queue-900-migration-codex", daemon=True).start()
