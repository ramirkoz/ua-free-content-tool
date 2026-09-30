from __future__ import annotations

import pytest

from content_agent.config import AppConfig
from content_agent.donation_settings_v1_3_1_rc8 import DonationSettings
from content_agent.publisher_factory_v1_4 import V14PublisherFactory
from content_agent.v2.publishing.registry import DestinationError
from content_agent.v2.publishing.service import PublicationService


def test_active_v14_factory_owns_registry_and_publication_service():
    factory = V14PublisherFactory(AppConfig(), DonationSettings())
    assert isinstance(factory.publication_service, PublicationService)
    assert factory.publication_service.registry is factory.destination_registry
    assert set(factory.destination_registry.families()) == {"facebook", "instagram", "linkedin", "telegram", "threads"}


def test_active_factory_returns_service_backed_publisher_before_transport_creation():
    factory = V14PublisherFactory(AppConfig(), DonationSettings())
    publisher = factory.create("telegram:test-channel")
    assert publisher.__class__.__name__ == "_RegistryPublisher"


def test_active_factory_rejects_google_drive_as_publisher():
    factory = V14PublisherFactory(AppConfig(), DonationSettings())
    with pytest.raises(DestinationError):
        factory.create("google_drive")
