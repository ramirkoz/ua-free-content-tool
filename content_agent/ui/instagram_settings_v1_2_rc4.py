from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

from ..instagram_api_v1_2_rc4 import inspect_instagram_profile


class InstagramSettingsMixin:
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[misc]
        self._upgrade_instagram_settings()
