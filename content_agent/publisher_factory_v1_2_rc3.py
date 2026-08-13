from __future__ import annotations

from .facebook_comments_v1_2_rc3 import CommentedFacebookPublisher
from .linkedin_comments_v1_2_rc3 import CommentedLinkedInPublisher
from .publishers import PublishError, Publisher
from .safe_publishers_v1_2 import SafePublisherFactory
from .threads_comments_v1_2_rc3 import CommentedThreadsPublisher


class Rc3PublisherFactory(SafePublisherFactory):
    def create(self, platform: str) -> Publisher:
        if platform.startswith("facebook:"):
            page_id = platform.split(":", 1)[1]
            page = self.config.facebook_page(page_id)
            if page is not None:
                return CommentedFacebookPublisher(
                    page["id"], page["access_token"], self.config.meta_graph_version
                )
            return super().create(platform)
        if platform == "threads":
            return CommentedThreadsPublisher(
                self.config.threads_user_id,
                self.config.threads_token,
            )
        if platform == "linkedin":
            return CommentedLinkedInPublisher(
                self.config.linkedin_author_urn,
                self.config.linkedin_token,
                self.config.linkedin_version,
            )
        if platform == "instagram":
            raise PublishError(
                "Instagram додано до інтерфейсу RC3, але підключення ще не налаштовано.",
                retryable=False,
                auth_error=True,
            )
        return super().create(platform)
