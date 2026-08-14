from __future__ import annotations

import tkinter as tk
from pathlib import Path, PurePosixPath
from tkinter import simpledialog, ttk
from typing import Any
from urllib.parse import urlsplit

from ..google_drive import GoogleDriveError
from ..managed_media_drive import (
    ManagedGoogleDriveClient,
    ManagedMediaUpload,
    safe_media_filename,
    validate_local_media,
)
from ..media_candidates import (
    MediaCandidate,
    MediaCandidateError,
    ValidatedMedia,
    download_media_candidate,
)
from ..media_discovery import discover_group_media, resolve_manual_media_url


def format_media_size(size: int) -> str:
    value = max(0, int(size or 0))
    if value >= 1024 * 1024:
        return f"{value / (1024 * 1024):.1f} МБ"
    if value >= 1024:
        return f"{value / 1024:.1f} КБ"
    return f"{value} Б"


def media_filename_from_url(url: str, mime_type: str) -> str:
    name = PurePosixPath(urlsplit(str(url or "")).path).name or "media"
    return safe_media_filename(name, mime_type)


class MediaWorkflowMixin:
    """Automatic source/local/URL media workflow for the v1.2 editor."""

    def _build_editor_tab(self) -> None:
        super()._build_editor_tab()  # type: ignore[misc]
        self._media_candidates: list[MediaCandidate] = []
        self._media_discovery_group_id: int | None = None
        self._upgrade_media_editor()

    def _upgrade_media_editor(self) -> None:
        frame: ttk.LabelFrame | None = None
        for child in self.publication_tab.winfo_children():  # type: ignore[attr-defined]
            if isinstance(child, ttk.LabelFrame):
                text = str(child.cget("text"))
                if text in {"Медіа з Google Drive", "Media from Google Drive"}:
                    frame = child
                    break
        if frame is None:
            return

        frame.configure(text="Медіа для публікації")
        for child in frame.winfo_children():
            child.grid_remove()

        self.media_candidates_status_var = tk.StringVar(
            value="Відкрийте новину. Програма сама перевірить її джерела на наявність фото й відео."
        )
        ttk.Label(
            frame,
            textvariable=self.media_candidates_status_var,
            foreground="#555",
            wraplength=1200,
            justify="left",
        ).grid(row=0, column=0, columnspan=6, sticky="ew", pady=(0, 5))

        columns = ("kind", "source", "details", "url")
        self.media_candidates_tree = ttk.Treeview(
            frame,
            columns=columns,
            show="headings",
            selectmode="browse",
            height=5,
        )
        headings = {
            "kind": "Тип",
            "source": "Джерело",
            "details": "Звідки знайдено",
            "url": "Файл",
        }
        widths = {"kind": 75, "source": 210, "details": 160, "url": 650}
        for column in columns:
            self.media_candidates_tree.heading(column, text=headings[column])
            self.media_candidates_tree.column(column, width=widths[column], anchor="w")
        self.media_candidates_tree.grid(row=1, column=0, columnspan=6, sticky="nsew", pady=(0, 6))
        self.media_candidates_tree.bind("<Double-1>", lambda _event: self.use_selected_media_candidate())

        refresh_button = ttk.Button(
            frame,
            text="Знайти медіа в джерелах",
            command=self.discover_current_group_media,
        )
        use_button = ttk.Button(
            frame,
            text="Використати вибране",
            command=self.use_selected_media_candidate,
        )
        local_button = ttk.Button(
            frame,
            text="Додати з комп’ютера",
            command=self.add_media_from_computer,
        )
        url_button = ttk.Button(
            frame,
            text="Додати за посиланням",
            command=self.add_media_by_url,
        )
        open_button = ttk.Button(frame, text="Відкрити прикріплене", command=self.open_media_link)  # type: ignore[attr-defined]
        clear_button = ttk.Button(frame, text="Прибрати медіа", command=self.clear_media)  # type: ignore[attr-defined]
        for index, button in enumerate(
            (refresh_button, use_button, local_button, url_button, open_button, clear_button)
        ):
            button.grid(row=2, column=index, sticky="w", padx=(0, 5), pady=(0, 4))
            self.operation_buttons.append(button)  # type: ignore[attr-defined]

        ttk.Separator(frame, orient="horizontal").grid(
            row=3,
            column=0,
            columnspan=6,
            sticky="ew",
            pady=(3, 4),
        )
        ttk.Label(
            frame,
            textvariable=self.media_status_var,  # type: ignore[attr-defined]
            foreground="#444",
            wraplength=1200,
            justify="left",
        ).grid(row=4, column=0, columnspan=6, sticky="ew")
        frame.columnconfigure(3, weight=1)
        frame.rowconfigure(1, weight=1)

    def load_group(self, group_id: int) -> None:
        super().load_group(group_id)  # type: ignore[misc]
        self._media_discovery_group_id = group_id
        self._set_media_candidates([])
        self.root.after(120, self.discover_current_group_media)  # type: ignore[attr-defined]

    def _set_media_candidates(self, candidates: list[MediaCandidate]) -> None:
        self._media_candidates = list(candidates)
        if not hasattr(self, "media_candidates_tree"):
            return
        tree = self.media_candidates_tree
        tree.delete(*tree.get_children())
        for index, candidate in enumerate(self._media_candidates):
            dimensions = ""
            if candidate.width and candidate.height:
                dimensions = f" · {candidate.width}×{candidate.height}"
            tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    "Відео" if candidate.kind == "video" else "Фото",
                    candidate.source_label or "Джерело новини",
                    candidate.origin + dimensions,
                    candidate.url,
                ),
            )
        if self._media_candidates:
            tree.selection_set("0")
            tree.focus("0")

    def discover_current_group_media(self) -> None:
        group_id = getattr(self, "current_group_id", None)
        articles = list(getattr(self, "current_group_articles", []))
        if group_id is None:
            self.msg.showinfo("Медіа", "Спочатку відкрийте новину в редакторі.", parent=self.root)  # type: ignore[attr-defined]
            return
        self._media_discovery_group_id = group_id
        self.media_candidates_status_var.set(
            f"Перевіряю джерела: {len(articles)}. Це не змінює вже прикріплене медіа."
        )

        def success(result: object) -> None:
            if self.current_group_id != group_id:  # type: ignore[attr-defined]
                return
            candidates = list(result) if isinstance(result, list) else []
            self._set_media_candidates(candidates)
            if candidates:
                self.media_candidates_status_var.set(
                    f"Знайдено медіафайлів: {len(candidates)}. Виберіть один і натисніть «Використати вибране»."
                )
            else:
                self.media_candidates_status_var.set(
                    "У джерелах не знайдено придатного медіа. Додайте файл із комп’ютера або за посиланням."
                )

        self.run_async(  # type: ignore[attr-defined]
            lambda: discover_group_media(articles),
            success,
            label=f"Шукаю медіа для блоку #{group_id}",
            done_label="Пошук медіа завершено",
        )

    def _selected_media_candidate(self) -> MediaCandidate | None:
        if not hasattr(self, "media_candidates_tree"):
            return None
        selection = self.media_candidates_tree.selection()
        if not selection:
            return None
        index = int(selection[0])
        if index < 0 or index >= len(self._media_candidates):
            return None
        return self._media_candidates[index]

    def _managed_drive_client(self) -> ManagedGoogleDriveClient:
        if not self.config.platform_ready("google_drive"):  # type: ignore[attr-defined]
            raise GoogleDriveError("Спочатку підключіть Google Drive у налаштуваннях.")
        return ManagedGoogleDriveClient(
            self.config.google_client_id,  # type: ignore[attr-defined]
            self.config.google_client_secret,  # type: ignore[attr-defined]
            self.config.google_refresh_token,  # type: ignore[attr-defined]
        )

    def _attach_uploaded_media(self, upload: ManagedMediaUpload) -> None:
        group_id = getattr(self, "current_group_id", None)
        if group_id is None:
            try:
                self._managed_drive_client().delete_file(upload.info.file_id)
            except GoogleDriveError:
                pass
            raise GoogleDriveError("Новину було закрито до завершення завантаження; файл видалено з Drive.")
        drive_url = f"https://drive.google.com/file/d/{upload.info.file_id}/view"
        try:
            self.db.set_group_media(  # type: ignore[attr-defined]
                group_id,
                drive_url=drive_url,
                file_id=upload.info.file_id,
                name=upload.info.name,
                kind=upload.info.kind,
                mime=upload.info.mime_type,
                size=upload.info.size,
            )
        except Exception:
            try:
                self._managed_drive_client().delete_file(upload.info.file_id)
            except GoogleDriveError:
                pass
            raise
        self.media_url_var.set(drive_url)  # type: ignore[attr-defined]
        self.media_status_var.set(  # type: ignore[attr-defined]
            f"Медіа готове ✓ {upload.info.name} · {upload.info.kind.upper()} · "
            f"{format_media_size(upload.info.size)} · Google Drive: перевірено ✓"
        )

    def _upload_media(self, media: ValidatedMedia, filename: str, *, label: str) -> None:
        group_id = getattr(self, "current_group_id", None)
        if group_id is None:
            self.msg.showinfo("Медіа", "Спочатку відкрийте новину в редакторі.", parent=self.root)  # type: ignore[attr-defined]
            return

        def action() -> object:
            client = self._managed_drive_client()
            return client.upload_validated_media(media, filename)

        def success(result: object) -> None:
            if not isinstance(result, ManagedMediaUpload):
                raise GoogleDriveError("Google Drive не повернув результат завантаження.")
            self._attach_uploaded_media(result)
            self.media_candidates_status_var.set("Вибраний файл автоматично додано й перевірено.")

        self.run_async(  # type: ignore[attr-defined]
            action,
            success,
            label=label,
            done_label="Медіафайл додано",
        )

    def use_selected_media_candidate(self) -> None:
        candidate = self._selected_media_candidate()
        if candidate is None:
            self.msg.showinfo("Медіа", "Оберіть файл у списку знайдених медіа.", parent=self.root)  # type: ignore[attr-defined]
            return

        def action() -> object:
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

        self.run_async(  # type: ignore[attr-defined]
            action,
            success,
            label="Завантажую вибране медіа й додаю в Google Drive",
            done_label="Вибране медіа готове",
        )

    def add_media_from_computer(self) -> None:
        selected = self.files.askopenfilename(  # type: ignore[attr-defined]
            parent=self.root,  # type: ignore[attr-defined]
            title="Оберіть фото або відео",
            filetypes=[
                ("Фото й відео", "*.jpg *.jpeg *.png *.gif *.webp *.mp4 *.webm"),
                ("Усі файли", "*.*"),
            ],
        )
        if not selected:
            return
        try:
            media, filename = validate_local_media(Path(selected))
        except (GoogleDriveError, MediaCandidateError) as exc:
            self._show_error(exc)  # type: ignore[attr-defined]
            return
        self._upload_media(media, filename, label="Перевіряю локальний файл і додаю в Google Drive")

    def add_media_by_url(self) -> None:
        value = simpledialog.askstring(
            "Додати медіа за посиланням",
            "Вставте пряме посилання на фото/відео або адресу вебсторінки:",
            parent=self.root,  # type: ignore[attr-defined]
        )
        if not value:
            return

        def action() -> object:
            return resolve_manual_media_url(value.strip())

        def success(result: object) -> None:
            media, candidates = result  # type: ignore[misc]
            if isinstance(media, ValidatedMedia):
                filename = media_filename_from_url(media.source_url or value, media.mime_type)
                self._upload_media(
                    media,
                    filename,
                    label="Додаю медіафайл за посиланням у Google Drive",
                )
                return
            found = list(candidates) if isinstance(candidates, list) else []
            self._set_media_candidates(found)
            self.media_candidates_status_var.set(
                f"На сторінці знайдено медіафайлів: {len(found)}. Оберіть потрібний."
            )

        self.run_async(  # type: ignore[attr-defined]
            action,
            success,
            label="Перевіряю посилання й шукаю медіа",
            done_label="Посилання перевірено",
        )
