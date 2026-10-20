"""Check the splitting + extraction on one PDF:   python run_split.py samples/test_proceedings.pdf"""
import sys
import pymupdf

from refcheck.splitter import split_papers, paper_text
from refcheck.references import extract_references


def main(path, mode="auto"):
    doc = pymupdf.open(path)
    spans, mode_used, reason = split_papers(doc, mode)
    print(f"FILE: {path}  ({len(doc)} pages)")
    print(f"MODE: {mode_used}  -- {reason}")
    print(f"PAPERS: {len(spans)}\n")
    total = 0
    for span in spans:
        result = extract_references(paper_text(doc, span))
        total += len(result.entries)
        print(f"[{span.index + 1}] pages {span.start_page + 1}-{span.end_page + 1} | "
              f"{len(result.entries):>3} refs | {result.style:<11} | reliable={result.reliable} | {span.title[:70]}")
    print(f"\nTOTAL REFERENCES: {total}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python run_split.py file.pdf [auto|single|multi]")
    else:
        main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "auto")