"""Limited, inert extraction of visible text from an HTML page with BeautifulSoup.

Scripts, styles and embedded objects are removed; nothing is executed. The
output is plain text, later treated as *untrusted data* (never instructions).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from cyberlead360.utils.validators import clean_text

_STRIP_TAGS = (
    "script",
    "style",
    "noscript",
    "template",
    "iframe",
    "object",
    "embed",
    "svg",
    "form",
    "nav",
    "footer",
)


@dataclass
class ExtractedPage:
    title: str | None
    meta_description: str | None
    headings: list[str] = field(default_factory=list)
    paragraphs: list[str] = field(default_factory=list)


def extract_page(html: str, max_paragraphs: int = 12, max_chars: int = 600) -> ExtractedPage:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_STRIP_TAGS):
        tag.decompose()
    title = clean_text(soup.title.get_text(" ", strip=True), 300) if soup.title else None
    meta = soup.find("meta", attrs={"name": "description"})
    meta_desc = clean_text(str(meta.get("content", "")), 500) if meta else None
    headings = []
    for h in soup.find_all(["h1", "h2"])[:10]:
        text = clean_text(h.get_text(" ", strip=True), 200)
        if text:
            headings.append(text)
    paragraphs: list[str] = []
    for p in soup.find_all("p"):
        text = clean_text(p.get_text(" ", strip=True), max_chars)
        if text and len(text) >= 40:
            paragraphs.append(text)
        if len(paragraphs) >= max_paragraphs:
            break
    return ExtractedPage(title, meta_desc, headings, paragraphs)
