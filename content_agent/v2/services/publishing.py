from __future__ import annotations

from ...publisher_factory_v1_4 import V14PublisherFactory
from ...worker_v1_4_rc10 import Rc10PublicationWorker
from ..publishing.registry import DestinationRegistry
from ..publishing.adapters import GoogleDriveMediaAdapter, build_authenticators, build_publisher_adapters


class PublishingService:
    """Composition boundary for the active publisher factory and worker."""

    def __init__(self, config, registry: DestinationRegistry) -> None:
        self.config = config
        self.registry = registry

    def create_factory(self, donation_settings):
        factory = V14PublisherFactory(self.config, donation_settings)
        self.authenticators = build_authenticators(self.config)
        self.adapters = build_publisher_adapters(factory)
        self.media = GoogleDriveMediaAdapter(self.config)
        return factory

    def adapter_for(self, destination_key: str):
        base = str(destination_key or "").split(":", 1)[0]
        return getattr(self, "adapters", {}).get(base)

    def auth_for(self, destination_key: str):
        base = str(destination_key or "").split(":", 1)[0]
        return getattr(self, "authenticators", {}).get(base)

    def create_worker(
        self,
        database,
        factory,
        *,
        progress_callback,
        result_callback,
        managed_media_registry,
        image_store,
    ):
        return Rc10PublicationWorker(
            database,
            factory,
            inter_target_delay_seconds=0.0,
            progress_callback=progress_callback,
            result_callback=result_callback,
            managed_media_registry=managed_media_registry,
            image_store=image_store,
        )
