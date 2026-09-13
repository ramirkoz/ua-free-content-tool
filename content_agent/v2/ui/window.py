from __future__ import annotations

import re
import tkinter as tk
from tkinter import ttk

from ...ai_router import (
    clear_router_cooldowns,
    load_provider_secrets,
    provider_health_text,
    save_provider_secrets,
    test_ai_router,
)
from ...codex_runtime import inspect_codex_cached
from ...inbox_layout_v1_3_1_rc8 import inbox_layout_path, save_widths
from ...ui.v1_4_rc30_window import MainWindow as Rc30MainWindow
from ..ai.openrouter_backend import OpenRouterBackend
from ..ai.service import backend_status, test_active_backend
from ..ai.settings import (
    AIBackendSettings,
    BACKEND_AGENT,
    BACKEND_OPENROUTER,
    BACKEND_ROUTER,
    load_backend_settings,
    load_openrouter_api_key,
    save_backend_settings,
    save_openrouter_api_key,
)
from ..ai.usage import usage_summary
from ..supervisor.diagnostics import instance_identity
from ..supervisor.runtime import SupervisorRuntime
from ..publishing.retry import assess_failed_target


class MainWindow(Rc30MainWindow):
    """V2 compatibility shell: RC30 behavior plus isolated V2 services.

    The old UI/runtime remains the functional baseline in rc1. New functionality
    is attached only through explicit V2 modules so the legacy chain can be retired
    incrementally instead of rewritten in one risky step.
    """

    VERSION_LABEL = "2.0.0-rc6"
