from __future__ import annotations

from .destinations_v1_4 import instagram_account_for_key, instagram_token_for
from .instagram_target_v1_2_rc4 import InstagramTarget
from .publisher_factory_v1_3_1_rc8 import Rc8InstagramPublisher, Rc8PublisherFactory
from .publishers import PublishError, Publisher


class V14PublisherFactory(Rc8PublisherFactory):
    """Resolve concrete Instagram destinations without duplicating Meta secrets."""

    def create(self, platform: str) -> Publisher:
        key = str(platform or "").strip()
        if key.startswith("instagram:"):
            if not self.config.instagram_enabled:
                raise PublishError("Instagram вимкнено в налаштуваннях.", retryable=False, auth_error=True)
            account = instagram_account_for_key(self.config, key)
            if account is None:
                raise PublishError(
                    f"Instagram-акаунт {key} не знайдено. Оновіть список акаунтів у налаштуваннях.",
                    retryable=False,
                    auth_error=True,
                )
            token = instagram_token_for(self.config, account)
            if not token:
                raise PublishError(
                    "Для цього Instagram-акаунта немає чинного Page Access Token. "
                    "Оновіть Facebook Pages / Instagram у налаштуваннях.",
                    retryable=False,
                    auth_error=True,
                )
            donation_text, enabled = self._policy(key)
            # Old donation settings contain the generic Instagram key. Preserve
            # that preference until the user explicitly configures the new target.
            if key not in self.donation_settings.targets:
                donation_text, enabled = self._policy("instagram")
            return Rc8InstagramPublisher(
                InstagramTarget(account.id, token, self.config.meta_graph_version),
                donation_text=donation_text,
                enabled=enabled,
            )
        return super().create(key)
