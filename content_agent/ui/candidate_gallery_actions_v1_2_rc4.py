from __future__ import annotations
from ..google_drive import GoogleDriveError
from ..managed_media_drive import ManagedMediaUpload
from ..media_candidates import download_media_candidate
from .media_workflow import media_filename_from_url

class CandidateGalleryActionsMixin:
    def _selected_media_candidates_rc4(self):
        tree = getattr(self, "media_candidates_tree", None)
        if tree is None: return []
        result = []
        for iid in tree.selection():
            try: index = int(iid)
            except ValueError: continue
            if 0 <= index < len(self._media_candidates): result.append(self._media_candidates[index])
        return result

    def use_selected_media_candidate(self) -> None:
        candidates = self._selected_media_candidates_rc4()
        if not candidates: return super().use_selected_media_candidate()
        group_id = getattr(self, "current_group_id", None)
        if group_id is None:
            self.msg.showinfo("Медіа", "Спочатку відкрийте новину в редакторі.", parent=self.root); return
        if len(candidates) == 1: return super().use_selected_media_candidate()
        kinds = {candidate.kind for candidate in candidates}
        if len(kinds) != 1 or next(iter(kinds)) not in {"image", "video"}:
            self._show_error(GoogleDriveError("Оберіть кілька медіа одного типу: тільки фото або тільки відео.")); return
        if len(candidates) > 10:
            self._show_error(GoogleDriveError("До однієї публікації можна додати не більше 10 медіафайлів.")); return
        kind = next(iter(kinds)); attached = self._attachment_rows(group_id)
        if attached:
            attached_kind = "video" if attached[0].mime_type.casefold().startswith("video/") else "image"
            if attached_kind != kind:
                self._show_error(GoogleDriveError("Не можна змішувати фото й відео в одному наборі медіа.")); return
        if len(attached) + len(candidates) > 10:
            self._show_error(GoogleDriveError("До однієї публікації можна додати не більше 10 медіафайлів.")); return
        def action() -> object:
            client = self._managed_drive_client(); uploaded: list[ManagedMediaUpload] = []
            try:
                for candidate in candidates:
                    media = download_media_candidate(candidate)
                    uploaded.append(client.upload_validated_media(media, media_filename_from_url(media.source_url or candidate.url, media.mime_type)))
                return uploaded
            except Exception:
                for upload in uploaded:
                    try: client.delete_file(upload.info.file_id)
                    except GoogleDriveError: pass
                raise
        def success(result: object) -> None:
            uploads = list(result) if isinstance(result, list) else []
            self._commit_uploaded_media(uploads, group_id)
            self.media_candidates_status_var.set(f"Із джерел додано {'відео' if kind == 'video' else 'фото'}: {len(uploads)}.")
        self.run_async(action, success, label=f"Завантажую вибрані медіа з джерел: {len(candidates)}", done_label="Медіа з джерел додано")
