from __future__ import annotations

from .comment_compat_v1_2_rc3 import (
    CompatibleFacebookPublisher,
    CompatibleLinkedInPublisher,
    CompatibleTelegramPublisher,
    CompatibleThreadsPublisher,
)
from .instagram_target_v1_2_rc4 import InstagramTarget
from .publishers import PublishError, Publisher
from .safe_publishers_v1_2 import SafePublisherFactory


class Rc3CompatiblePublisherFactory(SafePublisherFactory):
    def create(self, platform: str) -> Publisher:
        if platform == "telegram":
            return CompatibleTelegramPublisher(self.config.telegram_bot_token, self.config.telegram_chat_id)
        if platform.startswith("facebook:"):
            page_id = platform.split(":", 1)[1]
            page = self.config.facebook_page(page_id)
            if page is not None:
                return CompatibleFacebookPublisher(page["id"], page["access_token"], self.config.meta_graph_version)
            if platform == "facebook:1":
                return CompatibleFacebookPublisher(self.config.facebook_page_1_id, self.config.facebook_page_1_token, self.config.meta_graph_version)
            if platform == "facebook:2":
                return CompatibleFacebookPublisher(self.config.facebook_page_2_id, self.config.facebook_page_2_token, self.config.meta_graph_version)
        if platform == "threads":
            return CompatibleThreadsPublisher(self.config.threads_user_id, self.config.threads_token)
        if platform == "linkedin":
            return CompatibleLinkedInPublisher(self.config.linkedin_author_urn, self.config.linkedin_token, self.config.linkedin_version)
        if platform == "instagram":
            if self.config.instagram_enabled:
                return InstagramTarget(
                    self.config.instagram_user_id,
                    self.config.instagram_token,
                    self.config.meta_graph_version,
                )
            raise PublishError("Instagram вимкнено в налаштуваннях.", retryable=False, auth_error=True)
        return super().create(platform)
