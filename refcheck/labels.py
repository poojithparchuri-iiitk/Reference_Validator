"""
labels.py -- plain words for where a reference was found and what kind of record it is.
"""

_KINDS = {
    "journal-article": "journal article", "journalarticle": "journal article", "article": "article",
    "proceedings-article": "conference paper", "conferencepaper": "conference paper",
    "posted-content": "preprint", "preprint": "preprint",
    "book": "book", "monograph": "book", "edited-book": "book", "reference-book": "book", "textbook": "book",
    "book-chapter": "book chapter", "bookchapter": "book chapter", "book-section": "book chapter", "book-part": "book chapter",
    "report": "report", "report-component": "report", "dissertation": "thesis",
    "dataset": "dataset", "software": "software", "standard": "standard", "peer-review": "peer review",
    "proceedings": "proceedings volume", "conferenceproceeding": "proceedings volume",
    "journal": "journal", "journal-issue": "journal issue", "journal-volume": "journal volume",
    "reference-entry": "reference entry", "text": "text", "other": "other",
}


def found_in(source):
    """'arXiv', 'DOI registry (CrossRef)', 'CrossRef', 'OpenAlex' ... from the pipeline's source text."""
    source = source or ""
    if source.startswith("arXiv"):
        return "arXiv"
    if source.startswith("DOI"):
        inside = source[source.find("(") + 1:source.rfind(")")] if "(" in source else ""
        return f"DOI via {inside}" if inside and inside != "lookup" else "DOI registry"
    if source.startswith("CrossRef"):
        return "CrossRef"
    if source.startswith("OpenAlex"):
        return "OpenAlex"
    return source


def record_kind(record_type, source=""):
    """'journal article', 'conference paper', 'book', 'preprint' ... ('' when the record does not say)."""
    if record_type:
        key = str(record_type).lower()
        return _KINDS.get(key, key.replace("-", " "))
    return "preprint" if (source or "").startswith("arXiv") else ""