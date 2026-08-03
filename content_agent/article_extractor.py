from __future__ import annotations

from html.parser import HTMLParser


class _ArticleHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.skip_depth = 0
        self.preferred_depth = 0
        self.chunks: list[str] = []
        self.title_chunks: list[str] = []
        self.in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        self.depth += 1
        if tag in {"script", "style", "noscript", "svg", "nav", "footer", "form"}:
            self.skip_depth = self.depth
        if tag in {"article", "main"}:
            self.preferred_depth = self.depth
        if tag == "title":
            self.in_title = True
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3", "blockquote"}:
            self.chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self.in_title = False
        if self.skip_depth == self.depth:
            self.skip_depth = 0
        if self.preferred_depth == self.depth:
            self.preferred_depth = 0
        self.depth = max(0, self.depth - 1)

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        text = " ".join(data.split())
        if not text:
            return
        if self.in_title:
            self.title_chunks.append(text)
        self.chunks.append(text + " ")


def extract_article(html: str) -> tuple[str, str]:
    parser = _ArticleHTMLParser()
    parser.feed(html)
    text = "\n".join(
        line.strip()
        for line in "".join(parser.chunks).splitlines()
        if len(line.strip()) >= 2
    )
    title = " ".join(parser.title_chunks).strip()
    # Prevent navigation-heavy pages from flooding the local model.
    return title[:500], text[:120_000]
