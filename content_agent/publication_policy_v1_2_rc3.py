from __future__ import annotations

from .publication_text import FUND_FOOTER

DONATION_COMMENT = FUND_FOOTER


def compose_publication_text_rc3(
    core_text: str,
    platform: str,
    *,
    include_source_link: bool,
    source_url: str,
) -> str:
    pieces = [str(core_text or "").strip()]
    if platform == "telegram":
        pieces.append(FUND_FOOTER)
    if include_source_link and str(source_url or "").strip():
        pieces.append(f"Джерело: {str(source_url).strip()}")
    return "\n\n".join(piece for piece in pieces if piece)
