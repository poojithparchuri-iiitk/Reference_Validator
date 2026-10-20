"""
audit.py -- sanity checks on an extracted reference list, so that a missed, merged, repeated or
invented reference does not slip through unnoticed. No network needed.

Each check produces a flag with a level:
    warning   something probably needs a human look (counts as "needs attention")
    info      worth knowing, but not necessarily a problem
"""
import difflib
import re
import unicodedata

CITATION_MARKER = re.compile(r"\[[\d,\s\-\u2013\u2014]+\]")
_WORD = re.compile(r"[a-z0-9]+")

LONG_ENTRY = 600          # characters; a longer entry with two years in it is probably two references stuck together
VERY_LONG_ENTRY = 6000    # characters; this long is suspicious even with a single year (a 280-author report is ~3,500)
SHORT_ENTRY = 25          # characters; shorter entries are usually a fragment
FEW_REFERENCES = 5        # a paper with more than a few pages of text and this few references: look at it
DUPLICATE_AT = 0.85       # word-level similarity above which two entries count as the same reference
SAME_RUN_WORDS = 10       # ... or this many identical words in a row ...
SAME_RUN_SHARE = 0.60     # ... making up at least this share of the shorter entry
MIN_MATCHED_SHARE = 0.30  # in-text check is only trusted if at least this share of the list is cited


def cited_numbers(body):
    """Reference numbers cited in the text: [3], [3, 5], [7-10]. A bracket containing 0 is maths, not a citation."""
    cited = set()
    for marker in CITATION_MARKER.finditer(body or ""):
        numbers = []
        for part in re.split(r",\s*", marker.group().strip("[]")):
            part = part.strip()
            span = re.match(r"^(\d+)\s*[-\u2013\u2014]\s*(\d+)$", part)
            if span and 0 < int(span.group(2)) - int(span.group(1)) <= 60:
                numbers.extend(range(int(span.group(1)), int(span.group(2)) + 1))
            elif part.isdigit():
                numbers.append(int(part))
        if numbers and 0 not in numbers:
            cited.update(numbers)
    return cited


def _plain(text):
    """Lower-case, accents, hyphens and apostrophes removed ("Pöppelmann" == "Poppelmann", "Gutiérrez-Fandiño" == "GutiérrezFandiño")."""
    letters = "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))
    return re.sub(r"[-'\u2019\u2018]", "", letters)


_NAME = r"([A-Z\u00c0-\u00d6\u00d8-\u00de\u0100-\u017f][A-Za-z\u00c0-\u00ff\u0100-\u017f'\u2019\-]{2,})"
_YEARTAG = r"((?:19|20)\d{2})[a-z]?(?![A-Za-z0-9])"                       # "2022YFB4500200" (a grant number) is not a year
# "Smith, 2019"  "Smith et al., 2019"  "Smith and Lee, 2019"           (ACL style, with a comma)
_AUTHORS_PART = r"(?:\s+et al\.?|\s+(?:and|&)\s+[A-Z][A-Za-z'\u2019\-]+)?"
_CITE_WITH_COMMA = re.compile(_NAME + _AUTHORS_PART + r",\s+" + _YEARTAG)
# "Smith 2019"  "Smith and Lee 2019"                                            (AAAI / IJCAI style, no comma)
_CITE_SPACE_ONLY = re.compile(_NAME + _AUTHORS_PART + r"\s+" + _YEARTAG)
# "Smith (2019)"  "Smith et al. (2019)"  "Smith and Lee (2019)"
_CITE_NARRATIVE = re.compile(_NAME + r"(?:\s+et al\.?|\s+(?:and|&)\s+[A-Z][A-Za-z'\u2019\-]+)?\s+\(" + _YEARTAG)
_PAREN_WITH_YEAR = re.compile(r"[\(\[]([^()\[\]]*\b(?:19|20)\d{2}[a-z]?(?![A-Za-z0-9])[^()\[\]]*)[\)\]]")
_NOT_NAMES = {"Spring", "Summer", "Fall", "Autumn", "Winter", "See", "Table", "Figure", "Fig", "Section", "Eq", "Equation", "Appendix", "Chapter", "Version", "May", "June", "July",
              "April", "March", "January", "February", "August", "September", "October", "November", "December", "Page", "Pages",
              "Wikipedia", "Gigaword", "Twitter", "Reddit", "Facebook", "Google", "Amazon", "Linux", "Windows", "Python", "Common"}


def cited_author_years(body):
    """
    (surname, year) pairs cited in the text: (Smith et al., 2019; Lee, 2020) and Smith (2019).
    A paper that cites with commas is read that way only, so that "(Spring 2022)" or "(June 2022)" is not taken for a citation.
    """
    with_comma, space_only = set(), set()
    for group in _PAREN_WITH_YEAR.finditer(body or ""):
        for piece in group.group(1).split(";"):
            for name, year in _CITE_WITH_COMMA.findall(piece):
                if name not in _NOT_NAMES:
                    with_comma.add((_plain(name), year))
            for name, year in _CITE_SPACE_ONLY.findall(piece):
                if name not in _NOT_NAMES:
                    space_only.add((_plain(name), year))
    found = set(with_comma)
    if len(with_comma) < 3:                       # this paper does not cite with commas: allow "(Smith 2019)"
        found |= space_only
    for name, year in _CITE_NARRATIVE.findall(body or ""):
        if name not in _NOT_NAMES:
            found.add((_plain(name), year))
    return found


def _author_year_check(entries, body, add):
    """The author-year counterpart of the numbering check: is everything cited in the text in the list?"""
    cited = cited_author_years(body)
    if len(cited) < 3:
        add("info", "no_text_check", "Too few author-year citations were found in the text to cross-check the list.")
        return
    heads = [(_plain(text[:150]), _plain(text)) for _, text in entries]

    def listed(surname, year):
        return any(surname in head and year in whole for head, whole in heads)

    missing = sorted((n, y) for n, y in cited if not listed(n, y))
    matched = len(cited) - len(missing)
    if matched < MIN_MATCHED_SHARE * len(cited):
        add("info", "no_text_check", "The author-year citations in the text could not be matched to the list, "
                                      "so that cross-check was skipped.")
        return
    if missing:
        shown = ", ".join(f"{n.title()} ({y})" for n, y in missing[:8]) + (" ..." if len(missing) > 8 else "")
        add("warning", "cited_not_listed",
            f"Cited in the text but not found in the list: {shown} -- entries may have been lost "
            f"({len(missing)} of {len(cited)} citations).")
    unseen = [label for label, text in entries
              if not any(_plain(text[:150]).find(n) >= 0 and y in _plain(text) for n, y in cited)]
    if unseen and len(unseen) <= 0.5 * len(entries):
        add("info", "never_cited", f"In the list but not recognised as cited in the text: {_numbers(unseen[:12])}"
                                   f"{' ...' if len(unseen) > 12 else ''} (the citation style may differ).")


_ALPHA_KEY = re.compile(r"^[a-z]?[A-Z][A-Za-z+]{0,8}\d{2,4}[a-z]?$")
_ALPHA_IN_TEXT = re.compile(r"\b([a-z]?[A-Z][A-Za-z+]{0,8}\d{2,4}[a-z]?)\b")


def _keyed_check(entries, body, add):
    """Lists whose entries start with a key: [ADG+16] (alpha) or [Alsheikh et al., 2015] (author-year in brackets)."""
    labels = [label for label, _ in entries]
    if sum(1 for label in labels if _ALPHA_KEY.match(label)) >= 0.7 * len(labels):
        cited = set()
        for group in re.findall(r"\[([^\[\]]{2,200})\]", body or ""):
            cited.update(k for k in _ALPHA_IN_TEXT.findall(group) if k in set(labels) or "+" in k or len(k) <= 7)
        if len(cited & set(labels)) < MIN_MATCHED_SHARE * len(labels):
            add("info", "no_text_check", "The bracketed keys in the text could not be matched to the list, so that cross-check was skipped.")
            return
        not_listed = sorted(cited - set(labels))
        if not_listed:
            add("warning", "cited_not_listed", "Cited in the text but not in the list: "
                + ", ".join(f"[{k}]" for k in not_listed[:8]) + (" ..." if len(not_listed) > 8 else "") + " -- entries may have been lost.")
        never = [label for label in labels if label not in cited]
        if never and len(never) <= 0.5 * len(labels):
            add("info", "never_cited", f"In the list but not recognised as cited in the text: {_numbers(never[:12])}"
                                       f"{' ...' if len(never) > 12 else ''}.")
    else:
        _author_year_check(entries, body, add)


def find_duplicates(entries):
    """Pairs of (label_a, label_b) whose text is almost the same, e.g. one paper listed twice."""
    words = [(label, _WORD.findall(text.lower())) for label, text in entries]
    sets = [set(w) for _, w in words]
    pairs = []
    for i in range(len(words)):
        if len(words[i][1]) < 6:
            continue
        for j in range(i + 1, len(words)):
            if len(words[j][1]) < 6:
                continue
            overlap = len(sets[i] & sets[j]) / len(sets[i] | sets[j])
            if overlap < 0.5:                                   # cheap filter before the slow comparison
                continue
            matcher = difflib.SequenceMatcher(None, words[i][1], words[j][1], autojunk=False)
            run = matcher.find_longest_match(0, len(words[i][1]), 0, len(words[j][1])).size
            shorter = min(len(words[i][1]), len(words[j][1]))
            # same words overall, OR one long identical stretch (the same title even if the
            # authors' accents or the volume details are written differently)
            if matcher.ratio() >= DUPLICATE_AT or (run >= SAME_RUN_WORDS and run >= SAME_RUN_SHARE * shorter):
                pairs.append((words[i][0], words[j][0]))
    return pairs


_YEAR_IN_ENTRY = re.compile(r"\b(?:19|20)\d{2}[a-z]?\b")
_NOT_A_YEAR = re.compile(r"https?://\S+|doi:\s*\S+|10\.\d{4,9}/\S+|arxiv:?\s*\S+|abs/\S+", re.IGNORECASE)


def _looks_merged_by_years(text):
    """
    Two references stuck together hold two different years, or at least three year numbers. One reference may repeat its own
    year ("2023. ... EMNLP 2023"). arXiv IDs, DOIs and web addresses are not years (2005.14165).
    """
    years = [y[:4] for y in _YEAR_IN_ENTRY.findall(_NOT_A_YEAR.sub(" ", text))]
    return len(set(years)) >= 2 or len(years) >= 3


def _tail_after_first_year(text):
    """
    Characters that follow the FIRST year in an entry. A real reference ends soon after its year (title, venue, pages), even with
    300 authors; appendix text glued on, or a second reference, makes this long.
    """
    hidden = _NOT_A_YEAR.sub(lambda m: " " * len(m.group()), text)           # same length, so positions stay valid
    match = _YEAR_IN_ENTRY.search(hidden)
    return len(text) - match.end() if match else 0


def _numbers(labels):
    return ", ".join(f"[{n}]" for n in labels)


def audit_paper(entries, style, method, body=""):
    """
    entries : [(label, text), ...] as returned by extract_references
    style   : "numbered", "keyed", "author-year", "apa", ...
    method  : how the bibliography was located ("heading", "numbered-marker", "density")
    body    : the paper's text BEFORE the reference list (for the in-text cross-check)

    Returns {"flags": [...], "flagged_refs": {label: [messages]}, "warnings": int, "passed": bool}
    """
    flags, flagged = [], {}

    def add(level, code, message, refs=()):
        flags.append({"level": level, "code": code, "message": message, "refs": [str(r) for r in refs]})
        if level == "warning":
            for r in refs:
                flagged.setdefault(str(r), []).append(message)

    if not entries:
        add("warning", "no_references", "No references could be extracted from this paper.")
        return {"flags": flags, "flagged_refs": flagged, "warnings": 1, "passed": False}

    total_chars = sum(len(text) for _, text in entries)
    if len(entries) <= 3 and total_chars > 2000:
        add("warning", "not_split",
            f"Only {len(entries)} reference(s) were found, but they hold {total_chars} characters -- "
            f"the reference list was probably not split into separate references.", [label for label, _ in entries])

    if len(entries) <= FEW_REFERENCES and len(body or "") > 8000:
        add("warning", "few_references",
            f"Only {len(entries)} reference(s) for a paper with {len(body)} characters of text before the list -- "
            f"the real reference list may not have been found.", [label for label, _ in entries])

    if method == "density":
        add("warning", "weak_location",
            "The reference list was found by a weak method (no heading, no [1] marker) -- check that it is complete.")

    # --- entries that look wrong on their own ---
    long_ones = [label for label, text in entries
                 if len(text) > VERY_LONG_ENTRY
                 or (len(text) > LONG_ENTRY and _looks_merged_by_years(text))
                 or (len(text) > 1000 and _tail_after_first_year(text) > 700)]
    if long_ones:
        add("warning", "long_entry", f"Very long entry ({_numbers(long_ones)}) -- possibly two references merged.", long_ones)
    short_ones = [label for label, text in entries if len(text) < SHORT_ENTRY]
    if short_ones:
        add("warning", "short_entry", f"Very short entry ({_numbers(short_ones)}) -- probably a fragment.", short_ones)

    # --- the same reference twice ---
    for a, b in find_duplicates(entries):
        add("warning", "duplicate", f"[{a}] and [{b}] look like the same reference.", [a, b])

    # --- numbered lists: numbering and in-text citations ---
    if style == "numbered":
        labels = [int(label) for label, _ in entries]
        missing = sorted(set(range(1, max(labels) + 1)) - set(labels)) if labels else []
        if labels and labels[0] != 1:
            add("warning", "start", f"The list starts at [{labels[0]}], not [1] -- earlier references may be lost.")
        if missing:
            add("warning", "gap", f"Numbering gap: {_numbers(missing)} missing from the list -- entries may have been lost.")

        cited = cited_numbers(body)
        in_list = set(labels)
        if not cited or len(cited & in_list) < MIN_MATCHED_SHARE * len(in_list):
            add("info", "no_text_check", "The in-text citations could not be matched to the list "
                                          "(not numbered brackets?), so that cross-check was skipped.")
        else:
            ceiling = max(labels) * 1.25 + 3                      # [256, 480] in "scale in [256, 480]" is a range, not a citation
            not_in_list = sorted(n for n in cited - in_list if n <= ceiling)
            if not_in_list:
                add("warning", "cited_not_listed",
                    f"Cited in the text but not in the list: {_numbers(not_in_list)} -- entries may have been lost.")
            never_cited = sorted(in_list - cited)
            if never_cited:
                add("info", "never_cited",
                    f"In the list but never cited in the text: {_numbers(never_cited)} "
                    f"(maybe cited only in a table, figure or appendix).")
    elif style == "keyed":
        _keyed_check(entries, body, add)
    else:
        _author_year_check(entries, body, add)

    warnings = sum(1 for f in flags if f["level"] == "warning")
    return {"flags": flags, "flagged_refs": flagged, "warnings": warnings, "passed": warnings == 0}