"""
pipeline.py -- glue code: PDF bytes -> papers (title + references) -> CrossRef status per reference.
"""
import pymupdf

from refcheck.arxiv import check_ids
from refcheck.audit import audit_paper
from refcheck.crossref import check_dois, check_many
from refcheck.identifiers import find_arxiv_id, find_doi
from refcheck.matching import judge_exact, judge_match
from refcheck.references import ExtractionResult, clean_text, extract_references, find_bibliography_start
from refcheck.splitter import paper_text, split_papers

MIN_TEXT_CHARS = 200      # fewer characters than this means the pages are probably scanned images


def analyze_pdf(pdf_bytes, mode="auto", progress=None):
    """
    pdf_bytes : the uploaded file
    mode      : "auto", "single" or "multi"
    progress  : optional callback progress(done, total)

    Returns {"mode", "reason", "n_pages", "papers": [ {...}, ... ]}
    Every reference starts with status "not_checked".
    """
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    spans, mode_used, reason = split_papers(doc, mode)

    papers = []
    for i, span in enumerate(spans, 1):
        raw = paper_text(doc, span)
        if len(raw.strip()) < MIN_TEXT_CHARS:
            result = ExtractionResult([], "none", "none", False,
                                      "No text could be read from these pages (scanned PDF? OCR is not supported).")
        else:
            result = extract_references(raw)

        # the text before the reference list, so the audit can compare it with the list
        text = clean_text(raw)
        bibliography_start, _ = find_bibliography_start(text)
        body = text[:bibliography_start] if bibliography_start else ""
        audit = audit_paper(result.entries, result.style, result.method, body)

        papers.append({
            "paper_index": span.index,
            "title": span.title,
            "pages": f"{span.start_page + 1}-{span.end_page + 1}",
            "n_pages": span.n_pages,
            "citation_style": result.style,
            "detection_method": result.method,
            "reliable": result.reliable,
            "note": result.note,
            "audit": audit,
            "reference_count": len(result.entries),
            "references": [{"number": label, "text": text, "status": "not_checked",
                            "arxiv_id": find_arxiv_id(text), "doi_in_text": find_doi(text), "source": "",
                            "match_title": None, "authors": [], "year": None, "venue": None, "publisher": None,
                            "type": None, "doi": None, "score": None, "title_similarity": None, "note": "",
                            "error": None, "evidence": []}
                           for label, text in result.entries],
        })
        if progress:
            progress(i, len(spans))

    return {"mode": mode_used, "reason": reason, "n_pages": len(doc), "papers": papers}


VERY_LONG_ENTRY = 1500    # characters; no genuine reference is this long, several must have been merged
_RANK = {"match": 3, "check": 2, "different": 1, "none": 0, "error": -1}
_FIELDS = ("title", "authors", "year", "venue", "publisher", "type", "doi")


def _evidence(source, exact, verdict, similarity, note, record=None, score=None):
    record = record or {}
    return {"source": source, "exact": exact, "verdict": verdict, "similarity": similarity, "note": note,
            "score": score, **{k: record.get(k) for k in _FIELDS}}


def _cap_long_entry(text, verdict, note):
    """A match inside a huge entry only covers one of the merged references, so it cannot be a confident match."""
    if verdict == "match" and len(text) > VERY_LONG_ENTRY:
        return "check", (f"This entry is very long ({len(text)} characters), probably several references merged, "
                         f"so the match may cover only part of it.")
    return verdict, note


def _exact_evidence(text, result, kind, source):
    """What an exact lookup (arXiv ID or DOI) says about this reference."""
    status = result["status"]
    if status == "found":
        verdict, similarity, note = judge_exact(text, result, kind)
        verdict, note = _cap_long_entry(text, verdict, note)
        return _evidence(source, True, verdict, similarity, note, result)
    if status == "exists":
        return _evidence(source, True, "check", None,
                         f"The {kind} exists, but no details are available to compare with the reference.")
    if status == "not_found":
        return _evidence(source, True, "none", None, f"The {kind} in the reference does not exist.")
    return _evidence(source, True, "error", None, f"Looking up the {kind} failed: {result.get('error')}")


def _search_evidence(text, outcome):
    """What the CrossRef text search says about this reference."""
    if outcome["status"] == "found":
        verdict, similarity, note = judge_match(text, outcome)
        verdict, note = _cap_long_entry(text, verdict, note)
        return _evidence("CrossRef search", False, verdict, similarity, note, outcome, outcome.get("score"))
    if outcome["status"] == "not_found":
        return _evidence("CrossRef search", False, "none", None, "")
    return _evidence("CrossRef search", False, "error", None, f"The CrossRef search failed: {outcome.get('error')}")


def _combine(ref, evidence):
    """
    Put the best evidence on the reference. Order: match > check > different > nothing > error;
    on a tie an exact identifier beats a text search.
    """
    best = sorted(evidence, key=lambda e: (-_RANK[e["verdict"]], not e["exact"]))[0]
    errors = [e for e in evidence if e["verdict"] == "error"]

    if best["verdict"] == "match":
        ref["status"] = "found"
    elif best["verdict"] == "check":
        ref["status"] = "check"
    elif errors:                                   # nothing confirmed, and a lookup failed: the answer is incomplete
        ref["status"] = "error"
    else:
        ref["status"] = "not_found"

    # a wrong or invented identifier is worth reporting even when the paper was confirmed another way
    problems = [e["note"] for e in evidence if e is not best and e["exact"] and e["note"]
                and e["verdict"] in ("none", "different", "check")]
    ref["note"] = " ".join(x for x in [best["note"]] + problems if x)
    ref["error"] = " ".join(e["note"] for e in errors) or None
    ref["source"] = best["source"] if best["verdict"] in ("match", "check", "different") else ""
    has_record = best["verdict"] in ("match", "check", "different")
    for key in _FIELDS:
        value = best[key] if has_record else ([] if key == "authors" else None)
        ref["match_title" if key == "title" else key] = value        # the reference calls the title "match_title"
    ref["score"] = best["score"] if best["verdict"] in ("match", "check", "different") else None
    ref["title_similarity"] = None if best["similarity"] is None else round(best["similarity"], 3)
    ref["evidence"] = [{"source": e["source"], "verdict": e["verdict"], "title_similarity":
                        None if e["similarity"] is None else round(e["similarity"], 3),
                        "title": e["title"], "year": e["year"], "note": e["note"]} for e in evidence]


def lookup_plan(analysis, caches=None, max_papers=None):
    """How many lookups of each kind are still needed (for the time estimate)."""
    caches = caches or {}
    refs = [r for paper in analysis["papers"][:max_papers] for r in paper["references"]]
    ids = {r["arxiv_id"] for r in refs if r["arxiv_id"]} - set(caches.get("arxiv", {}))
    dois = {r["doi_in_text"] for r in refs if r["doi_in_text"]} - set(caches.get("doi", {}))
    texts = {r["text"] for r in refs} - set(caches.get("crossref", {}))
    return {"references": len(refs), "arxiv_ids": len(ids), "dois": len(dois), "texts": len(texts)}


def validate_papers(analysis, max_papers=None, mailto="", caches=None, progress=None):
    """
    Check the references of the papers (all of them, or the first `max_papers`), using every kind of
    evidence a reference offers:

        1. an arXiv ID        -> looked up exactly on arXiv
        2. a DOI              -> looked up exactly (CrossRef, then DataCite, then the DOI registry)
        3. its text           -> CrossRef search, only for references no exact lookup has confirmed

    Each reference ends with one of these statuses:
        found      a record with the same title was found (see "source" for where)
        check      the evidence only partly agrees -- a person should look
        not_found  no source has it, or the closest record is a different paper
        error      a lookup failed and nothing else confirmed the reference

    `caches` is a dict that remembers answers between runs; `progress(label, done, total)` reports progress.
    """
    caches = {} if caches is None else caches
    arxiv_cache = caches.setdefault("arxiv", {})
    doi_cache = caches.setdefault("doi", {})
    crossref_cache = caches.setdefault("crossref", {})

    def report(label):
        return (lambda done, total: progress(label, done, total)) if progress else None

    refs = [r for paper in analysis["papers"][:max_papers] for r in paper["references"]]

    ids = [r["arxiv_id"] for r in refs if r["arxiv_id"]]
    arxiv_results = check_ids(ids, mailto, report("arXiv IDs"), arxiv_cache) if ids else {}
    dois = [r["doi_in_text"] for r in refs if r["doi_in_text"]]
    doi_results = check_dois(dois, mailto, report("DOIs"), doi_cache) if dois else {}

    evidence = []
    for ref in refs:
        found_here = []
        if ref["arxiv_id"]:
            found_here.append(_exact_evidence(ref["text"], arxiv_results[ref["arxiv_id"]], "arXiv ID", "arXiv ID"))
        if ref["doi_in_text"]:
            result = doi_results[ref["doi_in_text"]]
            found_here.append(_exact_evidence(ref["text"], result, "DOI", f"DOI ({result.get('source') or 'lookup'})"))
        evidence.append(found_here)

    # the slow text search is only needed where an exact identifier did not already confirm the paper
    need_search = [i for i, found_here in enumerate(evidence) if not any(e["verdict"] == "match" for e in found_here)]
    outcomes = check_many([refs[i]["text"] for i in need_search], mailto, report("CrossRef search"), crossref_cache)
    for i, outcome in zip(need_search, outcomes):
        evidence[i].append(_search_evidence(refs[i]["text"], outcome))

    for ref, found_here in zip(refs, evidence):
        _combine(ref, found_here)


def count_statuses(analysis):
    """{'found': n, 'check': n, 'not_found': n, 'error': n, 'not_checked': n} over all references."""
    counts = {"found": 0, "check": 0, "not_found": 0, "error": 0, "not_checked": 0}
    for paper in analysis["papers"]:
        for ref in paper["references"]:
            counts[ref["status"]] += 1
    return counts