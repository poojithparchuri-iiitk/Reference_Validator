"""Command-line check of the extraction step:  python run_extract.py samples/sample.pdf"""
import sys
import pymupdf

from refcheck.references import extract_references
from refcheck.titles import guess_title, title_from_metadata, title_from_largest_text


def main(paths):
    for path in paths:
        doc = pymupdf.open(path)
        raw_text = "".join(page.get_text() for page in doc)
        result = extract_references(raw_text)

        print("=" * 70)
        print(f"FILE:        {path}")
        print(f"TITLE:       {guess_title(doc)}")
        print(f"  (metadata: {title_from_metadata(doc)!r} | largest text: {title_from_largest_text(doc)!r})")
        print(f"REFERENCES:  {len(result.entries)}   style={result.style}   located by={result.method}   reliable={result.reliable}")
        if result.note:
            print(f"NOTE:        {result.note}")
        for label, text in result.entries[:3]:
            print(f"  [{label}] {text[:110]}")
        print("  ...")
        for label, text in result.entries[-2:]:
            print(f"  [{label}] {text[:110]}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python run_extract.py file1.pdf [file2.pdf ...]")
    else:
        main(sys.argv[1:])