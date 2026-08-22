from __future__ import annotations

from ..google_drive import GoogleDriveError
from ..managed_media_drive import ManagedMediaUpload
from ..media_candidates import download_media_candidate
from .media_workflow import media_filename_from_url


class CandidateGalleryActionsMixin:
    def _selected_media_candidates_rc4(self):
        tree = getattr(self, "media_candidates_tree", None)
        if tree is None:
            return []
        result = []
        for iid in tree.selection():
            try:
                index = int(iid)
            except ValueError:
                continue
            if 0 <= index < len(self._media_candidates):
                result.append(self._media_candidates[index])
        return result

    def use_selected_media_candidate(self) -> None:
        candidates = self._selected_media_candidates_rc4()
        if not candidates:
            return super().use_selected_media_candidate()  # type: ignore[misc]
        group_id = getattr(self, "current_group_id", None)
        if group_id is None:
            self.msg.showinfo("Медіа", "Спочатку відкрийте новину в редакторі.", parent=self.root)
            return
        if len(candidates) == 1 and candidates[0].kind == "video":
            if self._attachment_rows(group_id):
                self._show_error(GoogleDriveError("Відео може бути лише єдиним медіафайлом. Спочатку приберіть фото."))
                return
            return super().use_selected_media_candidate()  # type: ignore[misc]
        if any(candidate.kind != "image" for candidate in candidates):
            self._show_error(GoogleDriveError("Кілька медіафайлів можна додавати тільки як фотогалерею."))
            return
        if len(self._attachment_rows(group_id)) + len(candidates) > 10:
            self._show_error(GoogleDriveError("До однієї публікації можна додати не більше 10 фото."))
            return

        def action() -> object:
            client = self._managed_drive_client()
            uploaded: list[ManagedMediaUpload] = []
            try:
                for candidate in candidates:
                    media = download_media_candidate(candidate)
                    filename = media_filename_from_url(media.source_url or candidate.url, media.mime_type)
                    uploaded.append(client.upload_validated_media(media, filename))
                return uploaded
            except Exception:
                for upload in uploaded:
                    try:
                        client.delete_file(upload.info.file_id)
                    except GoogleDriveError:
                        pass
                raise

        def success(result: object) -> None:
            uploads = list(result) if isinstance(result, list) else []
            self._commit_uploaded_images(uploads, group_id)
            self.media_candidates_status_var.set(f"Із джерел додано фото: {len(uploads)}.")

        self.run_async(
            action,
            success,
            label=f"Завантажую вибрані фото з джерел: {len(candidates)}",
            done_label="Фото з джерел додано",
        )
