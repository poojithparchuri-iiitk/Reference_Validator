"""
Look up the arXiv IDs and DOIs written in a PDF's references -- live, from the terminal:

    python run_lookup.py samples/sample5.pdf your.name@example.com
    python run_lookup.py samples/sample5.pdf your.name@example.com 20      (only the first 20 of each kind)
"""
import os
import sys
import pymupdf

from refcheck.arxiv import check_ids
from refcheck.crossref import check_dois
from refcheck.identifiers import find_arxiv_id, find_doi
from refcheck.matching import judge_exact
from refcheck.references import extract_references


LABEL = {"match": "MATCH", "check": "CHECK", "different": "DIFFERENT PAPER"}

REPORT = []


def say(line=""):
    """Print a line, even if the console cannot show some letters (a Windows console may not know 'c-caron'),
    and remember it for the report file, which is always written as UTF-8."""
    REPORT.append(line)
    encoding = sys.stdout.encoding or "utf-8"
    print(line.encode(encoding, errors="replace").decode(encoding))


def main(path, mailto, limit):
    doc = pymupdf.open(path)
    entries = extract_references("".join(page.get_text() for page in doc)).entries
    with_arxiv = [(label, text, find_arxiv_id(text)) for label, text in entries if find_arxiv_id(text)]
    with_doi = [(label, text, find_doi(text)) for label, text in entries if find_doi(text)]
    say(f"{len(entries)} references: {len(with_arxiv)} carry an arXiv ID, {len(with_doi)} carry a DOI.\n")

    counts = {}
    if with_arxiv:
        with_arxiv = with_arxiv[:limit]
        say(f"--- arXiv: looking up {len(with_arxiv)} IDs (one request per 40 IDs, 3 seconds apart) ---")
        results = check_ids([i for _, _, i in with_arxiv], mailto)
        for label, text, arxiv_id in with_arxiv:
            r = results[arxiv_id]
            if r["status"] == "found":
                verdict, sim, note = judge_exact(text, r, "arXiv ID")
                name = LABEL[verdict]
                say(f"[{label}] arXiv:{arxiv_id:<17} {name:<16} similarity {sim:.2f} | {r['title'][:70]} ({r['year']})")
                if note:
                    say(f"        note: {note}")
            else:
                name = "NO SUCH ID" if r["status"] == "not_found" else "ERROR"
                say(f"[{label}] arXiv:{arxiv_id:<17} {name:<16} {r['error'] or ''}")
            say(f"        reference: {text[:100]}")
            counts[name] = counts.get(name, 0) + 1
        say(f"arXiv summary: {counts}\n")

    counts = {}
    if with_doi:
        with_doi = with_doi[:limit]
        say(f"--- DOIs: looking up {len(with_doi)} ---")
        results = check_dois([d for _, _, d in with_doi], mailto)
        for label, text, doi in with_doi:
            r = results[doi]
            if r["status"] == "found":
                verdict, sim, note = judge_exact(text, r, "DOI")
                name = LABEL[verdict]
                say(f"[{label}] {doi:<32} {name:<16} similarity {sim:.2f} via {r['source']}, type {r['type']} | {(r['title'] or '')[:55]}")
                if note:
                    say(f"        note: {note}")
            elif r["status"] == "exists":
                name = "EXISTS, NO DETAILS"
                say(f"[{label}] {doi:<32} {name}")
            else:
                name = "NO SUCH DOI" if r["status"] == "not_found" else "ERROR"
                say(f"[{label}] {doi:<32} {name} {r['error'] or ''}")
            say(f"        reference: {text[:100]}")
            counts[name] = counts.get(name, 0) + 1
        say(f"DOI summary: {counts}")
    if not with_arxiv and not with_doi:
        say("Nothing to look up: none of the references carries an arXiv ID or a DOI.")

    report_name = "lookup_" + os.path.splitext(os.path.basename(path))[0] + ".txt"
    with open(report_name, "w", encoding="utf-8") as f:
        f.write("\n".join(REPORT))
    print(f"\nFull report saved as {report_name}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python run_lookup.py file.pdf [your e-mail] [how many of each kind]")
    else:
        main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "", int(sys.argv[3]) if len(sys.argv) > 3 else 100)