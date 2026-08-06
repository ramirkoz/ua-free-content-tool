from __future__ import annotations

from io import BytesIO
from typing import Any

from PIL import Image, ImageTk, UnidentifiedImageError

from ..google_drive import GoogleDriveError
from ..managed_media_drive import ManagedMediaUpload
from ..media_candidates import MediaCandidate, ValidatedMedia, download_media_candidate
from .media_workflow import MediaWorkflowMixin, media_filename_from_url

Image.MAX_IMAGE_PIXELS = 40_000_000


def make_thumbnail(data: bytes, max_size: tuple[int, int] = (280, 190)) -> Image.Image:
    """Decode a verified image and return a detached thumbnail."""

    try:
        with Image.open(BytesIO(data)) as opened:
            opened.load()
            image = opened.convert("RGBA")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise GoogleDriveError("Не вдалося безпечно відкрити зображення для попереднього перегляду.") from exc
    image.thumbnail(max_size, Image.Resampling.LANCZOS)
    return image


class MediaPreviewMixin(MediaWorkflowMixin):
    """Thumbnail preview and download cache layered over the media workflow."""

    def _build_editor_tab(self) -> None:
        self._media_download_cache: dict[str, ValidatedMedia] = {}
        self._media_preview_photo: ImageTk.PhotoImage | None = None
        super()._build_editor_tab()
        if not hasattr(self, "media_candidates_tree"):
            return
        frame = self.media_candidates_tree.master
        self.media_candidates_tree.grid_configure(columnspan=5)
        self.media_preview_label = __import__("tkinter.ttk", fromlist=["Label"]).Label(
            frame,
            text="Оберіть фото для перегляду",
            anchor="center",
            justify="center",
            width=30,
        )
        self.media_preview_label.grid(row=1, column=5, sticky="nsew", padx=(7, 0), pady=(0, 6))
        self.media_candidates_tree.bind(
            "<<TreeviewSelect>>",
            lambda _event: self.preview_selected_media_candidate(),
            add="+",
        )

    def _set_media_candidates(self, candidates: list[MediaCandidate]) -> None:
        super()._set_media_candidates(candidates)
        self._media_preview_photo = None
        if hasattr(self, "media_preview_label"):
            self.media_preview_label.configure(image="", text="Оберіть фото для перегляду")

    def _show_media_preview(self, candidate: MediaCandidate, media: ValidatedMedia) -> None:
        if candidate.kind == "video" or media.kind == "video":
            self._media_preview_photo = None
            self.media_preview_label.configure(
                image="",
                text=f"ВІДЕО\n{candidate.source_label or 'Джерело новини'}\n{media.mime_type}",
            )
            return
        thumbnail = make_thumbnail(media.data)
        photo = ImageTk.PhotoImage(thumbnail, master=self.root)
        self._media_preview_photo = photo
        self.media_preview_label.configure(image=photo, text="", compound="top")

    def preview_selected_media_candidate(self) -> None:
        candidate = self._selected_media_candidate()
        if candidate is None or not hasattr(self, "media_preview_label"):
            return
        cached = self._media_download_cache.get(candidate.url)
        if cached is not None:
            self._show_media_preview(candidate, cached)
            return
        if candidate.kind == "video":
            self.media_preview_label.configure(
                image="",
                text=f"ВІДЕО\n{candidate.source_label or 'Джерело новини'}\nПрев’ю кадру не завантажується",
            )
            return
        self.media_preview_label.configure(image="", text="Завантажую прев’ю…")

        def success(result: object) -> None:
            if not isinstance(result, ValidatedMedia):
                raise GoogleDriveError("Не вдалося отримати медіафайл для перегляду.")
            self._media_download_cache[candidate.url] = result
            current = self._selected_media_candidate()
            if current is not None and current.url == candidate.url:
                self._show_media_preview(candidate, result)

        self.run_async(
            lambda: download_media_candidate(candidate),
            success,
            label="Завантажую безпечне прев’ю медіа",
            done_label="Прев’ю готове",
        )

    def use_selected_media_candidate(self) -> None:
        candidate = self._selected_media_candidate()
        if candidate is None:
            self.msg.showinfo("Медіа", "Оберіть файл у списку знайдених медіа.", parent=self.root)
            return

        def action() -> object:
            media = self._media_download_cache.get(candidate.url)
            if media is None:
                media = download_media_candidate(candidate)
            filename = media_filename_from_url(media.source_url or candidate.url, media.mime_type)
            return self._managed_drive_client().upload_validated_media(media, filename)

        def success(result: object) -> None:
            if not isinstance(result, ManagedMediaUpload):
                raise GoogleDriveError("Google Drive не повернув результат завантаження.")
            self._attach_uploaded_media(result)
            self.media_candidates_status_var.set(
                f"Використано медіа з джерела «{candidate.source_label or 'новина'}»."
            )

        self.run_async(
            action,
            success,
            label="Додаю вибране медіа в Google Drive",
            done_label="Вибране медіа готове",
        )
