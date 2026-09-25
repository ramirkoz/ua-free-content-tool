from __future__ import annotations

from .publication_policy_v1_2_rc3 import compose_publication_text_rc3
from .publication_text import FUND_FOOTER


def compose_publication_text_rc4(
    core_text: str,
    platform: str,
    *,
    include_source_link: bool,
    source_url: str,
) -> str:
    text = compose_publication_text_rc3(
        core_text,
        platform,
        include_source_link=include_source_link,
        source_url=source_url,
    )
    if platform == "instagram" and FUND_FOOTER not in text:
        pieces = [str(core_text or "").strip(), FUND_FOOTER]
        if include_source_link and str(source_url or "").strip():
            pieces.append(f"Джерело: {str(source_url).strip()}")
        return "\n\n".join(piece for piece in pieces if piece)
    return text
