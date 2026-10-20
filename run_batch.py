"""
Check how well the reference extraction works on MANY papers at once:

    python run_batch.py samples\batch

Reads every PDF in the folder (a proceedings volume counts as many papers). No internet needed.
Writes batch_report.txt (UTF-8) and batch_report.csv next to the script.
"""
import csv
import glob
import os
import sys
import time
from collections import Counter

from refcheck.pipeline import analyze_pdf

LINES = []


def say(line=""):
    LINES.append(line)
    encoding = sys.stdout.encoding or "utf-8"
    print(line.encode(encoding, errors="replace").decode(encoding))


def progress(line):
    """A progress line on the screen only (not in the report)."""
    encoding = sys.stdout.encoding or "utf-8"
    print(line.encode(encoding, errors="replace").decode(encoding), flush=True)


def short(text, n):
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n - 1] + "~"


def main(folder):
    paths = sorted(glob.glob(os.path.join(folder, "*.pdf")))
    if not paths:
        print(f"No PDF files found in {folder}")
        return

    rows, problems = [], []
    kinds = Counter()                      # audit warning kind -> number of papers affected
    started = time.time()
    for number, path in enumerate(paths, 1):
        name = os.path.basename(path)
        elapsed = time.time() - started
        left = f", about {elapsed / (number - 1) * (len(paths) - number + 1) / 60:.0f} min left" if number > 3 else ""
        progress(f"[{number}/{len(paths)}] {name}  ({elapsed / 60:.1f} min so far{left})")
        try:
            with open(path, "rb") as f:
                analysis = analyze_pdf(f.read())
        except Exception as exc:                                  # encrypted, damaged, not really a PDF ...
            rows.append({"file": name, "paper": "-", "title": "", "pages": "", "refs": 0, "style": "-", "located": "-",
                         "audit": "ERROR", "first_warning": str(exc)[:80], "first_entry": "", "last_entry": ""})
            problems.append((name, "-", [f"Could not read the PDF: {exc}"]))
            continue

        for p in analysis["papers"]:
            warnings = [f["message"] for f in p["audit"]["flags"] if f["level"] == "warning"]
            kinds.update({f["code"] for f in p["audit"]["flags"] if f["level"] == "warning"})
            refs = p["references"]
            rows.append({"file": name, "paper": p["paper_index"] + 1, "title": short(p["title"], 40), "pages": p["pages"],
                         "refs": p["reference_count"], "style": p["citation_style"], "located": p["detection_method"],
                         "audit": "passed" if not warnings else f"{len(warnings)} warning(s)",
                         "first_warning": short(warnings[0], 80) if warnings else "",
                         "first_entry": short(refs[0]["text"], 50) if refs else "",
                         "last_entry": short(refs[-1]["text"], 50) if refs else ""})
            issues = list(warnings)
            if p["reference_count"] == 0:
                issues.insert(0, "NO references were extracted.")
            elif p["reference_count"] <= 5:
                issues.insert(0, f"Only {p['reference_count']} references -- unusually few.")
            if not p["reliable"] and p["note"]:
                issues.append(p["note"])
            if issues:
                problems.append((name, p["paper_index"] + 1, issues))

    say(f"{len(rows)} paper(s) from {len(paths)} PDF file(s), {time.time() - started:.0f} seconds\n")
    say(f"{'file':<24}{'#':>3} {'refs':>5}  {'style':<12}{'located by':<16}{'audit':<14}first warning")
    say("-" * 120)
    for r in rows:
        say(f"{short(r['file'], 22):<24}{str(r['paper']):>3} {r['refs']:>5}  {r['style']:<12}{r['located']:<16}{r['audit']:<14}{r['first_warning']}")

    say("\n" + "=" * 120)
    say("SUMMARY")
    say(f"  papers: {len(rows)} | references: {sum(r['refs'] for r in rows)}")
    say(f"  styles: {dict(Counter(r['style'] for r in rows))}")
    say(f"  reference list located by: {dict(Counter(r['located'] for r in rows))}")
    say(f"  audit passed: {sum(1 for r in rows if r['audit'] == 'passed')} of {len(rows)}")
    say(f"  no references at all: {sum(1 for r in rows if r['refs'] == 0)} | 5 or fewer: {sum(1 for r in rows if 0 < r['refs'] <= 5)}")
    if rows:
        counts = sorted(r["refs"] for r in rows)
        say(f"  references per paper: median {counts[len(counts) // 2]}, smallest {counts[0]}, largest {counts[-1]}")
    names = {"long_entry": "very long entry (maybe two references merged)", "cited_not_listed": "cited in the text but not in the list (maybe lost)",
             "duplicate": "the same reference twice", "short_entry": "very short entry (a fragment)", "not_split": "list not split into references",
             "no_references": "no references found", "gap": "numbering gap", "start": "numbered list does not start at 1",
             "weak_location": "list found by a weak method"}
    if kinds:
        say("  audit warnings by kind (number of papers affected):")
        for code, n in kinds.most_common():
            say(f"      {n:>4}  {names.get(code, code)}")

    if problems:
        say("\nNEEDS ATTENTION (open these PDFs and compare with the list)")
        for name, number, issues in problems:
            say(f"  {name}" + (f" (paper {number})" if number != "-" else ""))
            for issue in issues[:4]:
                say(f"      - {short(issue, 150)}")

    say("\nFIRST AND LAST ENTRY OF EACH PAPER (the list should begin and end where the PDF's list does)")
    for r in rows:
        if r["refs"]:
            say(f"  {short(r['file'], 22)} #{r['paper']}")
            say(f"      first: {r['first_entry']}")
            say(f"      last : {r['last_entry']}")

    with open("batch_report.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(LINES))
    with open("batch_report.csv", "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print("\nSaved batch_report.txt and batch_report.csv")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "samples")