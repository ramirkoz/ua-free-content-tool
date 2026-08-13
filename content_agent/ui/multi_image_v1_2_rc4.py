from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..google_drive import GoogleDriveError
from ..managed_media_drive import ManagedMediaUpload
from ..multi_image_store_v1_2_rc4 import MAX_IMAGE_ATTACHMENTS, MultiImageStoreError, StoredImageAttachment
from .media_workflow import format_media_size


class MultiImageEditorMixin:
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[misc]
        self._upgrade_multi_image_editor()

    def _upgrade_multi_image_editor(self) -> None:
        tree = getattr(self, "media_candidates_tree", None)
        if tree is None:
            return
        tree.configure(selectmode="extended")
        frame = tree.master
        ttk.Separator(frame, orient="horizontal").grid(
            row=5, column=0, columnspan=6, sticky="ew", pady=(6, 4)
        )
        ttk.Label(frame, text="Прикріплені фото (до 10)").grid(
            row=6, column=0, columnspan=6, sticky="w", pady=(0, 3)
        )
        self.attached_images_tree = ttk.Treeview(
            frame,
            columns=("number", "name", "size"),
            show="headings",
            selectmode="extended",
            height=3,
        )
        self.attached_images_tree.heading("number", text="№")
        self.attached_images_tree.heading("name", text="Файл")
        self.attached_images_tree.heading("size", text="Розмір")
        self.attached_images_tree.column("number", width=45, anchor="center")
        self.attached_images_tree.column("name", width=700, anchor="w")
        self.attached_images_tree.column("size", width=120, anchor="w")
        self.attached_images_tree.grid(row=7, column=0, columnspan=5, sticky="ew", pady=(0, 4))
        remove_button = ttk.Button(
            frame,
            text="Прибрати вибрані фото",
            command=self.remove_selected_attached_images,
        )
        remove_button.grid(row=7, column=5, sticky="n", padx=(6, 0))
        self.operation_buttons.append(remove_button)  # type: ignore[attr-defined]
        for child in frame.winfo_children():
            if isinstance(child, ttk.Button) and str(child.cget("text")) == "Використати вибране":
                child.configure(text="Додати вибране")
        self._refresh_attached_images()

    def _attachment_rows(self, group_id: int | None = None) -> list[StoredImageAttachment]:
        target = int(group_id or getattr(self, "current_group_id", 0) or 0)
        if not target:
            return []
        rows = self.multi_image_store.list_group(target)  # type: ignore[attr-defined]
        if rows:
            return rows
        group = self.db.get_group(target)  # type: ignore[attr-defined]
        if group.media_file_id and group.media_kind == "image":
            return [
                StoredImageAttachment(
                    file_id=group.media_file_id,
                    name=group.media_name or "image",
                    mime_type=group.media_mime or "image/jpeg",
                    size=int(group.media_size or 0),
                    drive_url=group.media_drive_url,
                )
            ]
        return []

    def _refresh_attached_images(self) -> None:
        tree = getattr(self, "attached_images_tree", None)
        if tree is None:
            return
        tree.delete(*tree.get_children())
        for index, item in enumerate(self._attachment_rows(), start=1):
            tree.insert("", "end", iid=item.file_id, values=(index, item.name, format_media_size(item.size)))

    def load_group(self, group_id: int) -> None:
        super().load_group(group_id)  # type: ignore[misc]
        self._refresh_attached_images()
