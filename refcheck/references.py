"""
references.py -- find the bibliography inside a paper's text and split it into entries.

Steps:  clean text -> locate bibliography -> split into entries
        (numbered / author-year / APA) -> trim leaked text -> tidy for display.
"""
import re
from dataclasses import dataclass


# ---------------------------------------------------------------- 1. cleaning

# DOIs, web addresses and arXiv IDs contain full stops that must stay exactly as they are
# ("10.1109/ICRC.2017.8123664" must not become "10.1109/ICRC. 2017. 8123664").
_PROTECTED = re.compile(r"https?://\S+|10\.\d{4,9}/\S+|arxiv\W{0,3}(?:abs/|pdf/)?\d{4}\.\d{4,5}", re.IGNORECASE)


def _add_missing_spaces(piece):
    piece = re.sub(r'\.(?=[A-Z])', '. ', piece)         # "Smith.The"  -> "Smith. The"
    return re.sub(r'\.(?=\d{4})', '. ', piece)         # "Smith.2018" -> "Smith. 2018"


def clean_text(raw):
    """Repair the usual damage from PDF text extraction."""
    text = re.sub(r'-\n', '', raw)                                           # words hyphenated across lines
    text = re.sub(r'(10\.\d{4,9}/\S*[./])\n(?=[0-9a-z])', r'\1', text)     # a DOI broken across two lines
    text = re.sub(r'\s*\n\s*', ' ', text)                                    # newlines -> single spaces
    # accent marks that some PDF fonts leave as separate characters ("Germ´an")
    text = re.sub(r'[\u0060\u00B4\u00A8\u02C6\u02C7\u00B8\u00AF\u02DC\u00B0\u0300-\u036F]', '', text)

    pieces, last = [], 0
    for match in _PROTECTED.finditer(text):                                  # add missing spaces, but not inside identifiers
        pieces.append(_add_missing_spaces(text[last:match.start()]))
        pieces.append(match.group())
        last = match.end()
    pieces.append(_add_missing_spaces(text[last:]))
    return "".join(pieces)


# ------------------------------------------------- 2. locating the bibliography

# Only capitalised headings count: lowercase "references" is just an ordinary word.
HEADING = re.compile(r'\b(?:References|REFERENCES|R\s?EFERENCES|Bibliography|BIBLIOGRAPHY|B\s?IBLIOGRAPHY)\b')
NAME_PATTERN = re.compile(r'[A-Z][a-z]+,?\s+[A-Z][a-z]+[\s,]')
MARKER = re.compile(r'\[(\d+)\]')


INITIAL_NAME = re.compile(r"\b[A-Z][a-z]+,\s+[A-Z]\.|\b[A-Z]\.(?:\s?[A-Z]\.)*\s+[A-Z][a-z]+")      # "Bell, S."  "S. Bell"


def _citation_score(window):
    """How citation-like is this stretch of text? (author-name patterns + [n] / [Key] / "1." markers)"""
    return (len(NAME_PATTERN.findall(window)) + len(MARKER.findall(window))
            + len(KEY_MARKER.findall(window)) + len(DOT_MARKER.findall(window))
            + len(INITIAL_NAME.findall(window)))


def _density_start(text):
    """Last resort: the densest cluster of author names."""
    positions = [m.start() for m in NAME_PATTERN.finditer(text)]
    best_start, best_count = None, 0
    for window_start in range(0, len(text), 1000):
        count = sum(1 for p in positions if window_start <= p < window_start + 2000)
        if count > best_count:
            best_start, best_count = window_start, count
    return best_start if best_count >= 4 else None


def _candidate_starts(text):
    """Places where the reference list might begin, most promising first: headings, a [1] marker, a cluster of names."""
    scored = []
    for m in HEADING.finditer(text):                       # the word 'References' also appears in a table of contents or a caption
        score = _citation_score(text[m.end():m.end() + 800])
        if score > 0:
            scored.append((score, m.end()))
    scored.sort(reverse=True)
    candidates = []

    def add(position, method):
        if all(abs(position - other) > 300 for other, _ in candidates):
            candidates.append((position, method))

    for _, position in scored[:4]:
        add(position, "heading")
    for m in reversed(list(re.finditer(r'\[1\]\s+[A-Z]', text))):      # numbered lists start with "[1]": the last one followed by "[2]"
        if re.search(r'\[2\]', text[m.start():m.start() + 4000]):
            add(m.start(), "numbered-marker")
            break
    density = _density_start(text)
    if density is not None:
        add(density, "density")
    return candidates


def _locate_and_split(text):
    """
    Try the candidate starts. The first one is kept when it gives a sensible list; otherwise the candidate that
    splits into clearly more entries wins. Returns (start, method, style, entries) or None.
    """
    candidates = _candidate_starts(text)
    if not candidates:
        return None
    best = None
    for rank, (position, method) in enumerate(candidates):
        block = _trim_tail(text[position:])
        style, entries = _split_block(block)
        if rank == 0:
            best = (position, method, style, entries)
            if len(entries) >= 5 and len(block) / len(entries) <= 600:        # a sensible list: stop here
                break
        elif len(entries) >= 5 and len(entries) > 1.5 * len(best[3]):
            best = (position, method, style, entries)
    return best


def find_bibliography_start(text):
    """Returns (position, method), or (None, None) if no bibliography is found."""
    found = _locate_and_split(text)
    return (found[0], found[1]) if found else (None, None)


END_MARKERS = [r'\bAppendix\s+[A-Z0-9]\b', r'\bSupplementary\s+Material\b',
               r'\bSupplementary\s+Information\b']


_CAPS_APPENDIX = re.compile(                                  # ICLR style: "A LOCALISATION In this ..." / "A L OCALISATION In this ..."
    r"\b[A-D]\s+(?:[A-Z]\s?[A-Z]{3,}|[A-Z]{4,})(?:[\s\-]+(?:[A-Z]\s?[A-Z]{2,}|[A-Z]{2,})){0,7}\s+(?=[A-Z][a-z]+\b)")


def _trim_tail(block):
    """Cut off an appendix or supplementary section that follows the reference list."""
    for pattern in END_MARKERS:
        m = re.search(pattern, block, re.IGNORECASE)
        if m and m.start() > 300:
            return block[:m.start()]
    m = _CAPS_APPENDIX.search(block, 300)
    if m:
        return block[:m.start()]
    return block


# ------------------------------------------------------ 3. splitting into entries

def _parse_numbered(block):
    """[1] ... [2] ... style. Returns a list of (number, text), or None if it is not this style."""
    accepted = []
    last = 0
    has_one = any(int(m.group(1)) == 1 for m in MARKER.finditer(block))
    for m in MARKER.finditer(block):
        n = int(m.group(1))
        # the list starts at [1]; after that accept the next number in sequence
        # (allowing a small gap) and ignore strays such as [0] or [17] inside an entry
        starts_list = (n == 1) if has_one else (n <= 3)
        if (not accepted and starts_list) or (accepted and last < n <= last + 3):
            accepted.append((m, n))
            last = n
    if len(accepted) < 3:          # one or two matches are noise (code like data[0])
        return None
    entries = []
    for i, (m, n) in enumerate(accepted):
        end = accepted[i + 1][0].start() if i + 1 < len(accepted) else len(block)
        text = re.sub(r'\s+\d{3,4}$', '', block[m.end():end].strip()).strip()
        entries.append((str(n), text))
    return entries


# "[Alsheikh et al., 2015] Authors. Title."  (IJCAI, AAAI)   and   "[ADG+16] Authors. Title."  (BibTeX "alpha" style, GPT-3)
_KEY_NAME = r"[A-Z\u00c0-\u00d6\u00d8-\u00de\u0100-\u017f][A-Za-z\u00c0-\u00ff\u0100-\u017f'\u2019\-]+"
KEY_MARKER = re.compile(
    r"\[(" + _KEY_NAME + r"(?:\s+(?:and|&)\s+" + _KEY_NAME + r")?(?:\s+et al\.?)?,?\s+(?:19|20)\d{2}[a-z]?"
    r"|[a-z]?[A-Z][A-Za-z+]{0,8}\d{2,4}[a-z]?)\]")


def _parse_key_labels(block):
    """Returns a list of (key, text), or None if the block is not a list whose entries start with a [Key]."""
    matches = list(KEY_MARKER.finditer(block))
    if len(matches) < 5 or matches[0].start() > 40:       # the very first thing in the list must be a key
        return None
    keys = [m.group(1) for m in matches]
    if len(set(keys)) < 0.9 * len(keys):                   # repeated keys are in-text citations, not a list
        return None
    entries = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(block)
        entries.append((keys[i], block[m.end():end].strip()))
    return entries


# "1. Smith J, Jones K. Title. Journal. 2018;5(2):1-10."  (PLOS, Vancouver and many medical journals).
# A number counts only if it is exactly the NEXT number in the sequence, so "vol. 3." inside an entry is ignored.
DOT_MARKER = re.compile(r"(?:(?<=\s)|^)(\d{1,3})\.\s+(?=[A-Z])")


def _parse_numbered_dot(block):
    """Returns a list of (number, text), or None if the block is not a list numbered 1. 2. 3. ..."""
    accepted, last = [], 0
    for m in DOT_MARKER.finditer(block):
        n = int(m.group(1))
        if n == last + 1:
            accepted.append((m, n))
            last = n
    if len(accepted) < 5 or accepted[0][0].start() > 60:      # a real list starts with "1." right after the heading
        return None
    entries = []
    for i, (m, n) in enumerate(accepted):
        end = accepted[i + 1][0].start() if i + 1 < len(accepted) else len(block)
        entries.append((str(n), block[m.end():end].strip()))
    return entries


# A name part is either an initial ("J.", "L.-J.", "J.R.") or a word ("Smith", "O'Neil", "Fei-Fei", "Llu\u2019is" -- an accent
# the PDF turned into a quote). A full stop may follow initials only. Without this rule the last words of a Title Case title
# ("... Image Database. InCVPR09.") or a venue ending ("... IEEE.") were swallowed into the NEXT entry's author list.
_UP = "A-Z\u00c0-\u00d6\u00d8-\u00de\u0100-\u017f"          # capitals incl. accented ones and L-stroke, S-caron, Z-caron ...
_INITIAL = rf"[{_UP}]\.(?:-?[{_UP}]\.|-[a-z]\.)*"                         # J.  L.-J.  W.-t. (Yih)
_WORD = rf"[{_UP}][\w'\u2019\u2018\-]*"
_GLUED = rf"(?:van|von|de|der|den|la|le|du|dos|das|da|di|del)[{_UP}][\w'\u2019\u2018\-]*"   # "derMaaten": a PDF that lost the space
_APOS = rf"[dDlLoO]['\u2019][{_UP}][\w'\u2019\u2018\-]*"                                   # d'Autume  L'Hote  O'Brien
_LOWER_SURNAME = r"(?:dos|das|da|de|do|di|del|van|von|der|den|ter|ten)\s+[a-z]{3,}"          # "dos santos" (BibTeX keeps it lower-case)
_TOKEN = r"(?:" + _INITIAL + r"|(?:Jr|Sr)\.|" + _WORD + r"|" + _GLUED + r"|" + _APOS + r"|" + _LOWER_SURNAME + r")"
_PARTICLE = r"(?:d\.|v\.|de|van|von|der|la|le|du|dos|das|bin|ibn|al|ter|ten|af|zu|do|da|den)"        # "Freitas, N. d.," ("d." = de)
_NAME = r"(?:" + _PARTICLE + r"\s+)*" + _TOKEN + r"(?:\s+(?:" + _TOKEN + r"|" + _PARTICLE + r"))*"
_SEP = r"(?:,\s*(?:and\s+)?|\s+and\s+)"
_ETAL = r"(?:,?\s+(?:et\s+al\.?|and\s+others))?"             # "Ryan Lowe, et al."  /  "and others"  (a shortened author list)
_ROLE = r"(?:,\s*(?:editors?|eds?\.?))?"                    # "Wicentowski, editors. 2007."
_NOT_INSIDE_A_WORD = r"(?<![\w'\u2019\u2018\-])"          # a name starts at a word start, never in the middle of "IEEE."
AUTHOR_YEAR_HEADER = re.compile(
    _NOT_INSIDE_A_WORD + r"(" + _NAME + r"(?:" + _SEP + _NAME + r")*" + _ETAL + _ROLE + r"\.\s+\d{4}[a-z]?\.)\s*")


# The end of one entry ("... Association for Computational Linguistics.") is cut in the middle by the
# entry splitter: "Association for" stays, but "Computational Linguistics." lands at the START of the next
# entry. These are the publisher / venue endings that get stranded that way (found in about 20% of the
# entries of a 757-paper proceedings).
LEAKED_TAIL = re.compile(
    r"^((?:Computational Linguistics|Learning Representations|Neural Information Processing Systems|"
    r"Natural Language Processing|Computing Machinery|AAAI Press|Curran Associates, Inc|Curran Associates|"
    r"PMLR|Springer|IEEE|ACM|ACL|MIT Press)\.)\s+(?=[A-Z])")


def _move_leaked_tails(entries):
    """Give a stranded venue ending back to the entry it belongs to (the previous one)."""
    for i in range(1, len(entries)):
        match = LEAKED_TAIL.match(entries[i])
        if match:
            entries[i - 1] = f"{entries[i - 1]} {match.group(1)}"
            entries[i] = entries[i][match.end():]
    return entries


def _parse_author_year(block):
    """'Author, Author, and Author. 2019. Title ...' style."""
    parts = AUTHOR_YEAR_HEADER.split(block)
    entries = []
    if len(parts[0].strip()) > 40:            # text before the first recognised entry is a reference too; never drop it silently
        entries.append(parts[0].strip())
    for i in range(1, len(parts) - 1, 2):
        entry = f"{parts[i].strip()} {parts[i + 1].strip()}".strip()
        if len(entry) > 20:
            entries.append(entry)
    return _move_leaked_tails(entries)


_DATE = r"(?:(?<=\.),\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+(?:19|20)\d{2})?"       # "Garvie, C., May 2019."
_AUTHORS_FIRST = re.compile(
    _NOT_INSIDE_A_WORD + r"(" + _NAME + r"(?:" + _SEP + _NAME + r")*" + _ETAL + _DATE + r"(?:\s*\((?:eds?|editors?)\.?\))?)(?:\.\s+|(?<=\.)\s+)(?=[A-Z0-9\u201c\"\u2018'(])")
_ENTRY_ENDING = re.compile(r"(?:\d[a-z]?|Linguistics|Press|Inc|Springer|IEEE|ACM|PMLR|Association)\.?\s*$")


_ORGANISATIONS = {"Google", "OpenAI", "Meta", "DeepMind", "Microsoft", "Anthropic", "NVIDIA", "Facebook", "IBM", "Amazon", "Apple",
                  "Intel", "Wikipedia", "Mozilla", "Kaggle", "Stanford", "Github", "GitHub", "Huggingface", "HuggingFace", "Cohere",
                  "Alibaba", "Baidu", "Tencent", "Mistral", "EleutherAI", "BigScience", "LAION", "UNESCO", "OECD"}   # one-word authors


def _parse_authors_first(block):
    """
    'Authors. Title. Venue, 2019.' style: there is no year after the authors, so entries are cut where an author
    list begins right after something that looks like the end of an entry (a digit -- year, pages, volume -- or a
    publisher). Only used when the usual parsers found almost nothing.
    """
    starts = [0]
    for m in _AUTHORS_FIRST.finditer(block):
        group = m.group(1)
        if m.start() == 0 or (not re.search(r"[\s,]", group) and group not in _ORGANISATIONS):   # "Nat. Commun." is not an author list
            continue
        before = block[max(0, m.start() - 40):m.start()].rstrip()
        strong = (len(re.findall(r",|\band\b", group)) >= 2                   # three or more names in a row: an author list for sure
                  or bool(re.match(_WORD + r",\s+" + _INITS, group))          # or "Surname, I." -- even a single author
                  or group in _ORGANISATIONS)                                 # or a known organisation ("Google.")
        inside_a_name = bool(re.search(r"\b(?:van|von|de|der|den|la|le|du|dos|das|da|di|del|ter|ten|d\.|v\.)\s*$", before))
        if ((_ENTRY_ENDING.search(before[-30:]) or strong) and not (before.endswith(",") or before.endswith(":"))
                and not inside_a_name):
            starts.append(m.start())
    entries = [block[a:b].strip() for a, b in zip(starts, starts[1:] + [len(block)])]
    return _move_leaked_tails([e for e in entries if len(e) > 20])


# "Axelrod, A., He, X., and Gao, J. (2011). Title."   "Azuma, Koji, Kiyoshi Tamaki, and William J. Munro (2015b), 'Title,'"
# (APA, Harvard, Rev. Mod. Phys.): the year stands in brackets right after a run of name parts.
_RUN_TOKEN = r"(?:" + _INITIAL + r"|(?:Jr|Sr)\.|" + _WORD + r"|" + _GLUED + r"|" + _APOS + r"|" + _LOWER_SURNAME + r"|" + _PARTICLE + r"(?=[\s,]))"
_RUN_SEP = r"(?:,\s*(?:and\s+|&\s*)?|\s+(?:and\s+|&\s*)?)"
_RUN = _RUN_TOKEN + r"(?:" + _RUN_SEP + _RUN_TOKEN + r")*"
PAREN_YEAR_HEADER = re.compile(_NOT_INSIDE_A_WORD + r"(" + _RUN + _ETAL + r"\s*\((?:19|20)\d{2}[a-z]?\)[.,]?)\s*")


def _parse_paren_year(block):
    """'Authors (2019). Title ...' and 'Authors (2019), "Title," ...' styles."""
    parts = PAREN_YEAR_HEADER.split(block)
    entries = []
    if len(parts[0].strip()) > 40:
        entries.append(parts[0].strip())
    for i in range(1, len(parts) - 1, 2):
        entry = f"{parts[i].strip()} {parts[i + 1].strip()}".strip()
        if len(entry) > 20:
            entries.append(entry)
    return entries


_parse_apa = _parse_paren_year                      # the old name, used by run_inspect.py

# "Azuma, K., Tamaki, K., Munro, W.J., 2015. Title."  (Elsevier / Harvard): every author is "Surname, Initials",
# and a comma (not a full stop) stands before the year. Needs real "Surname, I." units so that "In ICLR, 2019." is not an author list.
_INITS = rf"[{_UP}]\.(?:\s?-?[{_UP}]\.|-[a-z]\.)*"
_SI_UNIT = r"(?:" + _PARTICLE + r"\s+)*" + _WORD + r"(?:\s+(?:" + _WORD + r"|" + _PARTICLE + r"))*,\s+" + _INITS
_SI_SEP = r"(?:,\s*(?:and\s+|&\s*)?|\s+(?:and|&)\s+)"
ELSEVIER_HEADER = re.compile(
    _NOT_INSIDE_A_WORD + r"(" + _SI_UNIT + r"(?:" + _SI_SEP + _SI_UNIT + r")*(?:,?\s+et\s+al\.?)?,?\s+(?:19|20)\d{2}[a-z]?\.)\s*")


def _parse_elsevier(block):
    parts = ELSEVIER_HEADER.split(block)
    entries = []
    if len(parts[0].strip()) > 40:
        entries.append(parts[0].strip())
    for i in range(1, len(parts) - 1, 2):
        entry = f"{parts[i].strip()} {parts[i + 1].strip()}".strip()
        if len(entry) > 20:
            entries.append(entry)
    return entries


# ---------------------------------------------------- 4. trimming leaked text

_APPENDIX_LABEL = re.compile(r'\.\s+\d{0,4}\s*[A-Z]\s+[A-Z][a-z]{2,}')   # ". A Experiment Setup"
_APPENDIX_HEADING = re.compile(r"[.,]\s+(?:[A-Z]|\d{1,2})\.\s+(?:[A-Z][A-Za-z\-]+\s+){2,6}(?:In|We|The|This|Our|For)\s")
_FIGURE = re.compile(r'\bFigure\s+\d+[:.]')
_TABLE = re.compile(r'\bTable\s+\d+[:.]')
_APPENDIX_WORD = re.compile(r'\bappendix\b', re.IGNORECASE)
_SUPPLEMENTARY = re.compile(r'\bSupplementary\s+(Material|Information)\b', re.IGNORECASE)
_PAGE_RANGE_TAIL = re.compile(r'\d+[\-\u2013]\s?\d{4}$')
_BARE_YEAR_TAIL = re.compile(r'(?<!\d)\d{4}$')


def _is_real_year(preceding):
    """A trailing 4-digit number is a year only if it is not the end of a page range (5586-5609)."""
    if _PAGE_RANGE_TAIL.search(preceding):
        return False
    return bool(_BARE_YEAR_TAIL.search(preceding))


def trim_contamination(entry, min_length=300, min_match_pos=80):
    """
    Appendix / figure / table text sometimes gets glued onto the LAST entry of a list.
    Only long entries are examined, and a title that merely starts with "A" right after
    the year ("... 2020. A French Corpus ...") is left alone.
    """
    if len(entry) < min_length:
        return entry
    cuts = []
    for m in _APPENDIX_LABEL.finditer(entry):
        if m.start() >= min_match_pos and not _is_real_year(entry[:m.start()]):
            cuts.append(m.start())
    for m in _APPENDIX_HEADING.finditer(entry):               # "A." or "2." with a full stop is a heading, never a title
        if m.start() >= min_match_pos:
            cuts.append(m.start() + 1)
    for pattern in (_FIGURE, _TABLE, _APPENDIX_WORD, _SUPPLEMENTARY):
        for m in pattern.finditer(entry):
            if m.start() >= min_match_pos:
                cuts.append(m.start())
    return entry[:min(cuts)].strip() if cuts else entry


# ----------------------------------------------------------- 5. tidying + checks

def tidy_reference(text):
    """Undo spacing damage inside identifiers: 'arXiv:2212. 10820' -> 'arXiv:2212.10820'."""
    # arXiv IDs split by the extraction: "arXiv:2212. 10820", "ArXiv, abs/2303. 03697"
    text = re.sub(r'((?:arXiv|abs/)\W{0,12}\d{4})\.\s+(\d{4,5})', r'\1.\2', text, flags=re.IGNORECASE)
    text = re.sub(r'\b(10)\.\s+(\d{4,9}/)', r'\1.\2', text)
    text = re.sub(r'(10\.\d{4,9}/[\w\.\-]*?\d)\.\s+(\d{3,})', r'\1.\2', text)
    text = re.sub(r'(10\.\d{4,9}/)\s+(?=\w)', r'\1', text)                          # "10.18653/ v1/N19-1423"
    text = re.sub(r'(https?://[^\s]*?\.)\s+(?=[a-z]{2,}/)', r'\1', text)             # "https://www.aclweb. org/anthology/"
    return re.sub(r'\s+', ' ', text).strip()


_CONNECTORS = {"and", "&", "et", "al", "de", "van", "von", "der", "la", "le", "du",
               "dos", "das", "da", "di", "del", "bin", "ibn"}
_SENTENCE_STARTERS = {"The", "This", "These", "Those", "A", "An", "In", "It", "We", "Our", "Its"}
_YEAR = re.compile(r'\b(?:19|20)\d{2}\b')
_YEAR_TOKEN = re.compile(r'\(?(?:19|20)\d{2}[a-z]?\)?[.,]?')


def looks_like_citation(entry):
    """
    Starts like an author list (capitalised names, initials, connectors, a year token)
    and contains a year. Used only as a paper-level sanity check, never per entry.
    """
    e = entry.strip().lstrip('“"‘\'[(')
    tokens = e.split()[:4]
    if len(tokens) < 3 or tokens[0] in _SENTENCE_STARTERS:
        return False

    def author_like(t):
        return t[0].isupper() or t.lower().strip('.,') in _CONNECTORS or bool(_YEAR_TOKEN.fullmatch(t))

    return all(author_like(t) for t in tokens) and bool(_YEAR.search(e[:400]))


# ------------------------------------------------------------------ 6. main entry

@dataclass
class ExtractionResult:
    entries: list        # [(label, text), ...]  label = "[n]" number or running index
    style: str           # numbered / author-year / apa / none
    method: str          # how the bibliography was located
    reliable: bool       # False when the list is empty or does not look like citations
    note: str = ""


def _share_with_year(entries):
    """Share of the entries that contain a year: a reference nearly always does, a sentence from an appendix does not."""
    return sum(1 for _, text in entries if _YEAR.search(text)) / max(1, len(entries))


def _split_block(block, allow_numbered=True):
    """The style cascade for ONE block of text. Returns (style, [(label, text), ...])."""
    style = "numbered"
    entries = _parse_numbered(block) if allow_numbered else None
    if entries is not None and len(entries) < 8 and _share_with_year(entries) < 0.5:
        # a few "[1] [2] [3]" markers inside appendix text (prompt examples, JSON ...) are not a reference list:
        # let the other styles compete, and keep the numbered result only if they find nothing better
        other_style, other_entries = _split_block(block, allow_numbered=False)
        if len(other_entries) >= 5:
            return other_style, other_entries
    if entries is None:
        entries = _parse_key_labels(block)
        style = "keyed" if entries is not None else style
    if entries is None:
        entries = _parse_numbered_dot(block)
        style = "numbered" if entries is not None else style
    if entries is None:
        style = "author-year"
        entries = [(str(i), e) for i, e in enumerate(_parse_author_year(block), 1)]
    if style == "author-year" and (len(entries) <= 3 or len(block) / len(entries) > 600):
        # the usual parser found almost nothing, or entries that are far too long (merged): try the other styles
        candidates = {"paren-year": _parse_paren_year(block), "elsevier": _parse_elsevier(block),
                      "author-first": _parse_authors_first(block)}
        plausible = {k: v for k, v in candidates.items() if v and len(block) / len(v) >= 90}   # entries of 90+ characters on average
        if plausible:
            top = max(len(v) for v in plausible.values())
            # a style anchored on the YEAR is more trustworthy than "authors first", which can over-split at
            # publisher lines: take the first style (in this priority order) that is within 80% of the best count
            best_style = next(k for k, v in plausible.items() if len(v) >= 0.8 * top)
            best = plausible[best_style]
            if len(best) >= 5 and len(best) > 1.3 * len(entries):
                style = best_style
                entries = [(str(i), e) for i, e in enumerate(best, 1)]
    if not entries:
        style = "paren-year"
        entries = [(str(i), e) for i, e in enumerate(_parse_paren_year(block), 1)]
    return style, entries


def extract_references(raw_text):
    """Raw page text of ONE paper -> ExtractionResult."""
    text = clean_text(raw_text)
    found = _locate_and_split(text)
    if found is None:
        return ExtractionResult([], "none", "none", False, "No reference section found.")
    _, method, style, entries = found
    if not entries:
        return ExtractionResult([], "none", method, False, "Reference section found but no entries could be split.")

    entries = [(label, tidy_reference(trim_contamination(t))) for label, t in entries]
    entries = [(label, t) for label, t in entries if t]
    # appendix prose that follows the list is cut into "entries" too: long, and without a single year
    while len(entries) > 8 and len(entries[-1][1]) > 500 and not _YEAR.search(entries[-1][1]):
        entries.pop()

    reliable = len(entries) > 6 or any(looks_like_citation(t) for _, t in entries)
    note = "" if reliable else "Few entries and none look like citations -- the real reference list was probably not found."
    return ExtractionResult(entries, style, method, reliable, note)