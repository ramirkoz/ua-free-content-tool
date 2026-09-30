from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ...config import AppConfig
from ...publishers import Publisher, PublisherFactory


@dataclass(frozen=True, slots=True)
class DestinationSpec:
    key: str
    platform: str
    label: str
    configured: bool
    enabled: bool
    publisher_factory_key: str | None = None
    requires_public_media_url: bool = False
    managed_elsewhere: bool = False

    @property
    def ready(self) -> bool:
        return bool(self.enabled and self.configured)


class DestinationRegistry:
    """One authoritative view of publication destinations.

    The existing platform transports remain untouched. This registry owns naming,
    readiness and routing metadata so UI, queue code and diagnostics no longer need
    separate hard-coded destination lists.
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def all(self) -> tuple[DestinationSpec, ...]:
        rows: list[DestinationSpec] = []

        telegram_key = "telegram"
        rows.append(
            DestinationSpec(
                key=telegram_key,
                platform="telegram",
                label="Telegram",
                configured=self.config.platform_ready(telegram_key),
                enabled=bool(self.config.telegram_enabled),
                publisher_factory_key=telegram_key,
            )
        )

        seen_pages: set[str] = set()
        for page in self.config.facebook_pages:
            if not isinstance(page, dict):
                continue
            page_id = str(page.get("id") or "").strip()
            if not page_id or page_id in seen_pages:
                continue
            seen_pages.add(page_id)
            key = f"facebook:{page_id}"
            rows.append(
                DestinationSpec(
                    key=key,
                    platform="facebook",
                    label=str(page.get("name") or page_id),
                    configured=self.config.platform_ready(key),
                    enabled=bool(self.config.facebook_enabled),
                    publisher_factory_key=key,
                )
            )
        # Preserve the two historical slots when an older config has not migrated
        # to the list-backed page representation yet.
        for slot, page_id, name in (
            ("1", self.config.facebook_page_1_id, self.config.facebook_page_1_name),
            ("2", self.config.facebook_page_2_id, self.config.facebook_page_2_name),
        ):
            page_id = str(page_id or "").strip()
            if not page_id or page_id in seen_pages:
                continue
            key = f"facebook:{slot}"
            rows.append(
                DestinationSpec(
                    key=key,
                    platform="facebook",
                    label=str(name or f"Facebook {slot}"),
                    configured=self.config.platform_ready(key),
                    enabled=bool(self.config.facebook_enabled),
                    publisher_factory_key=key,
                )
            )

        rows.append(
            DestinationSpec(
                key="instagram",
                platform="instagram",
                label=str(self.config.instagram_profile_name or "Instagram"),
                configured=self.config.platform_ready("instagram"),
                enabled=bool(self.config.instagram_enabled),
                requires_public_media_url=True,
                managed_elsewhere=True,
            )
        )
        rows.append(
            DestinationSpec(
                key="threads",
                platform="threads",
                label=str(self.config.threads_profile_name or "Threads"),
                configured=self.config.platform_ready("threads"),
                enabled=bool(self.config.threads_enabled),
                publisher_factory_key="threads",
                requires_public_media_url=True,
            )
        )
        rows.append(
            DestinationSpec(
                key="linkedin",
                platform="linkedin",
                label=str(self.config.linkedin_profile_name or "LinkedIn"),
                configured=self.config.platform_ready("linkedin"),
                enabled=bool(self.config.linkedin_enabled),
                publisher_factory_key="linkedin",
            )
        )
        rows.append(
            DestinationSpec(
                key="google_drive",
                platform="google_drive",
                label=str(self.config.google_account_email or "Google Drive"),
                configured=self.config.platform_ready("google_drive"),
                enabled=True,
                publisher_factory_key=None,
                managed_elsewhere=True,
            )
        )
        return tuple(rows)

    def get(self, key: str) -> DestinationSpec | None:
        target = str(key or "").strip()
        return next((row for row in self.all() if row.key == target), None)

    def ready(self) -> tuple[DestinationSpec, ...]:
        return tuple(row for row in self.all() if row.ready)

    def create_publisher(self, key: str) -> Publisher:
        spec = self.get(key)
        if spec is None:
            raise KeyError(f"Unknown publication destination: {key}")
        if not spec.ready:
            raise RuntimeError(f"Destination is not ready: {key}")
        if not spec.publisher_factory_key:
            raise RuntimeError(f"Destination is managed outside PublisherFactory: {key}")
        return PublisherFactory(self.config).create(spec.publisher_factory_key)

    def labels(self) -> dict[str, str]:
        return {row.key: row.label for row in self.all()}


__all__ = ["DestinationRegistry", "DestinationSpec"]
