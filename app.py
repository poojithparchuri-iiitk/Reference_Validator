"""
Reference Validator -- Streamlit app.
Upload a paper (or a multi-paper proceedings PDF); the app lists each paper's title and references
and checks every reference on CrossRef. Or open a saved results file to browse many papers at once.

Run:  python -m streamlit run app.py
"""
import csv
import hashlib
import html
import io
import json
from collections import Counter
from urllib.parse import quote

import streamlit as st

from refcheck.kinds import reference_kind
from refcheck.labels import found_in, record_kind
from refcheck.pipeline import analyze_pdf, count_statuses, lookup_plan, validate_papers

PAPERS_PER_PAGE = 50     # papers opened below at once; a selector pages through the rest
DATA_VERSION = 6        # bump whenever the structure of the stored results changes
BADGES = {"found": ("Found", "ok"), "check": ("Check", "warn"), "not_found": ("Not found", "bad"),
          "error": ("Error", "err"), "not_checked": ("Not checked", "idle")}

st.set_page_config(page_title="Reference Validator", layout="wide")

st.markdown("""
<style>
table.refs { width: 100%; border-collapse: collapse; font-size: 1.05rem; line-height: 1.5; }
table.refs th { text-align: left; padding: 10px 12px; border-bottom: 2px solid rgba(128,128,128,0.5); }
table.refs td { padding: 10px 12px; border-bottom: 1px solid rgba(128,128,128,0.3); vertical-align: top; }
table.refs td.num { width: 3rem; white-space: nowrap; }
table.refs td.status { width: 10.5rem; }
table.refs td.match { width: 36%; }
table.refs td.pages, table.refs td.count { width: 11rem; white-space: nowrap; }
.badge { padding: 3px 12px; border-radius: 14px; font-weight: 600; font-size: 0.95rem; white-space: nowrap; }
.badge.ok   { background: rgba(33,160,70,0.18);  color: #1b8a3c; }
.badge.bad  { background: rgba(220,50,50,0.18);  color: #d03030; }
.badge.warn { background: rgba(230,150,0,0.20);  color: #c27c00; }
.badge.err  { background: rgba(110,80,200,0.20); color: #6a4fc7; }
.badge.idle { background: rgba(128,128,128,0.18); }
.closest { opacity: 0.75; }
</style>
""", unsafe_allow_html=True)


def evidence_cell(r):
    """What we found for one reference, from whichever source, as HTML (all text escaped)."""
    if r["status"] == "error":
        return html.escape(r.get("error") or r.get("note") or "")
    lines = []
    has_record = bool(r.get("match_title") or r.get("doi"))
    if r["status"] == "not_found":
        kind = reference_kind(r["text"])
        lines.append("<small><b>" + (f"Probably a {kind}, not a paper in these databases." if kind
                                      else "Probably a paper that these databases do not index.") + "</b></small>")
    if has_record:
        if r["status"] == "not_found":
            lines.append("<small><i>Closest record found -- a different paper:</i></small>")
        lines.append(f"<b>{html.escape(r.get('match_title') or '(no title)')}</b>")
        authors = r.get("authors") or []
        if authors:
            shown = ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "")
            lines.append(f"<small>{html.escape(shown)}</small>")
        year = r.get("year")
        where = [x for x in (r.get("venue"), str(year) if year else None,
                             (r.get("type") or "").replace("-", " ")) if x]
        if where:
            lines.append(f"<small>{html.escape(' | '.join(where))}</small>")
        tail = []
        if r.get("source"):
            tail.append(f"via {html.escape(r['source'])}")
        if r.get("title_similarity") is not None:
            tail.append(f"title match {r['title_similarity']:.2f}")
        doi = r.get("doi")
        if doi:
            url = "https://doi.org/" + quote(doi, safe="/")
            tail.append(f'<a href="{html.escape(url)}" target="_blank" rel="noopener">{html.escape(doi)}</a>')
        if tail:
            lines.append(f"<small>{' | '.join(tail)}</small>")
    if r.get("note"):
        lines.append(f"<small><i>{html.escape(r['note'])}</i></small>")
    cell = "<br>".join(lines)
    return f"<div class='closest'>{cell}</div>" if (r["status"] == "not_found" and has_record) else cell


def references_table(refs, flagged=None):
    """HTML table of one paper's references. Every piece of text is HTML-escaped first."""
    flagged = flagged or {}
    rows = []
    for r in refs:
        label, css = BADGES[r["status"]]
        number = html.escape(str(r["number"]))
        if str(r["number"]) in flagged:                # the audit found something odd about this entry
            tip = html.escape(" / ".join(flagged[str(r["number"])]), quote=True)
            number += f" <span title='{tip}' style='cursor:help'>&#9888;</span>"
        where = ""
        if r["status"] in ("found", "check"):                      # say where it was found, and as what
            parts = [x for x in (found_in(r.get("source")), record_kind(r.get("type"), r.get("source"))) if x]
            where = f"<br><small>{html.escape(' | '.join(parts))}</small>" if parts else ""
        rows.append(f"<tr><td class='num'>{number}</td>"
                    f"<td class='status'><span class='badge {css}'>{label}</span>{where}</td>"
                    f"<td>{html.escape(r['text'])}</td><td class='match'>{evidence_cell(r)}</td></tr>")
    return ("<table class='refs'><thead><tr><th>#</th><th>Result</th><th>Reference (from the PDF)</th>"
            "<th>What we found</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>")


def papers_table(papers):
    """HTML overview of every paper in a proceedings file: title, pages, references, audit result."""
    rows = []
    for p in papers:
        warnings = p["audit"]["warnings"]
        audit = "passed" if warnings == 0 else f"{warnings} warning{'s' if warnings != 1 else ''}"
        file_cell = f"<td class='pages'><small>{html.escape(p['file'])}</small></td>" if "file" in p else ""
        rows.append(f"<tr><td class='num'>{p['paper_index'] + 1}</td>{file_cell}<td>{html.escape(p['title'])}</td>"
                    f"<td class='pages'>{p['n_pages']} <small>(p. {html.escape(p['pages'])})</small></td>"
                    f"<td class='count'>{p['reference_count']}</td><td class='count'>{audit}</td></tr>")
    file_head = "<th>File</th>" if papers and "file" in papers[0] else ""
    return (f"<table class='refs'><thead><tr><th>#</th>{file_head}<th>Title</th><th>Pages</th><th>References</th>"
            "<th>Extraction audit</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>")


def results_csv(analysis):
    """One row per reference, for Excel (with a byte-order mark so accents display correctly)."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["paper_no", "file", "paper_title", "ref_no", "reference", "status", "found_in", "record_kind", "matched_title",
                     "matched_authors", "matched_venue", "matched_type", "year", "doi", "source", "title_similarity", "note",
                     "probable_kind", "audit_warning"])
    for p in analysis["papers"]:
        flagged = p["audit"]["flagged_refs"]
        for r in p["references"]:
            similarity = r.get("title_similarity")
            writer.writerow([p["paper_index"] + 1, p.get("file", ""), p["title"], r["number"], r["text"], r["status"],
                             found_in(r.get("source")) if r["status"] in ("found", "check") else "",
                             record_kind(r.get("type"), r.get("source")) if r["status"] in ("found", "check") else "",
                             r.get("match_title") or "", "; ".join(r.get("authors") or []), r.get("venue") or "",
                             r.get("type") or "", r.get("year") or "", r.get("doi") or "", r.get("source") or "",
                             "" if similarity is None else similarity, r.get("note") or "",
                             (reference_kind(r["text"]) or "paper (not indexed)") if r["status"] == "not_found" else "",
                             " / ".join(flagged.get(str(r["number"]), []))])
    return ("\ufeff" + out.getvalue()).encode("utf-8")


st.title("Reference Validator")

MODE_PDF, MODE_SAVED = "Check a PDF", "Open saved results (JSON)"
mode = st.radio("What do you want to do?", [MODE_PDF, MODE_SAVED], horizontal=True)
validate = extract_only = False

if mode == MODE_PDF:
    uploaded = st.file_uploader("PDF file", type=["pdf"])
    mailto = st.text_input("Your e-mail address (recommended)",
                           help="CrossRef serves requests 3 times faster when it knows who is asking. "
                                "The address is only sent to CrossRef and is not stored by this app.")
    if uploaded is None:
        st.info("Choose a PDF to begin.")
        st.stop()

    pdf_bytes = uploaded.getvalue()
    file_key = f"{hashlib.md5(pdf_bytes).hexdigest()}-v{DATA_VERSION}"

    button_validate, button_extract, _ = st.columns([1, 2, 3])
    validate = button_validate.button("Validate references", type="primary")
    extract_only = button_extract.button("Only extract the references (no internet)",
                                         help="Splits each paper's reference list and runs the extraction audit. "
                                              "Nothing is sent anywhere; takes seconds.")
else:
    saved = st.file_uploader("Saved results (.json), made by run_export_all.py or downloaded from this app", type=["json"])
    if saved is None:
        st.info("Choose a results file to begin.")
        st.stop()
    raw = saved.getvalue()
    file_key = f"{hashlib.md5(raw).hexdigest()}-saved"
    if st.session_state.get("analysis_key") != file_key:
        try:
            loaded = json.loads(raw)
            assert isinstance(loaded.get("papers"), list) and all("references" in p and "audit" in p for p in loaded["papers"])
        except Exception:
            st.error("This is not a results file made by this app.")
            st.stop()
        st.session_state["analysis"] = loaded
        st.session_state["analysis_key"] = file_key

if validate or extract_only:
    if st.session_state.get("analysis_key") != file_key:
        bar = st.progress(0.0, text="Reading the PDF ...")
        st.session_state["analysis"] = analyze_pdf(
            pdf_bytes, "auto", lambda d, t: bar.progress(d / t, text=f"Reading paper {d} of {t}"))
        st.session_state["analysis_key"] = file_key
        bar.empty()

if validate:
    analysis = st.session_state["analysis"]
    caches = st.session_state.setdefault(f"caches_v{DATA_VERSION}", {})
    for table in caches.values():                          # a failed lookup says nothing about the reference: ask again
        for key in [k for k, v in table.items() if isinstance(v, dict) and v.get("status") == "error"]:
            del table[key]
    plan = lookup_plan(analysis, caches)
    rate = 3 if mailto.strip() else 1
    seconds = -(-plan["arxiv_ids"] // 40) * 3 + plan["dois"] / rate + plan["texts"] / rate
    note = st.empty()
    if plan["references"] and (plan["arxiv_ids"] or plan["dois"] or plan["texts"]):
        note.info(f"Checking {plan['references']} references: {plan['arxiv_ids']} carry an arXiv ID and "
                  f"{plan['dois']} a DOI (looked up exactly, first); the others are searched on CrossRef at "
                  f"{rate} per second. At most about {max(1, round(seconds / 60))} minute(s).")
    bar = st.progress(0.0, text="Checking references ...")
    validate_papers(analysis, None, mailto.strip(), caches,
                    lambda label, d, t: bar.progress(d / t, text=f"{label}: {d} of {t}"))
    bar.empty()
    note.empty()

if st.session_state.get("analysis_key") != file_key:
    st.info("Click **Validate references** (checks the references against databases) or **Only extract the references** (no internet) to start.")
    st.stop()

analysis = st.session_state["analysis"]
papers = analysis["papers"]
total_refs = sum(p["reference_count"] for p in papers)

if analysis["mode"] == "multi":
    st.success(f"Detected: **multi-paper proceedings** -- {len(papers)} papers, "
               f"{analysis['n_pages']} pages, {total_refs} references.")
    st.caption(f"How the papers were found: {analysis['reason']}.")
    if analysis["reason"].startswith("no bookmarks"):
        st.warning("This file has no bookmarks, so each paper was recognised from the layout of its first page "
                   "(a title, then \"Abstract\"). A paper with a different first-page layout can be missed and merged "
                   "with the paper before it -- compare the list below with your file.")
    st.subheader("Papers in this file")
    st.markdown(papers_table(papers), unsafe_allow_html=True)
else:
    st.success(f"Detected: **single paper** -- {analysis['n_pages']} pages, {total_refs} references.")

counts = count_statuses(analysis)
validated = counts["not_checked"] < total_refs
if validated:
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Papers", len(papers))
    c2.metric("References", total_refs)
    c3.metric("Found", counts["found"])
    c4.metric("Check", counts["check"])
    c5.metric("Not found", counts["not_found"])
    c6.metric("Errors", counts["error"])
    st.caption("**Found**: a source has a record with the same title as the reference. "
               "**Check**: the evidence only partly agrees (similar title, a different year, or an identifier that leads "
               "to a whole journal or volume) -- compare by eye. "
               "**Not found**: no source has it, or the closest record is a different paper; this is common for "
               "websites, theses and older proceedings. **Error**: a lookup failed -- run it again.")
else:
    passed = sum(1 for p in papers if not p["audit"]["warnings"])
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Papers", len(papers))
    c2.metric("References", total_refs)
    c3.metric("Papers that passed the audit", passed)
    c4.metric("Papers with warnings", len(papers) - passed)
    st.info("The references have only been **extracted**, not checked against any database."
            + (" Click **Validate references** to check them." if mode == MODE_PDF else ""))
kinds_of_not_found = Counter(reference_kind(r["text"]) or "paper (not indexed)" for p in papers for r in p["references"]
                             if r["status"] == "not_found")
if kinds_of_not_found:
    st.caption("**Not found, by kind** (a guess from the wording): "
               + ", ".join(f"{name} {n}" for name, n in kinds_of_not_found.most_common()) + ".")
export_key = (st.session_state["analysis_key"], counts["found"], counts["check"], counts["not_found"], counts["error"])
if st.session_state.get("export_key") != export_key:                    # build the files once, not at every click
    st.session_state["export_csv"] = results_csv(analysis)
    st.session_state["export_json"] = json.dumps(analysis, ensure_ascii=False).encode("utf-8")
    st.session_state["export_key"] = export_key
d1, d2, _ = st.columns([2, 2, 4])
d1.download_button("Download all references (CSV)", st.session_state["export_csv"], "references.csv", "text/csv")
d2.download_button("Download full results (JSON)", st.session_state["export_json"], "results.json", "application/json")
found_as = Counter(record_kind(r.get("type"), r.get("source")) or "type not stated" for p in papers for r in p["references"]
                   if r["status"] == "found")
if found_as:
    st.caption("**Found as:** " + ", ".join(f"{name} {n}" for name, n in found_as.most_common()) + ".")
confirmed_by = Counter(r["source"].split(" (")[0] for p in papers for r in p["references"] if r["status"] == "found")
if confirmed_by:
    st.caption("**Confirmed by:** " + ", ".join(f"{name} {n}" for name, n in confirmed_by.most_common())
               + ". References with an arXiv ID or a DOI are looked up exactly; the rest are searched on CrossRef.")

with_warnings = sum(1 for p in papers if p["audit"]["warnings"])
st.caption(f"**Extraction audit** (is the reference list complete and sensible?): "
           f"{len(papers) - with_warnings} of {len(papers)} papers passed, {with_warnings} have warnings. "
           f"Open a paper below to see them; entries with a warning carry a \u26a0 sign.")

st.subheader("References by paper")
query = st.text_input("Filter papers by title", "")
shown = [p for p in papers if query.lower() in p["title"].lower()]
if len(shown) > PAPERS_PER_PAGE:
    ranges = [f"{i + 1}-{min(i + PAPERS_PER_PAGE, len(shown))}" for i in range(0, len(shown), PAPERS_PER_PAGE)]
    chosen = st.selectbox(f"{len(shown)} papers match. Show papers number", ranges)
    first = ranges.index(chosen) * PAPERS_PER_PAGE
    shown = shown[first:first + PAPERS_PER_PAGE]

for p in shown:
    label = f"{p['paper_index'] + 1}. {p['title']}  --  {p['reference_count']} references"
    with st.expander(label, expanded=len(papers) == 1):
        st.caption(f"pages {p['pages']}  |  style: {p['citation_style']}  |  bibliography located by: {p['detection_method']}")
        if not p["reliable"]:
            st.warning(p["note"] or "The reference list for this paper is not reliable.")
        audit_warnings = [f for f in p["audit"]["flags"] if f["level"] == "warning"]
        audit_infos = [f for f in p["audit"]["flags"] if f["level"] == "info"]
        if audit_warnings:
            st.warning("**Extraction audit**\n\n" + "\n".join(f"- {f['message']}" for f in audit_warnings))
        else:
            st.caption("Extraction audit: passed")
        for f in audit_infos:
            st.caption(f["message"])
        if p["references"]:
            st.markdown(references_table(p["references"], p["audit"]["flagged_refs"]), unsafe_allow_html=True)