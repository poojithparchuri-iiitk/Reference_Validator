"""
splitter.py -- decide whether a PDF is one paper or a proceedings volume,
and cut a proceedings volume into papers using its bookmarks (outline).

ACL Anthology volumes carry one top-level bookmark per paper, which gives exact page ranges.
A PDF without such bookmarks is treated as a single paper.
"""
import re
import statistics
from collections import Counter
from dataclasses import dataclass

from refcheck.titles import guess_title, title_from_largest_text

# top-level bookmarks that are front/back matter, not papers
NON_PAPER_TITLES = {"program", "conference program", "contents", "table of contents", "preface",
                    "foreword", "index", "author index", "front matter", "cover", "title page",
                    "committees", "organizers", "sponsors", "keynote", "invited talks"}


# A bookmark whose WHOLE title is a section heading ("1 Introduction", "References") marks a section of one paper.
SECTION_TITLE = re.compile(
    r'^(?:\d+(?:\.\d+)*\.?\s+)?(?:abstract|introduction|background|related work|methods?|methodology|'
    r'approach|experiments?|evaluation|results|discussion|conclusions?|references|acknowledg(?:e)?ments?|appendix)\s*$',
    re.IGNORECASE)


@dataclass
class PaperSpan:
    index: int          # 0-based position in the volume
    title: str
    start_page: int     # 0-based, inclusive
    end_page: int       # 0-based, inclusive

    @property
    def n_pages(self):
        return self.end_page - self.start_page + 1


def bookmark_papers(doc):
    """Top-level bookmarks -> paper spans. Skips front matter and bookmarks that share a page."""
    entries = []
    for level, title, page in doc.get_toc():
        if level != 1 or page < 1:
            continue
        title = " ".join(title.split())
        if title.lower() in NON_PAPER_TITLES:
            continue
        entries.append((page - 1, title))          # get_toc pages are 1-based

    entries.sort(key=lambda e: e[0])
    unique, seen_pages = [], set()
    for page, title in entries:
        if page not in seen_pages:
            seen_pages.add(page)
            unique.append((page, title))

    spans = []
    for i, (page, title) in enumerate(unique):
        end = unique[i + 1][0] - 1 if i + 1 < len(unique) else len(doc) - 1
        spans.append(PaperSpan(i, title, page, max(end, page)))
    return spans


def looks_like_proceedings(doc):
    """
    Returns (is_proceedings, reason).
    A single paper can also have bookmarks (Introduction, Methods, ...), but those sections
    are only a page or two long. Papers in a volume are several pages long.
    """
    spans = bookmark_papers(doc)
    if len(spans) < 3:
        return False, f"only {len(spans)} usable top-level bookmark(s)"
    section_like = sum(1 for s in spans if SECTION_TITLE.match(s.title)) / len(spans)
    if section_like >= 0.3:
        return False, f"{len(spans)} bookmarks but {section_like:.0%} are section headings (Introduction, References, ...)"
    median_pages = statistics.median(s.n_pages for s in spans)
    if median_pages < 4:
        return False, f"{len(spans)} bookmarks but they average only {median_pages:g} pages (looks like sections)"
    return True, f"{len(spans)} bookmarked papers, median {median_pages:g} pages each"


MAX_PAGES_FOR_LAYOUT = 800          # the layout scan reads every page; skip it for giant files


def _body_font_size(doc):
    """The most common font size, weighted by the number of characters (= the size of the running text)."""
    weight = Counter()
    for page in doc:
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    weight[round(span["size"], 1)] += len(span["text"].strip())
    return weight.most_common(1)[0][0] if weight else 10.0


def _is_title_page(page, body_size):
    """
    A first page looks like this: the biggest text on the page is clearly bigger than the running text and sits near
    the top (the title), and the word "Abstract" follows soon after.
    """
    data = page.get_text("dict")
    biggest, y_of_biggest = 0.0, 0.0
    for block in data["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                if span["text"].strip() and span["size"] > biggest:
                    biggest, y_of_biggest = span["size"], span["bbox"][1]
    if biggest < 1.15 * body_size or y_of_biggest > 0.35 * page.rect.height:
        return False
    text = page.get_text()
    match = re.search(r"\bAbstract\b|\bABSTRACT\b", text)
    return bool(match) and match.start() < 0.30 * max(1, len(text))


def layout_papers(doc):
    """
    For a PDF WITHOUT bookmarks (for example one that was cut out of a proceedings volume and lost its outline):
    find where each paper starts by recognising title pages. Returns a list of PaperSpan, or [] when fewer than two
    papers are recognised. The number of papers is never guessed from page counts: every start is a real title page.
    """
    if len(doc) < 4 or len(doc) > MAX_PAGES_FOR_LAYOUT:
        return []
    body = _body_font_size(doc)
    starts = [i for i in range(len(doc)) if _is_title_page(doc[i], body)]
    if len(starts) < 2:
        return []
    if starts[0] != 0:
        starts.insert(0, 0)                       # pages before the first title page belong to a paper whose start was cut off
    lengths = [b - a for a, b in zip(starts, starts[1:] + [len(doc)])]
    if statistics.median(lengths) < 3:            # papers are several pages long; a median under 3 means false alarms
        return []
    spans = []
    for number, start in enumerate(starts):
        end = (starts[number + 1] - 1) if number + 1 < len(starts) else len(doc) - 1
        spans.append(PaperSpan(number, title_from_largest_text(doc, start) or "(title not found)", start, end))
    return spans


def split_papers(doc, mode="auto"):
    """
    mode: "auto", "single" or "multi".
    Returns (spans, mode_used, reason).
    """
    if mode == "auto":
        is_multi, reason = looks_like_proceedings(doc)
        mode = "multi" if is_multi else "single"
        if mode == "single" and not doc.get_toc():                 # no bookmarks at all: try the page layout
            laid_out = layout_papers(doc)
            if laid_out:
                return laid_out, "multi", f"no bookmarks; {len(laid_out)} papers recognised by the layout of their first pages"
    elif mode == "multi":
        reason = "chosen by user"
        if not bookmark_papers(doc):
            laid_out = layout_papers(doc)
            if laid_out:
                return laid_out, "multi", f"no bookmarks; {len(laid_out)} papers recognised by the layout of their first pages"
            return ([PaperSpan(0, guess_title(doc), 0, len(doc) - 1)], "single",
                    "multi was requested but no papers could be recognised -- treated as one paper")
    else:
        reason = "chosen by user"

    if mode == "multi":
        return bookmark_papers(doc), "multi", reason
    return [PaperSpan(0, guess_title(doc), 0, len(doc) - 1)], "single", reason


def strip_running_lines(pages):
    """
    Remove page headers and footers: a line that appears (apart from its digits) on at least half of the
    pages is not content. Without this, "PLOS ONE ... doi.org/10.1371/... 17 / 18" ends up inside the
    last reference of every page, and the paper's own DOI is mistaken for a reference's DOI.
    """
    if len(pages) < 4:
        return pages

    def shape(line):
        return re.sub(r"\d+", "#", " ".join(line.split()))

    counts = Counter()
    for text in pages:
        counts.update({shape(line) for line in text.splitlines() if line.strip() and len(line) < 200})
    repeated = {shape_ for shape_, n in counts.items() if n >= max(3, len(pages) / 2)}
    return ["\n".join(line for line in text.splitlines() if shape(line) not in repeated) for text in pages]


def paper_text(doc, span):
    """Raw text of the pages that belong to one paper, without running headers and footers."""
    pages = [doc[p].get_text() for p in range(span.start_page, span.end_page + 1)]
    return "\n".join(strip_running_lines(pages))