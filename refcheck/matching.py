"""
matching.py -- does the record CrossRef returned look like the reference we asked about?

CrossRef always answers with its NEAREST record, so "a record came back" proves nothing.
We compare the record's title with the reference text:

    similarity >= 0.90   the titles agree             -> match   (still compared on year)
    0.65 - 0.90          the titles only partly agree -> check   (a person should look)
    < 0.65               different title              -> different

The two cut-offs come from reading real pairs: on 2,500 random references from the COLING data,
every pair above 0.90 that was read was the same paper, almost every pair below 0.65 was a
different paper, and the band in between was mixed.
"""
import difflib
import re
import unicodedata

MATCH_AT = 0.90
CHECK_AT = 0.65

_WORD = re.compile(r"[a-z0-9]+")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")


def _tokens(text):
    return _WORD.findall(text.lower())


def title_similarity(reference_text, crossref_title):
    """
    0..1: how well the CrossRef title is contained in the reference text.
    The title is slid along the reference (windows of about the same number of words)
    and the best word-level match wins, so authors and venue around the title do not matter.
    """
    t, r = _tokens(crossref_title or ""), _tokens(reference_text or "")
    if not t or not r:
        return 0.0
    if "".join(t) in "".join(r):            # same words; only spacing or punctuation differs
        return 1.0
    best, n = 0.0, len(t)
    for size in range(max(1, n - 2), n + 3):
        for start in range(max(1, len(r) - size + 1)):
            ratio = difflib.SequenceMatcher(None, t, r[start:start + size], autojunk=False).ratio()
            if ratio > best:
                best = ratio
    return best


def _plain(text):
    """Lower case, accents removed."""
    return "".join(c for c in unicodedata.normalize("NFKD", (text or "").lower()) if not unicodedata.combining(c))


def authors_agree(reference_text, authors):
    """
    True when at least one author of the record also appears in the reference text (family name = last word of the
    name). True as well when the record lists no authors, because then there is nothing to compare.
    """
    if not authors:
        return True
    plain = _plain(reference_text)
    words = set(_WORD.findall(plain))
    squashed = re.sub(r"[^a-z0-9]", "", plain)               # a PDF sometimes glues names together: "DiazGaliano"
    for author in authors:
        tokens = _WORD.findall(_plain(author))
        if not tokens:
            continue
        family = tokens[-1]
        if (len(family) >= 4 and family in squashed) or family in words:
            return True
    return False


SHORT_TITLE_WORDS = 4         # a title this short can match an unrelated reference by chance
NEAR_EXACT = 0.98
PREPRINT_TYPES = {"posted-content", "preprint"}      # an arXiv copy carries the date of its LATEST version, not of the first posting


def judge_match(reference_text, record):
    """
    record: a dict from crossref.check_reference() with status "found".
    Returns (verdict, similarity, note); verdict is "match", "check" or "different".
    """
    title = record.get("title") or ""
    similarity = title_similarity(reference_text, title) if title else 0.0

    if similarity < CHECK_AT:
        return "different", similarity, "CrossRef's closest record has a different title."
    if similarity < MATCH_AT:
        return "check", similarity, "The title only partly matches -- compare by eye."

    # A short or not-quite-exact title can match an unrelated reference by chance: then an author must agree too.
    risky = similarity < NEAR_EXACT or len(_tokens(title)) <= SHORT_TITLE_WORDS
    if risky and not authors_agree(reference_text, record.get("authors")):
        return ("check", similarity,
                "The title matches, but none of the record's authors appears in the reference -- compare by eye.")

    year = record.get("year")
    reference_years = sorted({int(y) for y in _YEAR.findall(reference_text or "")})
    if (year and reference_years and (record.get("type") or "") not in PREPRINT_TYPES
            and min(abs(year - y) for y in reference_years) > 1):
        return ("check", similarity,
                f"Same title, but CrossRef says {year} and the reference says "
                f"{', '.join(map(str, reference_years))} -- possibly another version of the paper.")
    return "match", similarity, ""


# A DOI that stops too early (or a mistyped one) can lead to a whole journal or proceedings volume.
# Such a record's title is the venue name -- which the reference also contains -- so the title
# would "match" without the record being the cited paper.
VENUE_TYPES = {"proceedings", "proceedings-series", "journal", "journal-issue", "journal-volume"}


def judge_exact(reference_text, record, kind):
    """
    For a record found through an exact identifier (kind: "arXiv ID" or "DOI").
    Returns (verdict, similarity, note); verdict is "match", "check" or "different".
    The year is not compared here: a reference often carries the venue year, the identifier the first posting.
    """
    title = record.get("title") or ""
    similarity = title_similarity(reference_text, title) if title else 0.0

    if (record.get("type") or "") in VENUE_TYPES:
        return ("check", similarity,
                f"The {kind} leads to a whole {record['type'].replace('-', ' ')}, not to this paper -- "
                f"the {kind} may be cut off or wrong.")
    if similarity >= MATCH_AT:
        return "match", similarity, ""
    if similarity >= CHECK_AT:
        return "check", similarity, "The title only partly matches -- compare by eye."
    return "different", similarity, f"The {kind} in the reference belongs to a different paper."