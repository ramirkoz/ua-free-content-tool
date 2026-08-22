from __future__ import annotations

from ..media_order_v1_2_rc3 import order_media_by_source
from .v1_2_rc3_instagram_window import MainWindow as InstagramRC3Window


class MainWindow(InstagramRC3Window):
    def _set_media_candidates(self, candidates):
        articles = list(getattr(self, "current_group_articles", []))
        ordered = order_media_by_source(list(candidates), articles)
        return super()._set_media_candidates(ordered)
