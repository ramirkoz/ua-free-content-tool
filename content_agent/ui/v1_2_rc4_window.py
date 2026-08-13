from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

from ..instagram_api_v1_2_rc4 import InstagramError, inspect_instagram_profile
from ..multi_image_store_v1_2_rc4 import MultiImageStore
from ..publisher_factory_v1_2_rc3_compat import Rc3CompatiblePublisherFactory
from ..worker_v1_2_rc4 import Rc4PublicationWorker
from .v1_2_rc3_final_window import MainWindow as RC3FinalWindow


class MainWindow(RC3FinalWindow):
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.multi_image_store = MultiImageStore()
        super().__init__(*args, **kwargs)
        self.root.title("UA FREE Content Tool — v1.2.0-dev RC4")
