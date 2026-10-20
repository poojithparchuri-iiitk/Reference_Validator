"""
titles.py -- guess the title of a single paper from its first page.

Two sources: (1) the PDF's own metadata, if it looks like a real title, and
(2) the text with the largest font size on page 1.
"""
import re

_BAD_METADATA = re.compile(r'(\.pdf|\.tex|\.docx?|\.dvi)$|^microsoft word|^untitled|^arxiv', re.IGNORECASE)


def _plausible(title):
    title = (title or "").strip()
    return len(title) >= 12 and len(title.split()) >= 3 and not _BAD_METADATA.search(title)


def title_from_metadata(doc):
    return (doc.metadata or {}).get("title", "").strip()


def title_from_largest_text(doc, page_index=0):
    """Join the consecutive lines on a page (the first by default) that use the largest font size."""
    if len(doc) == 0:
        return ""
    data = doc[page_index].get_text("dict")
    lines = []
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            spans = [s for s in line["spans"] if s["text"].strip()]
            if spans:
                size = max(s["size"] for s in spans)
                text = " ".join(s["text"].strip() for s in spans)
                lines.append((line["bbox"][1], size, text))
    # ignore arXiv date stamps and similar banners -- they are often the biggest text on the page
    lines = [ln for ln in lines if not re.search(r'arxiv:\s?\d|^proceedings|©|^preprint', ln[2], re.IGNORECASE)]
    if not lines:
        return ""
    lines.sort()
    max_size = max(size for _, size, _ in lines)

    parts, prev_y = [], None
    for y, size, text in lines:
        if size >= max_size - 0.6:
            if prev_y is not None and y - prev_y > 2.5 * max_size:
                break
            parts.append(text)
            prev_y = y
        elif parts:
            break                      # a smaller line after the title ends it
    return re.sub(r'\s+', ' ', " ".join(parts)).strip()


def guess_title(doc):
    """Best title guess for a single-paper PDF (a pymupdf Document)."""
    meta = title_from_metadata(doc)
    if _plausible(meta):
        return meta
    return title_from_largest_text(doc) or "(title not found)"