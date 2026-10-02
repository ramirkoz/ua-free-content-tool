from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..media_rc56 import Rc56ManagedGoogleDriveClient
from ...google_drive import GoogleDriveError
from ...managed_media_drive import ManagedMediaUpload
from ...media_candidates import download_media_candidate
from ...media_discovery_v1_2_rc3 import discover_group_media_rc3
from ...ui.media_workflow import MediaWorkflowMixin, media_filename_from_url

from .components import FilterBar, PublicationStatus, StatusBar
from .legacy_manual_topics_window_rc44 import MainWindow as LegacyStableMainWindow
from .manual_topics_window import ALL_SOURCES, ALL_TOPICS
from .tabs.data_backups import DataBackupsTabController
from .tabs.inbox import InboxTabController
from .tabs.platforms import PlatformsTabController


class MainWindow(LegacyStableMainWindow):
    """Canonical V2 shell composed from shared controls and tab controllers."""

    def _replace_ollama_settings_panel(self) -> None:
        """RC56: AI configuration lives only in the dedicated AI tab."""
        stack = list(getattr(self, "notebook", self.root).winfo_children())
        while stack:
            widget = stack.pop()
            if isinstance(widget, ttk.LabelFrame):
                try:
                    label = str(widget.cget("text") or "")
                except tk.TclError:
                    label = ""
                if label.startswith("1. Ollama") or label.startswith("1. AI Router"):
                    try:
                        widget.destroy()
                    except tk.TclError:
                        pass
                    return
            try:
                stack.extend(widget.winfo_children())
            except tk.TclError:
                pass

    def _current_media_title(self) -> str:
        """Return the publication headline/context used for human-readable media names."""
        group_id = int(getattr(self, "current_group_id", 0) or 0)
        if group_id:
            try:
                group = self.db.get_group(group_id)
            except Exception:
                group = None
            if group is not None:
                for key in ("headline", "canonical_title", "title"):
                    try:
                        value = getattr(group, key, "")
                    except Exception:
                        value = ""
                    if not value:
                        try:
                            value = group[key]
                        except Exception:
                            value = ""
                    if str(value or "").strip():
                        return str(value).strip()
        for article in list(getattr(self, "current_group_articles", [])):
            value = str(getattr(article, "title", "") or "").strip()
            if value:
                return value
        return ""

    def _managed_drive_client(self) -> Rc56ManagedGoogleDriveClient:
        if not self.config.platform_ready("google_drive"):
            raise GoogleDriveError("Спочатку підключіть Google Drive у налаштуваннях.")
        return Rc56ManagedGoogleDriveClient(
            self.config.google_client_id,
            self.config.google_client_secret,
            self.config.google_refresh_token,
            post_title=self._current_media_title(),
            group_id=int(getattr(self, "current_group_id", 0) or 0),
        )

    def _upgrade_media_editor(self) -> None:
        super()._upgrade_media_editor()
        tree = getattr(self, "media_candidates_tree", None)
        if tree is None or hasattr(self, "_rc56_media_progress"):
            return
        frame = tree.master
        progress = ttk.Progressbar(frame, mode="indeterminate")
        progress.grid(row=3, column=0, columnspan=6, sticky="ew", pady=(2, 4))
        self._rc56_media_progress = progress
        self._rc59_media_busy_count = 0

    def _begin_media_busy(self) -> None:
        progress = getattr(self, "_rc56_media_progress", None)
        if progress is None:
            return
        count = int(getattr(self, "_rc59_media_busy_count", 0) or 0) + 1
        self._rc59_media_busy_count = count
        if count == 1:
            progress.configure(value=0)
            progress.start(12)
            try:
                progress.update_idletasks()
            except Exception:
                pass

    def _finish_media_busy(self) -> None:
        progress = getattr(self, "_rc56_media_progress", None)
        if progress is None:
            return
        count = max(0, int(getattr(self, "_rc59_media_busy_count", 0) or 0) - 1)
        self._rc59_media_busy_count = count
        if count == 0:
            progress.stop()
            try:
                progress.configure(value=0)
            except Exception:
                pass

    def load_group(self, group_id: int) -> None:
        """RC60: opening an item must not silently start a media scan.

        The operator now starts source discovery explicitly with the button. This
        makes the progress indicator mean actual requested media work instead of
        background activity triggered merely by opening a material.
        """
        super(MediaWorkflowMixin, self).load_group(group_id)
        self._media_discovery_group_id = group_id
        self._set_media_candidates([])
        if hasattr(self, "media_candidates_status_var"):
            self.media_candidates_status_var.set(
                "Натисніть «Знайти медіа в джерелах», щоб перевірити фото й відео для цього матеріалу."
            )

    def discover_current_group_media(self) -> None:
        group_id = getattr(self, "current_group_id", None)
        articles = list(getattr(self, "current_group_articles", []))
        if group_id is None:
            self.msg.showinfo("Медіа", "Спочатку відкрийте новину в редакторі.", parent=self.root)
            return
        self._media_discovery_group_id = group_id
        self.media_candidates_status_var.set(
            f"Перевіряю джерела: {len(articles)}. Це не змінює вже прикріплене медіа."
        )
        self._begin_media_busy()

        def action() -> object:
            try:
                return discover_group_media_rc3(articles)
            finally:
                self._post_ui(self._finish_media_busy)

        def success(result: object) -> None:
            if self.current_group_id != group_id:
                return
            candidates = list(result) if isinstance(result, list) else []
            self._set_media_candidates(candidates)
            if candidates:
                self.media_candidates_status_var.set(
                    f"Знайдено медіафайлів: {len(candidates)}. Виберіть потрібне медіа та натисніть «Використати вибране»."
                )
            else:
                self.media_candidates_status_var.set(
                    "У джерелах не знайдено придатного медіа. Додайте файл із комп’ютера або за посиланням."
                )

        self.run_async(action, success, label=f"Шукаю медіа для блоку #{group_id}", done_label="Пошук медіа завершено")

    def use_selected_media_candidate(self) -> None:
        candidates = []
        selected_many = getattr(self, "_selected_media_candidates_rc4", None)
        if callable(selected_many):
            candidates = list(selected_many())
        if not candidates:
            single = getattr(self, "_selected_media_candidate", None)
            candidate = single() if callable(single) else None
            if candidate is not None:
                candidates = [candidate]
        if not candidates:
            self.msg.showinfo("Медіа", "Оберіть файл у списку знайдених медіа.", parent=self.root)
            return

        group_id = getattr(self, "current_group_id", None)
        if group_id is None:
            self.msg.showinfo("Медіа", "Спочатку відкрийте новину в редакторі.", parent=self.root)
            return
        kinds = {candidate.kind for candidate in candidates}
        if len(kinds) != 1 or next(iter(kinds)) not in {"image", "video"}:
            self._show_error(GoogleDriveError("Оберіть медіа одного типу: тільки фото або тільки відео."))
            return
        if len(candidates) > 10:
            self._show_error(GoogleDriveError("До однієї публікації можна додати не більше 10 медіафайлів."))
            return

        kind = next(iter(kinds))
        attached = self._attachment_rows(group_id) if len(candidates) > 1 else []
        if attached:
            attached_kind = "video" if attached[0].mime_type.casefold().startswith("video/") else "image"
            if attached_kind != kind:
                self._show_error(GoogleDriveError("Не можна змішувати фото й відео в одному наборі медіа."))
                return
        if len(attached) + len(candidates) > 10:
            self._show_error(GoogleDriveError("До однієї публікації можна додати не більше 10 медіафайлів."))
            return

        self.media_candidates_status_var.set(
            f"Завантажую {'відео' if kind == 'video' else 'фото'}: {len(candidates)}."
        )
        self._begin_media_busy()

        def action() -> object:
            client = self._managed_drive_client()
            uploaded: list[ManagedMediaUpload] = []
            try:
                for candidate in candidates:
                    media = download_media_candidate(candidate)
                    uploaded.append(
                        client.upload_validated_media(
                            media,
                            media_filename_from_url(media.source_url or candidate.url, media.mime_type),
                        )
                    )
                return uploaded
            except Exception:
                for upload in uploaded:
                    try:
                        client.delete_file(upload.info.file_id)
                    except GoogleDriveError:
                        pass
                raise
            finally:
                self._post_ui(self._finish_media_busy)

        def success(result: object) -> None:
            uploads = list(result) if isinstance(result, list) else []
            if not uploads:
                raise GoogleDriveError("Google Drive не повернув результат завантаження.")
            if len(uploads) == 1:
                self._attach_uploaded_media(uploads[0])
            else:
                self._commit_uploaded_media(uploads, group_id)
            self.media_candidates_status_var.set(
                f"Додано {'відео' if kind == 'video' else 'фото'}: {len(uploads)}."
            )

        self.run_async(
            action,
            success,
            label=f"Завантажую вибрані медіа з джерел: {len(candidates)}",
            done_label="Медіа з джерел додано",
        )

    def _upload_media(self, media, filename: str, *, label: str) -> None:
        group_id = getattr(self, "current_group_id", None)
        if group_id is None:
            self.msg.showinfo("Медіа", "Спочатку відкрийте новину в редакторі.", parent=self.root)
            return
        self.media_candidates_status_var.set("Завантажую медіафайл у Google Drive…")
        self._begin_media_busy()

        def action() -> object:
            try:
                return self._managed_drive_client().upload_validated_media(media, filename)
            finally:
                self._post_ui(self._finish_media_busy)

        def success(result: object) -> None:
            if not isinstance(result, ManagedMediaUpload):
                raise GoogleDriveError("Google Drive не повернув результат завантаження.")
            self._attach_uploaded_media(result)
            self.media_candidates_status_var.set("Вибраний файл автоматично додано й перевірено.")

        self.run_async(action, success, label=label, done_label="Медіафайл додано")

    ALL_SOURCES_LABEL = ALL_SOURCES
    ALL_TOPICS_LABEL = ALL_TOPICS

    def __init__(self, root, database_or_services, config=None) -> None:
        self._inbox_controller: InboxTabController | None = None
        self._platforms_controller: PlatformsTabController | None = None
        self._data_controller: DataBackupsTabController | None = None
        super().__init__(root, database_or_services, config)
        self._apply_rc55_inbox_cleanup()
        self._apply_rc54_dpi_layout()
        self._inbox_controller = InboxTabController(self, self._rc53_filter_bar)
        self._inbox_controller.refresh_choices()
        self._platforms_controller = PlatformsTabController(self)
        self._data_controller = DataBackupsTabController(self)
        self._rename_system_tab()
        self._apply_rc54_publication_layout()
        self.refresh_groups()

    def _apply_rc55_inbox_cleanup(self) -> None:
        """Remove obsolete Inbox controls and lock the operator-visible column contract."""
        old_search = getattr(self, "_rc14_keyword_entry", None)
        if old_search is not None:
            try:
                old_search.destroy()
            except tk.TclError:
                pass
        tree = getattr(self, "groups_tree", None)
        if tree is not None:
            try:
                tree.configure(displaycolumns=("title", "topic", "sources", "published"))
            except tk.TclError:
                pass
        for widget in tuple(self._rc48_walk(self.root)):
            if widget is getattr(self, "_rc53_filter_bar", None):
                continue
            try:
                text = str(widget.cget("text") or "").strip()
            except Exception:
                continue
            if text in {"Пошук у Вхідних:", "Знайти", "Колонки", "Відновити стандартні колонки"}:
                try:
                    widget.destroy()
                except tk.TclError:
                    pass

    def _install_manual_topic_inbox_filters(self) -> None:
        if hasattr(self, "_rc53_filter_bar"):
            return
        tree = getattr(self, "groups_tree", None)
        if tree is None:
            return
        tree_frame = tree.master
        tab = tree_frame.master
        self.inbox_source_filter_var = tk.StringVar(master=self.root, value=ALL_SOURCES)
        self.inbox_topic_filter_var = tk.StringVar(master=self.root, value=ALL_TOPICS)
        self.inbox_search_var = tk.StringVar(master=self.root, value="")
        bar = FilterBar(
            tab,
            source_var=self.inbox_source_filter_var,
            topic_var=self.inbox_topic_filter_var,
            search_var=self.inbox_search_var,
            on_change=self.refresh_groups,
            on_reset=self.reset_manual_topic_filters,
            all_sources=ALL_SOURCES,
            all_topics=ALL_TOPICS,
        )
        bar.pack(fill="x", pady=(0, 6), before=tree_frame)
        self._manual_topic_filter_bar = bar
        self._rc53_filter_bar = bar
        self.inbox_source_filter_box = bar.source_box
        self.inbox_topic_filter_box = bar.topic_box
        old_search = getattr(self, "_rc14_keyword_entry", None)
        if old_search is not None:
            try:
                old_search.grid_remove()
            except tk.TclError:
                try:
                    old_search.pack_forget()
                except tk.TclError:
                    pass
        self._refresh_inbox_filter_choices()

    def _refresh_inbox_filter_choices(self) -> None:
        controller = getattr(self, "_inbox_controller", None)
        if controller is not None:
            controller.refresh_choices()
            return
        if not hasattr(self, "inbox_source_filter_box"):
            return
        source_rows = self.db.source_topic_rows()
        source_labels: list[str] = []
        source_map: dict[str, int] = {}
        for row in source_rows:
            label = f"{str(row['name'])} [#{int(row['id'])}]"
            source_labels.append(label)
            source_map[label] = int(row["id"])
        topic_rows = self.db.list_manual_topics()
        topic_labels = [str(row["name"]) for row in topic_rows]
        topic_map = {str(row["name"]): int(row["id"]) for row in topic_rows}
        self._inbox_source_label_to_id = source_map
        self._inbox_topic_label_to_id = topic_map
        self._rc53_filter_bar.set_choices(
            sources=(ALL_SOURCES, *source_labels),
            topics=(ALL_TOPICS, *topic_labels),
        )

    def reset_manual_topic_filters(self) -> None:
        controller = getattr(self, "_inbox_controller", None)
        if controller is not None:
            controller.reset()
            return
        self.inbox_source_filter_var.set(ALL_SOURCES)
        self.inbox_topic_filter_var.set(ALL_TOPICS)
        if hasattr(self, "inbox_search_var"):
            self.inbox_search_var.set("")
        self.refresh_groups()

    def _active_inbox_source_id(self) -> int | None:
        return getattr(self, "_inbox_source_label_to_id", {}).get(
            str(getattr(self, "inbox_source_filter_var", tk.StringVar(master=self.root)).get() or "")
        )

    def _active_inbox_topic_id(self) -> int | None:
        return getattr(self, "_inbox_topic_label_to_id", {}).get(
            str(getattr(self, "inbox_topic_filter_var", tk.StringVar(master=self.root)).get() or "")
        )

    def refresh_groups(self) -> None:
        controller = getattr(self, "_inbox_controller", None)
        if controller is None:
            return super().refresh_groups()
        controller.refresh()

    def _apply_rc48_shell_layout(self) -> None:
        super()._apply_rc48_shell_layout()
        old = getattr(self, "_rc48_status_bar", None)
        if old is not None:
            try:
                old.destroy()
            except tk.TclError:
                pass
        bar = StatusBar(self.root, operation_var=self.operation_var, status_var=self.status_var)
        bar.pack(side="bottom", fill="x")
        self._rc48_status_bar = bar
        self.operation_progress = bar.progress

    def _apply_rc54_dpi_layout(self) -> None:
        try:
            pixels_per_inch = float(self.root.winfo_fpixels("1i"))
            scaling = max(1.0, min(2.5, pixels_per_inch / 72.0))
            self.root.tk.call("tk", "scaling", scaling)
            self._rc54_tk_scaling = scaling
        except Exception:
            self._rc54_tk_scaling = 1.0
