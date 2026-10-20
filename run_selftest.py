"""
Live self-test of the exact lookups (arXiv and DOI): things that MUST be found, and things that MUST be flagged.

    python run_selftest.py your.name@example.com

It writes selftest_report.txt (UTF-8). Takes about 30 seconds.
"""
import sys

from refcheck.arxiv import check_ids
from refcheck.crossref import check_dois
from refcheck.matching import judge_exact

REPORT = []


def say(line=""):
    REPORT.append(line)
    encoding = sys.stdout.encoding or "utf-8"
    print(line.encode(encoding, errors="replace").decode(encoding))


# (arXiv ID, reference text as it might appear, acceptable outcomes)
ARXIV_CASES = [
    ("1706.03762", "Ashish Vaswani et al. 2017. Attention is all you need. arXiv:1706.03762.", {"match"}),
    ("2010.11929", "Alexey Dosovitskiy et al. 2020. An image is worth 16x16 words: Transformers for image recognition at scale. arXiv:2010.11929.", {"match"}),
    ("2501.99999", "Nobody. 2025. A paper that does not exist. arXiv:2501.99999.", {"no such id"}),
    ("1706.03763", "Ashish Vaswani et al. 2017. Attention is all you need. arXiv:1706.03763.", {"different", "no such id"}),
]
MALFORMED_ID = "9999.99999"        # month 99 does not exist: arXiv must report it, and the good IDs must survive

# (DOI, reference text, acceptable outcomes, required source or None)
DOI_CASES = [
    ("10.1145/3007651", "Keith A. Britt and Travis S. Humble. 2017. High-Performance Computing with Quantum Processing Units. ACM JETC.", {"match"}, "CrossRef"),
    ("10.5281/zenodo.12786681", "Zilong Li. 2024. Example dataset for QUILT2. Zenodo.", {"match"}, "DataCite"),
    ("10.5281/zenodo.6518360", "Ricardo Roman-Brenes. 2022. Example Data for PlotsOfData Tutorial. Zenodo.", {"match"}, "DataCite"),
    ("10.5281/zenodo.4769814", "Quan Xu and Simon J van Heeringen. 2021. ANANSE example data. Zenodo.", {"match"}, "DataCite"),
    ("10.1145/0000000.0000000", "Nobody. 2020. A paper that does not exist. ACM.", {"no such doi"}, None),
    ("10.1145/3007652", "Keith A. Britt and Travis S. Humble. 2017. High-Performance Computing with Quantum Processing Units. ACM JETC.", {"different", "no such doi"}, None),
    # a DOI cut off too early leads to the whole conference volume: this was a false MATCH before the guard
    ("10.1109/QCE57702.2023", "Brice Chichereau et al. 2023. Experimenting with Hybrid Quantum Optimization in HPC. In 2023 IEEE International Conference on Quantum Computing and Engineering (QCE).", {"check"}, None),
]


def outcome_of(result, text, kind):
    if result["status"] == "found":
        verdict, similarity, note = judge_exact(text, result, kind)
        return verdict, f"similarity {similarity:.2f}, type {result.get('type')}, source {result.get('source')}, title {(result['title'] or '')[:50]!r}"
    if result["status"] == "exists":
        return "exists", "registered, no details"
    if result["status"] == "not_found":
        return f"no such {'id' if kind == 'arXiv ID' else 'doi'}", ""
    return "error", result.get("error") or ""


def main(mailto):
    passed = total = 0

    say("--- arXiv: four IDs plus one malformed ID in the SAME request ---")
    ids = [c[0] for c in ARXIV_CASES] + [MALFORMED_ID]
    results = check_ids(ids, mailto)
    for arxiv_id, text, expected in ARXIV_CASES:
        got, detail = outcome_of(results[arxiv_id], text, "arXiv ID")
        ok = got in expected
        passed += ok; total += 1
        say(f"{'PASS' if ok else 'FAIL'}  arXiv:{arxiv_id:<12} expected {sorted(expected)}, got {got!r}  {detail}")
    got, detail = outcome_of(results[MALFORMED_ID], "", "arXiv ID")
    ok = got in {"no such id", "error"}
    passed += ok; total += 1
    say(f"{'PASS' if ok else 'FAIL'}  arXiv:{MALFORMED_ID:<12} malformed ID, got {got!r}  {detail}")

    say("\n--- DOIs: CrossRef, DataCite, a missing DOI, a wrong DOI, a cut-off DOI ---")
    results = check_dois([c[0] for c in DOI_CASES], mailto)
    for doi, text, expected, source in DOI_CASES:
        got, detail = outcome_of(results[doi], text, "DOI")
        ok = got in expected and (source is None or results[doi].get("source") == source)
        passed += ok; total += 1
        say(f"{'PASS' if ok else 'FAIL'}  {doi:<26} expected {sorted(expected)}{' via ' + source if source else ''}, got {got!r}  {detail}")

    say(f"\n{passed} of {total} checks behaved as expected.")
    with open("selftest_report.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(REPORT))
    print("Full report saved as selftest_report.txt")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "")