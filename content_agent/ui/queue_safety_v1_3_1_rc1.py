from __future__ import annotations


class QueueSafetyRC1Mixin:
    """RC1 startup recovery and cooperative cancellation for the active UI."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        recovered = self.db.recover_abandoned_batches(max_automatic_attempts=3)
        if recovered:
            self.refresh_queue()
            self.status_var.set(
                "Безпечно призупинено перервані/виснажені пакети: "
                + ", ".join(f"#{item}" for item in recovered[:12])
            )

    def cancel_selected_batches(self) -> None:
        batch_ids = self._selected_queue_batch_ids()
        if not batch_ids:
            self.msg.showinfo("Черга", "Оберіть один або кілька пакетів у списку.", parent=self.root)
            return

        if len(batch_ids) == 1:
            title = "Скасування пакета"
            question = (
                f"Скасувати пакет #{batch_ids[0]} і прибрати його з активної черги?\n\n"
                "Уже опубліковані дописи не видаляються. Сам блок новини залишиться доступним для повторного налаштування."
            )
        else:
            title = "Скасування вибраних пакетів"
            shown = ", ".join(f"#{item}" for item in batch_ids[:12])
            if len(batch_ids) > 12:
                shown += f" та ще {len(batch_ids) - 12}"
            question = (
                f"Скасувати {len(batch_ids)} вибраних пакетів і прибрати їх з активної черги?\n\n"
                f"Пакети: {shown}.\n\n"
                "Операція виконується цілісно: якщо хоча б один пакет зараз публікується або вже завершений, жоден із вибраних пакетів не буде скасовано. "
                "Уже опубліковані дописи не видаляються."
            )
        if not self.msg.askyesno(title, question, parent=self.root):
            return

        try:
            batches = [self.db.get_batch(batch_id) for batch_id in batch_ids]
            active = [batch for batch in batches if batch.status == "in_progress"]
            if active:
                if len(batch_ids) != 1:
                    raise ValueError(
                        "Пакет, що публікується, зупиняйте окремо. Інші вибрані пакети не змінено."
                    )
                batch = active[0]
                if not self.worker.request_cancel(batch.id, reason="queue-ui-confirmed"):
                    raise ValueError(
                        f"Пакет #{batch.id} позначений як «публікується», але не належить поточному worker. "
                        "Оновіть чергу; після перезапуску 1.3.1 RC1 такий пакет буде безпечно призупинено."
                    )
                self.set_status(
                    f"Пакет #{batch.id}: зупинку запрошено. Нові платформи не запускатимуться."
                )
                self.msg.showinfo(
                    "Зупинка публікації",
                    f"Пакет #{batch.id}: запит на зупинку прийнято.\n\n"
                    "Якщо мережевий запит уже відправлено платформі, програма дочекається його завершення, "
                    "щоб не створити дубль. Нові платформи після цього не запускатимуться.",
                    parent=self.root,
                )
                self.worker.wake()
                return
            cancelled = self.db.cancel_batches(batch_ids)
        except Exception as exc:
            self._show_error(exc)
            return

        self.refresh_queue()
        self.refresh_groups()
        if not cancelled:
            result_text = "Усі вибрані пакети вже були скасовані."
        elif len(cancelled) == 1:
            result_text = f"Пакет #{cancelled[0]} скасовано й прибрано з активної черги."
        else:
            result_text = f"Скасовано й прибрано з активної черги: {len(cancelled)} пакетів."
        self.msg.showinfo("Черга", result_text, parent=self.root)
