"""
Look up the first few references of a PDF on CrossRef:
    python run_check.py samples/sample.pdf your.name@example.com 10
"""
import sys
import pymupdf

from refcheck.crossref import check_many
from refcheck.references import extract_references


def main(path, mailto, how_many):
    doc = pymupdf.open(path)
    result = extract_references("".join(page.get_text() for page in doc))
    texts = [text for _, text in result.entries][:how_many]
    print(f"Checking {len(texts)} of {len(result.entries)} references ({'polite pool, 3/s' if mailto else 'anonymous, 1/s'}) ...\n")

    outcomes = check_many(texts, mailto, progress=lambda done, total: print(f"  {done}/{total}", end="\r"))
    print()
    counts = {"found": 0, "not_found": 0, "error": 0}
    for i, (text, outcome) in enumerate(zip(texts, outcomes), 1):
        counts[outcome["status"]] += 1
        print(f"[{i}] {outcome['status'].upper():<9} score={outcome['score']}")
        print(f"     reference : {text[:90]}")
        print(f"     CrossRef  : {(outcome['title'] or outcome['error'] or '-')[:90]}")
    print(f"\nSUMMARY: {counts}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python run_check.py file.pdf [your e-mail] [how many references]")
    else:
        email = sys.argv[2] if len(sys.argv) > 2 else ""
        n = int(sys.argv[3]) if len(sys.argv) > 3 else 10
        main(sys.argv[1], email, n)