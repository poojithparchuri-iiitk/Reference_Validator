"""
identifiers.py -- find an arXiv ID or a DOI written inside a reference.

An identifier is looked up EXACTLY (no guessing which paper is nearest), so it is the strongest
evidence a reference can carry -- and a wrong or invented identifier is easy to expose.
"""
import re

# arXiv: new style 2010.11929 (year+month, then 4-5 digits); old style quant-ph/0402148
_ARXIV_NEW = re.compile(r"(?<![\d.])(\d{2}(?:0[1-9]|1[0-2])\.\d{4,5})(?:v\d+)?(?!\d)")
_ARXIV_OLD = re.compile(r"arxiv(?:\.org)?\W{0,3}(?:abs/|pdf/)?((?:[a-z]+-)*[a-z]+(?:\.[a-z]{2})?/\d{7})(?:v\d+)?(?!\d)", re.IGNORECASE)
_ARXIV_DOI = re.compile(r"10\.48550/arxiv\.(\d{2}(?:0[1-9]|1[0-2])\.\d{4,5}|(?:[a-z]+-)*[a-z]+/\d{7})", re.IGNORECASE)

_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+)")


def _normalise_old(arxiv_id):
    """Old-style IDs are written archive-lowercase, subject-class-uppercase: cs.LG/0112017, quant-ph/0402148."""
    archive, _, number = arxiv_id.partition("/")
    name, dot, subject = archive.partition(".")
    return f"{name.lower()}{dot}{subject.upper()}/{number}"


def find_arxiv_id(text):
    """'arXiv:2010.11929', 'arxiv.org/abs/1706.03762v5', 'quant-ph/0402148' -> the ID without version, or None."""
    if not text:
        return None
    doi = _ARXIV_DOI.search(text)                      # arXiv's own DOIs: 10.48550/arXiv.2010.11929
    if doi:
        return _normalise_old(doi.group(1)) if "/" in doi.group(1) else doi.group(1)
    for match in _ARXIV_NEW.finditer(text):
        if "arxiv" in text[max(0, match.start() - 40):match.start()].lower():   # a bare 2010.11929 might be anything
            return match.group(1)
    old = _ARXIV_OLD.search(text)
    if old:
        return _normalise_old(old.group(1))
    return None


def find_doi(text):
    """The first DOI in the text, cleaned of trailing punctuation, or None. arXiv's own DOIs are left to find_arxiv_id."""
    if not text:
        return None
    for match in _DOI.finditer(text):
        doi = match.group(1).rstrip(".,;:)]}>\"'")
        if doi.lower().startswith("10.48550/arxiv."):
            continue
        suffix = doi.split("/", 1)[1] if "/" in doi else ""
        if len(doi) > 8 and re.search(r"\d", suffix):          # no digit at all: the DOI was cut off, do not look it up
            return doi
    return None