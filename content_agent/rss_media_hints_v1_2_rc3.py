from __future__ import annotations

import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

from .media_candidates import MediaCandidate

_VIDEO_EXT = (".mp4", ".webm", ".mov", ".m4v")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _kind(url: str, mime: str, fallback: str) -> str:
    clean = str(mime or "").split(";", 1)[0].casefold()
    path = urlsplit(str(url or "")).path.casefold()
    if clean.startswith("video/") or path.endswith(_VIDEO_EXT):
        return "video"
    return "image" if clean.startswith("image/") else fallback


def rss_media_hints(xml_bytes: bytes, source_label: str) -> dict[str, list[MediaCandidate]]:
    """Read RSS/Atom enclosure and Media RSS entries while the feed is fresh."""

    result: dict[str, list[MediaCandidate]] = {}
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return result
    for item in root.iter():
        if _local_name(item.tag) not in {"item", "entry"}:
            continue
        link = ""
        guid = ""
        for child in list(item):
            name = _local_name(child.tag)
            if name == "link" and not link:
                link = str(child.attrib.get("href") or child.text or "").strip()
            elif name in {"guid", "id"} and not guid:
                guid = str(child.text or "").strip()
        key = link or guid
        if not key:
            continue
        found: list[MediaCandidate] = []
        for child in item.iter():
            name = _local_name(child.tag)
            if name not in {"enclosure", "content", "thumbnail", "image"}:
                continue
            url = str(child.attrib.get("url") or child.attrib.get("href") or "").strip()
            if not url.startswith(("http://", "https://")):
                continue
            mime = str(child.attrib.get("type") or "")
            fallback = "image" if name in {"thumbnail", "image"} else ("video" if mime.casefold().startswith("video/") else "image")
            kind = _kind(url, mime, fallback)
            found.append(
                MediaCandidate(
                    url=url,
                    kind=kind,
                    source_label=source_label,
                    origin=f"rss:{name}",
                    mime_hint=mime.split(";", 1)[0].casefold(),
                    score=160 if kind == "video" else 130,
                )
            )
        if found:
            result[key] = found
    return result
