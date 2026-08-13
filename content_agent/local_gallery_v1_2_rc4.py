from __future__ import annotations

from pathlib import Path

from .google_drive import GoogleDriveError
from .managed_media_drive import validate_local_media


def prepare_local_gallery(paths: list[Path]) -> list[tuple[object, str]]:
    prepared = [validate_local_media(path) for path in paths]
    if not prepared:
        return []
    kinds = {getattr(media, "kind", "") for media, _name in prepared}
    if len(prepared) > 1 and kinds != {"image"}:
        raise GoogleDriveError("Кілька медіафайлів можна додавати тільки як фотогалерею.")
    return prepared
