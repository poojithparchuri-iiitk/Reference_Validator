r"""
Measure how well the reference extraction works, using arXiv papers as the ANSWER KEY.

For every arXiv paper the LaTeX source contains the exact bibliography (the .bbl file: one \bibitem per
reference). This script downloads the PDF and the source, counts the true references, runs our extractor on
the PDF and compares the two.

    python run_answer_key.py arxiv_ids.txt your.name@example.com
    python run_answer_key.py arxiv_ids.txt your.name@example.com 10        (only the first 10 papers)

arxiv_ids.txt: one arXiv ID per line (e.g. 1706.03762); text after # is ignored.

Politeness (arXiv asks for this): one connection, at least 5 seconds between requests, a User-Agent that names
you, back-off when arXiv says "slow down", and everything is cached in answer_key_cache\ so re-runs download
nothing. Keep that folder on your computer: do not publish it or commit it to GitHub.

Writes answer_key_report.txt (UTF-8) and answer_key_report.csv.
"""
import csv
import gzip
import io
import os
import re
import sys
import tarfile
import time
import unicodedata
from collections import Counter

import requests

from refcheck.pipeline import analyze_pdf

CACHE = "answer_key_cache"
MIN_GAP = 5.0                 # seconds between two requests to arXiv
MATCH_AT = 0.60               # share of a true reference's words that must be found in an extracted entry
LINES = []


def say(line=""):
    LINES.append(line)
    encoding = sys.stdout.encoding or "utf-8"
    print(line.encode(encoding, errors="replace").decode(encoding))


# ---------------------------------------------------------------- downloading

class TooManyRefusals(Exception):
    pass


class Downloader:
    """One request at a time, MIN_GAP seconds apart, with exponential back-off. Answers are cached on disk."""

    def __init__(self, email):
        self.headers = {"User-Agent": f"reference-validator-research/0.1 (mailto:{email})"}
        self.last = 0.0
        self.refusals = 0

    def _wait(self):
        wait = MIN_GAP - (time.monotonic() - self.last)
        if wait > 0:
            time.sleep(wait)
        self.last = time.monotonic()

    def get(self, url):
        """Returns (status_code, bytes). status 0 means a network error."""
        for attempt, pause in enumerate([0, 30, 60, 120]):
            if pause:
                time.sleep(pause)
            self._wait()
            try:
                response = requests.get(url, headers=self.headers, timeout=90)
            except requests.RequestException:
                return 0, b""
            if response.status_code in (429, 503):                 # "slow down"
                self.refusals += 1
                if self.refusals >= 3:
                    raise TooManyRefusals(url)
                continue
            self.refusals = 0
            return response.status_code, response.content
        raise TooManyRefusals(url)


def safe(arxiv_id):
    return arxiv_id.replace("/", "_")


def fetch_pdf(downloader, arxiv_id):
    path = os.path.join(CACHE, safe(arxiv_id) + ".pdf")
    if os.path.exists(path):
        return open(path, "rb").read(), ""
    status, data = downloader.get(f"https://arxiv.org/pdf/{arxiv_id}")
    if status != 200 or not data.startswith(b"%PDF"):
        return None, f"PDF download failed (HTTP {status})"
    with open(path, "wb") as f:
        f.write(data)
    return data, ""


def fetch_source(downloader, arxiv_id):
    path = os.path.join(CACHE, safe(arxiv_id) + ".src")
    missing = os.path.join(CACHE, safe(arxiv_id) + ".nosrc")
    if os.path.exists(path):
        return open(path, "rb").read(), ""
    if os.path.exists(missing):
        return None, open(missing, encoding="utf-8").read()
    status, data = downloader.get(f"https://arxiv.org/e-print/{arxiv_id}")
    reason = ""
    if status != 200:
        reason = f"source download failed (HTTP {status})"
    elif data.startswith(b"%PDF"):
        reason = "the author uploaded only a PDF, no LaTeX source"
    if reason:
        if status == 200 or status == 404:                         # a definite answer: remember it
            with open(missing, "w", encoding="utf-8") as f:
                f.write(reason)
        return None, reason
    with open(path, "wb") as f:
        f.write(data)
    return data, ""


# ---------------------------------------------------------- reading the source

def unpack_source(raw):
    """arXiv source = a tar(.gz) of files, or one gzipped .tex file. Returns {name: text}."""
    files = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:*") as archive:
            for member in archive.getmembers():
                if member.isfile() and member.name.lower().endswith((".bbl", ".tex")) and member.size < 8_000_000:
                    files[member.name] = archive.extractfile(member).read().decode("utf-8", errors="replace")
        return files
    except (tarfile.TarError, EOFError, OSError):
        pass
    try:
        files["main.tex"] = gzip.decompress(raw).decode("utf-8", errors="replace")
    except (OSError, EOFError):
        pass
    return files


# Accent commands. Symbol accents attach straight to a letter (\"o, \'{e}); letter accents need a brace or a space
# (\v{s}, \c c), otherwise "\url" would be read as the accent "\u" + "r".
_ACCENT = re.compile(r"\\(?:['\"`^~=.]\s*\{?\\?([A-Za-z])\}?|[uvHcdbtkr](?:\s+|\s*\{)\\?([A-Za-z])\}?)")
_BRACED_ACCENT = re.compile(r"\{\\(?:['\"`^~=.]\s*\{?\\?([A-Za-z])\}?|[uvHcdbtkr](?:\s+|\s*\{)\\?([A-Za-z])\}?)\}")


def _accent_letter(match):
    return match.group(1) or match.group(2)


_UNWRAP = [
    re.compile(r"\\(?:bibfnamefont|bibnamefont|textbf|textit|textsc|textrm|emph|mbox|natexlab|path)\s*\{([^{}]*)\}"),
    re.compile(r"\\(?:bibinfo|bibfield)\s*\{[^{}]*\}\s*\{([^{}]*)\}"),                  # \bibinfo{journal}{Nature} -> Nature
    re.compile(r"\\href(?:@noop)?\s*\{[^{}]*\}\s*\{([^{}]*)\}"),
    re.compile(r"\\url\s*\{([^{}]*)\}"),
    re.compile(r"\{\\(?:em|it|bf|sc|rm|sf|tt)\s+([^{}]*)\}"),                          # {\em words}
]


def latex_to_text(chunk):
    """Good-enough LaTeX -> plain text for comparing words (plain, natbib, REVTeX and ACM bibliographies)."""
    text = re.sub(r"(?m)^\s*%.*$", " ", chunk)
    text = re.sub(r"\\(?:BibitemOpen|endbibitem|@noop)|\\BibitemShut\s*\{[^{}]*\}", " ", text)
    text = text.replace("\\newblock", " ").replace("\\\\", " ")
    for _ in range(12):                                                            # unwrap macros from the inside out
        before = text
        for pattern in _UNWRAP:
            text = pattern.sub(r"\1", text)
        if text == before:
            break
    text = _BRACED_ACCENT.sub(_accent_letter, text)                                # {\'e} -> e   {\"o} -> o   {\c c} -> c
    text = _ACCENT.sub(_accent_letter, text)                                       # \"o -> o   \'{e} -> e
    text = text.replace("~", " ")                                                  # a tie (Andrew~M) is a space; AFTER the accents (\~n)
    text = re.sub(r"\\(?:ss)\b", "ss", text)
    text = re.sub(r"\\([oOlL]|ae|AE|oe|OE|i|j)\b", r"\1", text)                    # \o  \l  \ae  \i  \j
    text = re.sub(r"\\&", "&", text)
    text = re.sub(r"\\[A-Za-z]+\*?", " ", text)                                   # any other command
    text = re.sub(r"[{}$\\]", "", text)
    return " ".join(text.replace("--", "-").split())


def _skip_group(text, i, open_char, close_char):
    """Index just after the group that opens at text[i], counting nested groups."""
    depth = 0
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == open_char:
            depth += 1
        elif text[i] == close_char:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return i


def strip_bibitem_header(chunk):
    """Remove the optional [label] and the {key} that follow \\bibitem, however they are nested or commented."""
    def skip_blank(i):
        while i < len(chunk) and (chunk[i].isspace() or chunk[i] == "%"):
            if chunk[i] == "%":
                while i < len(chunk) and chunk[i] != "\n":
                    i += 1
            else:
                i += 1
        return i
    i = skip_blank(0)
    if i < len(chunk) and chunk[i] == "[":
        i = skip_blank(_skip_group(chunk, i, "[", "]"))
    if i < len(chunk) and chunk[i] == "{":
        i = _skip_group(chunk, i, "{", "}")
    return chunk[i:]


def parse_bibitems(text):
    """\\bibitem entries of a .bbl file or a thebibliography environment -> list of plain-text entries."""
    text = re.sub(r"(?m)^\s*%.*$", "", text)
    if "\\begin{thebibliography}" in text:
        text = text.split("\\begin{thebibliography}", 1)[1]
    text = text.split("\\end{thebibliography}", 1)[0]
    chunks = re.split(r"\\bibitem\b", text)[1:]
    return [latex_to_text(strip_bibitem_header(chunk)) for chunk in chunks]


def true_entries(files):
    """Returns (entries_or_None, note). entries is a list of plain-text strings, or [None]*n when only a count is known."""
    candidates = []
    for name, text in files.items():
        if name.lower().endswith(".bbl"):
            items = parse_bibitems(text)
            if items:
                candidates.append((len(items), name, items))
            else:
                count = len(re.findall(r"(?m)^\s*\\entry\{", text))          # biblatex
                if count:
                    candidates.append((count, name, [None] * count))
    if candidates:
        candidates.sort(key=lambda c: -c[0])
        note = f"{len(candidates)} .bbl files, used the largest" if len(candidates) > 1 else ""
        return candidates[0][2], note
    for name, text in files.items():
        if name.lower().endswith(".tex") and "\\begin{thebibliography}" in text:
            items = parse_bibitems(text)
            if items:
                return items, "bibliography typed inside the .tex file"
    return None, "no .bbl and no thebibliography in the source (only a .bib file?)"


# ------------------------------------------------------------------ comparing

def words(text):
    text = re.sub(r"(?:https?)?://\S+|doi:\s*\S+|arxiv:\s*\S+", " ", text, flags=re.IGNORECASE)   # links and IDs are broken differently in a PDF
    text = unicodedata.normalize("NFKD", text.lower())                 # ligatures (fi) and accents -> plain letters
    text = "".join(c for c in text if not unicodedata.combining(c))
    return set(re.findall(r"[a-z0-9]{3,}", text))


def compare(true_texts, ours):
    """How many true references are found in our entries, and how many of those are cleanly separated."""
    t_words = [words(t) for t in true_texts]
    o_words = [words(o) for o in ours]
    recovered = clean = 0
    missed, used, owners = [], set(), {}
    for ti, T in enumerate(t_words):
        if not T:
            continue
        best, best_oi, best_share_of_ours = 0.0, None, 0.0
        for oi, O in enumerate(o_words):
            shared = len(T & O)
            if shared and shared / len(T) > best:
                best, best_oi, best_share_of_ours = shared / len(T), oi, shared / len(O)
        if best >= MATCH_AT:
            recovered += 1
            used.add(best_oi)
            owners.setdefault(best_oi, []).append(ti)
            if best_share_of_ours >= MATCH_AT:                           # the entry is not much bigger than the true reference
                clean += 1
        else:
            missed.append((ti, best_oi if best >= 0.3 else None))
    extra = [oi for oi in range(len(ours)) if oi not in used]
    merged = {oi: tis for oi, tis in owners.items() if len(tis) >= 2}              # one entry of ours holds several true references
    return {"recovered": recovered, "clean": clean, "missed": missed, "extra": extra, "merged": merged}


# ----------------------------------------------------------------------- main

def read_ids(path):
    ids = []
    for line in open(path, encoding="utf-8"):
        value = line.split("#", 1)[0].strip()
        value = re.sub(r"^arxiv:", "", value, flags=re.I)
        value = re.sub(r"v\d+$", "", value)
        if value and value not in ids:
            ids.append(value)
    return ids


def _plain(text):
    text = unicodedata.normalize("NFKD", " ".join((text or "").split()))
    return "".join(c for c in text if not unicodedata.combining(c))


def junction(merged_entry, second_true_text):
    """Where the second true reference starts inside our merged entry: 50 characters before it, 190 from it."""
    flat, probe = _plain(merged_entry), _plain(second_true_text)
    for length in (20, 12):
        at = flat.lower().find(probe[:length].lower())
        if at > 0:
            return f"...{flat[max(0, at - 50):at]} >>> {flat[at:at + 190]}"
    return ""


def short(text, n):
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n - 1] + "~"


def main(ids_file, email, limit):
    os.makedirs(CACHE, exist_ok=True)
    ids = read_ids(ids_file)[:limit]
    downloader = Downloader(email)
    rows, details = [], []
    say(f"{len(ids)} papers. About {len(ids) * 2 * MIN_GAP / 60:.0f} minutes if nothing is cached yet.\n")

    for number, arxiv_id in enumerate(ids, 1):
        row = {"id": arxiv_id, "style": "", "true": "", "ours": "", "count_ok": "", "recovered_pct": "", "clean_pct": "",
               "extra": "", "merged": "", "audit": "", "note": ""}
        rows.append(row)
        try:
            pdf, problem = fetch_pdf(downloader, arxiv_id)
            if pdf is None:
                row["note"] = problem
                say(f"[{number}/{len(ids)}] {arxiv_id:<14} {problem}")
                continue
            raw, problem = fetch_source(downloader, arxiv_id)
        except TooManyRefusals as exc:
            say(f"\narXiv keeps refusing requests ({exc}). Stopping to be polite -- run the script again later; "
                f"everything downloaded so far is cached.")
            rows.pop()
            break

        analysis = analyze_pdf(pdf, "single")                       # an arXiv PDF is one paper, whatever its bookmarks look like
        paper = analysis["papers"][0]
        ours = [r["text"] for r in paper["references"]]
        warnings = [f["message"] for f in paper["audit"]["flags"] if f["level"] == "warning"]
        row.update({"style": paper["citation_style"], "ours": len(ours), "audit": "passed" if not warnings else f"{len(warnings)} warning(s)"})

        if raw is None:
            row["note"] = problem
            say(f"[{number}/{len(ids)}] {arxiv_id:<14} ours={len(ours):>3}  (no answer key: {problem})")
            continue
        truth, note = true_entries(unpack_source(raw))
        if truth is None:
            row["note"] = note
            say(f"[{number}/{len(ids)}] {arxiv_id:<14} ours={len(ours):>3}  (no answer key: {note})")
            continue

        row["true"] = len(truth)
        row["count_ok"] = "yes" if len(truth) == len(ours) else "no"
        row["note"] = note
        if truth[0] is None:
            row["note"] = (note + "; " if note else "") + "biblatex: count compared, entries not"
            say(f"[{number}/{len(ids)}] {arxiv_id:<14} true={len(truth):>3} ours={len(ours):>3} {paper['citation_style']:<12} count {'OK' if row['count_ok'] == 'yes' else 'DIFFERENT'}  audit {row['audit']}")
            continue

        result = compare(truth, ours)
        row["recovered_pct"] = round(100 * result["recovered"] / len(truth), 1)
        row["clean_pct"] = round(100 * result["clean"] / len(truth), 1)
        row["extra"] = len(result["extra"])
        row["merged"] = len(result["merged"])
        say(f"[{number}/{len(ids)}] {arxiv_id:<14} true={len(truth):>3} ours={len(ours):>3} {paper['citation_style']:<12} "
            f"found {row['recovered_pct']:>5}%  clean {row['clean_pct']:>5}%  audit {row['audit']}")
        if row["clean_pct"] < 95 or row["count_ok"] == "no":
            details.append((arxiv_id, paper["title"], truth, ours, result, warnings))

    comparable = [r for r in rows if r["recovered_pct"] != ""]
    say("\n" + "=" * 110)
    say("SUMMARY")
    say(f"  papers tried: {len(rows)} | with an answer key and comparable entries: {len(comparable)}")
    if comparable:
        total_true = sum(r["true"] for r in comparable)
        total_found = sum(round(r["true"] * r["recovered_pct"] / 100) for r in comparable)
        total_clean = sum(round(r["true"] * r["clean_pct"] / 100) for r in comparable)
        exact = sum(1 for r in comparable if r["count_ok"] == "yes")
        say(f"  same number of references as the answer key: {exact} of {len(comparable)} papers")
        say(f"  true references: {total_true} | found in our entries: {total_found} ({100 * total_found / total_true:.1f}%) | "
            f"found AND cleanly separated: {total_clean} ({100 * total_clean / total_true:.1f}%)")
        problem_rows = [r for r in comparable if r["clean_pct"] < 95 or r["count_ok"] == "no"]
        good_rows = [r for r in comparable if r not in problem_rows]
        flagged_problem = sum(1 for r in problem_rows if r["audit"] != "passed")
        flagged_good = sum(1 for r in good_rows if r["audit"] != "passed")
        say(f"  entries of ours that hold two or more true references (merged): {sum(r['merged'] for r in comparable)}")
        say(f"  papers with a problem (wrong count or under 95% clean): {len(problem_rows)} -- the audit warned on {flagged_problem} of them")
        say(f"  papers that were fine: {len(good_rows)} -- the audit raised a warning on {flagged_good} of them (false alarms)")
        by_style = Counter(r["style"] for r in comparable)
        for style in by_style:
            group = [r for r in comparable if r["style"] == style]
            say(f"    style {style:<12}: {len(group)} papers, mean 'clean' {sum(r['clean_pct'] for r in group) / len(group):.1f}%")
    skipped = [r for r in rows if r["recovered_pct"] == "" and r["note"]]
    if skipped:
        say("\nNOT COMPARED")
        for r in skipped:
            say(f"  {r['id']:<14} {r['note']}")

    if details:
        say("\n" + "=" * 110)
        say("PROBLEM PAPERS: what we missed (first 5 per paper), and what we invented")
        for arxiv_id, title, truth, ours, result, warnings in details:
            say(f"\n  {arxiv_id}  {short(title, 70)}  | true {len(truth)}, ours {len(ours)} | audit: {'; '.join(short(w, 70) for w in warnings[:2]) or 'no warning'}")
            for ti, oi in result["missed"][:5]:
                say(f"      MISSED  true #{ti + 1}: {short(truth[ti], 100)}")
                if oi is not None:
                    say(f"              closest of ours: {short(ours[oi], 100)}")
            for oi, tis in list(result["merged"].items())[:5]:
                say(f"      MERGED  one entry of ours holds {len(tis)} true references: {short(ours[oi], 95)}")
                for ti in tis[:3]:
                    say(f"                 true #{ti + 1}: {short(truth[ti], 80)}")
                where = junction(ours[oi], truth[tis[1]])
                if where:
                    say(f"                 junction: {where}")
            for oi in result["extra"][:3]:
                say(f"      EXTRA   ours: {short(ours[oi], 110)}")

    with open("answer_key_report.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(LINES))
    with open("answer_key_report.csv", "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print("\nSaved answer_key_report.txt and answer_key_report.csv")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: python run_answer_key.py arxiv_ids.txt your.name@example.com [how many papers]")
    else:
        main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 40)