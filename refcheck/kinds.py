"""
kinds.py -- what kind of thing is a reference that no database knows?  A guess from its wording, for explaining
"not found": a web page, a book, a thesis, a report or documentation, software -- or (empty) probably a paper.
"""
import re

_RULES = [                        # the first rule that matches wins
    ("thesis", r"\bph\.?\s?d\b|\bthesis\b|\bdissertation\b|\bdoctoral\b|master'?s\b|\btesis\b|trabajo (?:de|fin)|bachelor"),
    ("software or dataset", r"github\.com|gitlab\.com|pypi\.org|huggingface\.co|zenodo\.org|\bpython package\b"),
    ("report or documentation", r"technical report|tech\.? rep|white ?paper|documentation|\bmanual\b|user guide|\bdatasheet\b|model card|\binforme\b|\bguidelines?\b"),
    ("book", r"\bisbn\b|university press|\bmit press\b|\bpress\b.{0,40}\b(?:new york|london|cambridge|oxford)\b|"
             r"\bwiley\b|o'reilly|pearson|mcgraw|\bedition\b|\btextbook\b|\bhandbook\b|\b\d+(?:st|nd|rd|th) ed"),
    ("web page", r"https?://|www\.|\baccessed\b|\bretrieved\b|\bavailable (?:at|online)\b|\[online\]|\bblog\b|\bwebsite\b"),
]
_COMPILED = [(name, re.compile(pattern, re.IGNORECASE)) for name, pattern in _RULES]
# links to where PAPERS live say nothing about the kind of reference
_PAPER_LINKS = re.compile(r"https?://(?:dx\.)?doi\.org/\s*\S+|https?://(?:www\.)?arxiv\.org/\S+|https?://aclanthology\.org/\S+|"
                          r"https?://ieeexplore\S+|https?://dl\.acm\.org/\S+|https?://link\.springer\.com/\S+|"
                          r"https?://openreview\.net/\S+|https?://proceedings\.\S+|https?://papers\.\S+|https?://www\.nature\.com/\S+|"
                          r"https?://journals\.aps\.org/\S+|https?://www\.science\.org/\S+|https?://(?:\w+\.)?semanticscholar\.org/\S+",
                          re.IGNORECASE)


def reference_kind(text):
    """'thesis', 'software or dataset', 'report or documentation', 'book', 'web page', or '' (probably a paper)."""
    text = _PAPER_LINKS.sub(" ", text or "")
    for name, pattern in _COMPILED:
        if pattern.search(text):
            if name == "web page" and re.search(r"arxiv|doi\.org|\bdoi\b", text, re.IGNORECASE):   # it carries a paper identifier
                continue
            return name
    return ""