from __future__ import annotations

import threading

from ..collector_v1_2_rc3 import collect_source_rc3
from ..editorial_memory_v1_2_rc3 import rank_editorial_examples_rc3, rank_topic_candidates_rc3
from ..media_discovery_v1_2_rc3 import discover_group_media_rc3
from ..publisher_factory_v1_2_rc3_compat import Rc3CompatiblePublisherFactory
from ..publication_policy_v1_2_rc3 import compose_publication_text_rc3
from ..rewriter_v1_2_rc3 import rewrite_article_with_fallback_rc3
from ..short_source_v1_2_rc3 import source_values_rc3
from ..strict_ollama_decode_v1_2_rc3 import decode_rewrite_payload_rc3
from ..topic_search_v1_2_rc3 import build_topic_prompt_rc3
from ..worker_v1_2 import ManagedMediaPublicationWorker
from .. import ollama_client as ollama_module
from .. import rewriter_v1_2_rc3 as rc3_rewriter
from . import main_window as legacy_ui
from . import v1_2_rc2_window as rc2_ui
from .v1_2_rc2_window import MainWindow as RC2MainWindow

_BASE_TARGET_LABELS = legacy_ui.target_labels
_BASE_TARGET_KEYS = legacy_ui.publication_target_keys


def _target_labels_rc3(config: object) -> dict[str, str]:
    labels = _BASE_TARGET_LABELS(config)
    labels["instagram"] = "Instagram (не підключено)"
    return labels


def _target_keys_rc3(config: object) -> list[str]:
    keys = _BASE_TARGET_KEYS(config)
    if "instagram" not in keys:
        keys.append("instagram")
    return keys


def _install_rc3_overrides() -> None:
    legacy_ui.compose_publication_text = compose_publication_text_rc3
    legacy_ui.collect_source = collect_source_rc3
    legacy_ui.rank_editorial_examples = rank_editorial_examples_rc3
    legacy_ui.rank_topic_candidates = rank_topic_candidates_rc3
    legacy_ui.build_topic_prompt = build_topic_prompt_rc3
    legacy_ui.rewrite_article_with_fallback = rewrite_article_with_fallback_rc3
    legacy_ui.target_labels = _target_labels_rc3
    legacy_ui.publication_target_keys = _target_keys_rc3
    rc2_ui.discover_group_media = discover_group_media_rc3
    ollama_module._decode_rewrite_payload = decode_rewrite_payload_rc3
    rc3_rewriter._source_values = source_values_rc3


class MainWindow(RC2MainWindow):
    """RC3 field-feedback build: cleaner text, better retrieval/media and comments."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        _install_rc3_overrides()
        super().__init__(*args, **kwargs)

        self.publisher_factory = Rc3CompatiblePublisherFactory(self.config)
        self.worker = ManagedMediaPublicationWorker(
            self.db,
            self.publisher_factory,
            inter_target_delay_seconds=5.0,
            max_automatic_attempts=3,
            progress_callback=self._publication_progress_from_worker,
            result_callback=self._publication_result_from_worker,
            managed_media_registry=self.managed_media_registry,
        )
        self.worker_thread = threading.Thread(
            target=self.worker.run_loop,
            args=(self.stop_event,),
            name="publication-worker",
            daemon=True,
        )
        self.root.title("UA FREE Content Tool — v1.3.1-rc7")
