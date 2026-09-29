from __future__ import annotations

from ...ai_router import (
    AIProviderSecrets,
    load_provider_secrets,
    provider_health_text,
    save_provider_secrets,
    test_ai_router,
)
from .manual_topics_window_rc44 import MainWindow as Rc49BaseMainWindow


class MainWindow(Rc49BaseMainWindow):
    """Active RC49 window with explicit V2 AI-provider callbacks.

    The canonical V2 AI tab is built in ``v2.ui.window.MainWindow``.  Its buttons
    resolve callbacks on the concrete runtime instance, so keeping these callbacks
    on the active shell makes the contract explicit and prevents startup from
    failing when a historical RC layer no longer provides them.
    """

    def save_ai_provider_keys(self) -> None:
        try:
            current = load_provider_secrets()
            values = getattr(self, "ai_provider_vars", {})
            updated = AIProviderSecrets(
                gemini_api_key=str(values["gemini_api_key"].get() or ""),
                nvidia_api_key=str(values["nvidia_api_key"].get() or ""),
                groq_api_key=str(values["groq_api_key"].get() or ""),
                cloudflare_account_id=str(values["cloudflare_account_id"].get() or ""),
                cloudflare_api_token=str(values["cloudflare_api_token"].get() or ""),
                codex_enabled=bool(self.codex_enabled_var.get()),
                local_enabled=bool(self.local_enabled_var.get()),
                local_base_url=current.local_base_url,
                local_model=current.local_model,
            )
            save_provider_secrets(updated)
            self.refresh_v2_ai_status()
            self.v2_router_status_var.set(provider_health_text())
            self.set_status("AI Router: прямі провайдери збережено.")
        except Exception as exc:
            self._show_error(exc)

    def test_ai_router_ui(self) -> None:
        def action() -> str:
            return test_ai_router()

        def success(result: object) -> None:
            self.refresh_v2_ai_status()
            health = provider_health_text()
            self.v2_router_status_var.set(f"{result}\n{health}" if health else str(result))
            self.set_status(str(result))

        self.run_async(
            action,
            success,
            label="Перевіряю AI Router",
            done_label="AI Router перевірено",
            timeout_seconds=165,
            timeout_message="AI Router не завершив перевірку за 165 секунд.",
            modal_errors=False,
            modal_timeout=False,
        )
