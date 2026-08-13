from __future__ import annotations

from ..image_registration_v1_2_rc4 import register_secondary_image


class MultiImageActionsMixin:
    def register_extra_image(self, upload, group_id: int) -> None:
        register_secondary_image(
            self.db,
            self.managed_media_registry,
            self.multi_image_store,
            upload,
            group_id,
        )
        self._refresh_attached_images()
