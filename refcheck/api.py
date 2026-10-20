"""
api.py -- the one function other projects call.

    from refcheck.api import validate_reference_texts
    results = validate_reference_texts(["Ashish Vaswani et al. 2017. Attention is all you need. NeurIPS."], "you@example.com")

Each result says whether a record with the same title exists (arXiv ID and DOI exact; otherwise CrossRef search, top 5 records),
where it was found, and what kind of record it is. Weak matches are "check", never "found". No guessing.
"""
from refcheck.identifiers import find_arxiv_id, find_doi
from refcheck.kinds import reference_kind
from refcheck.labels import found_in, record_kind
from refcheck.pipeline import validate_papers

_EMPTY = {"status": "not_checked", "source": "", "match_title": None, "authors": [], "year": None, "venue": None, "publisher": None,
          "type": None, "doi": None, "score": None, "title_similarity": None, "note": "", "error": None, "evidence": []}


def validate_reference_texts(texts, mailto="", caches=None, progress=None):
    """
    texts   : list of reference strings, exactly as they appear in the paper's reference list
    mailto  : your e-mail address (CrossRef answers 3 times faster when it knows who asks)
    caches  : a dict you keep between calls so nothing is looked up twice (it may be saved to disk as JSON)
    progress: optional callback progress(label, done, total)

    Returns a list of dicts, one per text, in the same order:
      status          "found" | "check" | "not_found" | "error"
                      found = a record with the same title exists; check = a person should compare; not_found = no source has it;
                      error = a lookup failed (ask again later; this says nothing about the reference)
      found_in        "arXiv", "CrossRef", "DOI via CrossRef", ... ("" unless found or check)
      record_kind     "journal article", "conference paper", "book", "preprint", ... ("" unless found or check)
      match_title, authors, year, venue, type, doi   the record that was found (empty unless found or check)
      closest_rejected_record   for "not_found" only: the nearest record the databases offered, which was REJECTED as a different paper
      arxiv_id, doi_in_text   identifiers that were written in the reference itself
      title_similarity, note  how well the title matched, and why a result is "check"
      probable_kind   only for "not_found": "web page", "book", "thesis", "report or documentation", "software or dataset",
                      or "paper (not indexed)"
      evidence        what each source said
    """
    refs = [{"number": str(i), "text": text, "arxiv_id": find_arxiv_id(text), "doi_in_text": find_doi(text), **_EMPTY,
             "authors": [], "evidence": []} for i, text in enumerate(texts, 1)]
    validate_papers({"papers": [{"references": refs}]}, None, mailto, {} if caches is None else caches, progress)

    results = []
    for r in refs:
        good = r["status"] in ("found", "check")
        # for "not_found" the pipeline keeps the closest record it REJECTED; it must never look like a match
        closest = ({"title": r["match_title"], "authors": r["authors"], "year": r["year"], "venue": r["venue"], "doi": r["doi"],
                    "title_similarity": r["title_similarity"]}
                   if r["status"] == "not_found" and r["match_title"] else None)
        results.append({
            "text": r["text"], "status": r["status"],
            "found_in": found_in(r["source"]) if good else "", "record_kind": record_kind(r["type"], r["source"]) if good else "",
            "match_title": r["match_title"] if good else None, "authors": r["authors"] if good else [],
            "year": r["year"] if good else None, "venue": r["venue"] if good else None, "type": r["type"] if good else None,
            "doi": r["doi"] if good else None, "closest_rejected_record": closest,
            "arxiv_id": r["arxiv_id"], "doi_in_text": r["doi_in_text"],
            "title_similarity": r["title_similarity"], "note": r["note"],
            "probable_kind": (reference_kind(r["text"]) or "paper (not indexed)") if r["status"] == "not_found" else "",
            "evidence": r["evidence"], "error": r["error"]})
    return results