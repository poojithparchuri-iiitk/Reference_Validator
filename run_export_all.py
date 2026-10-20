r"""
Read every PDF in a folder (a proceedings chunk counts as several papers) and save ALL papers, with their
references and audit results, in one file that the app can open:

    python run_export_all.py samples\coling

Writes coling_results.json. Then start the app, choose "Open saved results (JSON)" and upload that file.
No internet needed.
"""
import glob
import json
import os
import re
import sys
import time

from refcheck.pipeline import analyze_pdf


def first_number(path):
    found = re.search(r"(\d+)", os.path.basename(path))
    return int(found.group(1)) if found else 0


def main(folder, out="coling_results.json"):
    paths = sorted(glob.glob(os.path.join(folder, "*.pdf")), key=lambda p: (first_number(p), p))
    if not paths:
        print(f"No PDF files found in {folder}")
        return
    papers, pages, started = [], 0, time.time()
    for number, path in enumerate(paths, 1):
        name = os.path.basename(path)
        print(f"[{number}/{len(paths)}] {name}  ({(time.time() - started) / 60:.1f} min)", flush=True)
        with open(path, "rb") as f:
            analysis = analyze_pdf(f.read())
        pages += analysis["n_pages"]
        for paper in analysis["papers"]:
            paper["file"] = name
            paper["paper_index"] = len(papers)                     # one running number over all files
            papers.append(paper)
    combined = {"mode": "multi", "reason": f"saved results of {len(paths)} files", "n_pages": pages, "papers": papers}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(combined, f, ensure_ascii=False)
    print(f"\nSaved {out}: {len(papers)} papers, {sum(p['reference_count'] for p in papers)} references, "
          f"{os.path.getsize(out) / 1e6:.1f} MB")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "samples")