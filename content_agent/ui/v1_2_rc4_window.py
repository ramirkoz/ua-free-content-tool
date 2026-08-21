from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

from ..multi_image_store_v1_2_rc4 import MultiImageStore
from ..publisher_factory_v1_2_rc3_compat import Rc3CompatiblePublisherFactory
from ..worker_v1_2_rc4 import Rc4PublicationWorker
from .candidate_gallery_actions_v1_2_rc4 import CandidateGalleryActionsMixin
from .instagram_settings_v1_2_rc4 import InstagramSettingsMixin
from .local_gallery_actions_v1_2_rc4 import LocalGalleryActionsMixin
from .multi_image_actions_v1_2_rc4 import MultiImageActionsMixin
from .v1_2_rc3_final_window import MainWindow as RC3FinalWindow


class MainWindow(
    LocalGalleryActionsMixin,
    CandidateGalleryActionsMixin,
    MultiImageActionsMixin,
    InstagramSettingsMixin,
    RC3FinalWindow,
):
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.multi_image_store = MultiImageStore()
        super().__init__(*args, **kwargs)
        self.media_candidates_tree.configure(selectmode="extended")
        self._style_topic_search_button()
        self.publisher_factory = Rc3CompatiblePublisherFactory(self.config)
        self.worker = Rc4PublicationWorker(
            self.db,
            self.publisher_factory,
            inter_target_delay_seconds=5.0,
            max_automatic_attempts=3,
            progress_callback=self._publication_progress_from_worker,
            result_callback=self._publication_result_from_worker,
            managed_media_registry=self.managed_media_registry,
            image_store=self.multi_image_store,
        )
        self.worker_thread = threading.Thread(
            target=self.worker.run_loop,
            args=(self.stop_event,),
            name="publication-worker",
            daemon=True,
        )
        self.root.title("UA FREE Content Tool — v1.3.1-rc7")

    def _style_topic_search_button(self) -> None:
        for parent in self.root.winfo_children():
            found = self._replace_topic_button_in(parent)
            if found:
                return

    def _replace_topic_button_in(self, widget: tk.Misc) -> bool:
        for child in widget.winfo_children():
            if isinstance(child, ttk.Button):
                try:
                    text = str(child.cget("text"))
                except tk.TclError:
                    text = ""
                if text == "Пошук схожих за темою матеріалів":
                    parent = child.master
                    info = child.grid_info()
                    row = int(info.get("row", 0))
                    column = int(info.get("column", 0))
                    child.destroy()
                    tk.Button(
                        parent,
                        text=text,
                        command=self.find_all_by_topic,
                        bg="#1565c0",
                        fg="white",
                        activebackground="#0d47a1",
                        activeforeground="white",
                        relief="flat",
                        padx=9,
                        pady=4,
                    ).grid(row=row, column=column, padx=3)
                    return True
            if self._replace_topic_button_in(child):
                return True
        return False
