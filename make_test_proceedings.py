"""
Builds a small test 'proceedings' PDF from the sample papers, with one bookmark per paper
(the way ACL Anthology volumes are built).   python make_test_proceedings.py
"""
import pymupdf

from refcheck.titles import guess_title

SAMPLES = ["sample.pdf", "sample2.pdf", "sample3.pdf", "sample4.pdf", "sample5.pdf", "sample6.pdf"]

out = pymupdf.open()
toc = []
for name in SAMPLES:
    src = pymupdf.open(f"samples/{name}")
    toc.append([1, guess_title(src), len(out) + 1])       # bookmark -> first page of this paper (1-based)
    out.insert_pdf(src)
out.set_toc(toc)
out.save("samples/test_proceedings.pdf")
print(f"Saved samples/test_proceedings.pdf  ({len(out)} pages, {len(SAMPLES)} papers)")