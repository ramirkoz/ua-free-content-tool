from __future__ import annotations

from .instagram_api_v1_2_rc4 import (
    InstagramError,
    create_instagram_carousel,
    create_instagram_container,
    publish_instagram_container,
    wait_instagram_container,
)
from .media_gallery_v1_2_rc4 import ImageGalleryPayload
from .models import MediaPayload
from .publishers import PublishContext, PublishError, PublishResult, Publisher


class InstagramTarget(Publisher):
    def __init__(self, user_id: str, token: str, graph_version: str):
        if not user_id or not token:
            raise PublishError("Instagram не підключено.", retryable=False, auth_error=True)
        self.user_id = user_id
        self.token = token
        self.graph_version = graph_version

    def publish(
        self,
        text: str,
        progress: dict[str, object],
        context: PublishContext,
        media: MediaPayload | ImageGalleryPayload | None = None,
    ) -> PublishResult:
        remote_id = str(progress.get("instagram_remote_id") or "").strip()
        if remote_id:
            return PublishResult(remote_id=remote_id, progress=progress)
        if media is None:
            raise PublishError("Instagram потребує фото або відео.", retryable=False)
        try:
            container_id = str(progress.get("instagram_container_id") or "").strip()
            if not container_id:
                if isinstance(media, ImageGalleryPayload):
                    child_ids = list(progress.get("instagram_child_ids") or [])
                    for item in media.items[len(child_ids):]:
                        child_id = create_instagram_container(
                            self.user_id,
                            self.token,
                            self.graph_version,
                            public_url=item.public_url,
                            kind="image",
                            carousel_item=True,
                        )
                        wait_instagram_container(child_id, self.token, self.graph_version)
                        child_ids.append(child_id)
                        progress = {**progress, "instagram_child_ids": child_ids}
                        context.save_progress(progress)
                    container_id = create_instagram_carousel(
                        self.user_id,
                        self.token,
                        self.graph_version,
                        child_ids,
                        text,
                    )
                else:
                    if not media.public_url:
                        raise PublishError("Instagram потребує тимчасово доступне медіапосилання.")
                    container_id = create_instagram_container(
                        self.user_id,
                        self.token,
                        self.graph_version,
                        public_url=media.public_url,
                        kind=media.kind,
                        caption=text,
                    )
                progress = {**progress, "instagram_container_id": container_id}
                context.save_progress(progress)
            wait_instagram_container(container_id, self.token, self.graph_version)
            if progress.get("instagram_publish_started") and not progress.get("instagram_remote_id"):
                raise PublishError(
                    "Instagram: результат попередньої публікації невідомий; автоматичний повтор заблоковано.",
                    retryable=False,
                    outcome_unknown=True,
                )
            progress = {**progress, "instagram_publish_started": True}
            context.save_progress(progress)
            context.before_write()
            remote_id = publish_instagram_container(
                self.user_id,
                self.token,
                self.graph_version,
                container_id,
            )
            progress = {
                **progress,
                "instagram_remote_id": remote_id,
                "instagram_publish_completed": True,
            }
            context.save_progress(progress)
            return PublishResult(remote_id=remote_id, progress=progress)
        except InstagramError as exc:
            raise PublishError(f"Instagram: {exc}") from exc
