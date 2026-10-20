r"""
Look INSIDE one PDF's reference list to see why it was read wrongly:

    python run_inspect.py samples\batch\2020.acl-main.703.pdf
    python run_inspect.py samples\batch\N19-1423.pdf Deng ImageNet      (also look for these words)
    python run_inspect.py samples\coling10\papers_16-20.pdf --paper 1   (paper 1 of a file that holds several papers)

Writes inspect_<name>.txt (UTF-8) in the project folder. No internet needed.
"""
import os
import re
import sys

import pymupdf

from refcheck.references import (AUTHOR_YEAR_HEADER, _parse_apa, _parse_author_year, _parse_key_labels, _parse_numbered,
                                 _parse_numbered_dot, _trim_tail, clean_text, extract_references, find_bibliography_start)
from refcheck.splitter import paper_text, split_papers

LINES = []


def say(line=""):
    LINES.append(line)
    encoding = sys.stdout.encoding or "utf-8"
    print(line.encode(encoding, errors="replace").decode(encoding))


def main(path, words, paper=None):
    doc = pymupdf.open(path)
    if paper:                                              # one paper of a multi-paper file, split exactly as the app does
        spans, _, why = split_papers(doc, "auto")
        if not 1 <= paper <= len(spans):
            print(f"This file has {len(spans)} paper(s); --paper {paper} does not exist.")
            return
        span = spans[paper - 1]
        say(f"PAPER {paper} of {len(spans)}: {span.title[:80]} | pages {span.start_page + 1}-{span.end_page + 1} | {why}")
    else:
        spans, _, _ = split_papers(doc, "single")
        span = spans[0]
    raw = paper_text(doc, span)
    text = clean_text(raw)
    start, method = find_bibliography_start(text)
    say(f"FILE: {os.path.basename(path)} | pages: {span.n_pages} | text: {len(text)} characters")
    if start is None:
        say("No reference list was located.")
        return
    block = _trim_tail(text[start:])
    say(f"reference list located by: {method} | starts at character {start} of {len(text)} | length: {len(block)} characters\n")

    say("HOW MANY ENTRIES EACH PARSER FINDS")
    for name, parser in [("[1] numbered", _parse_numbered), ("[Key] keyed", _parse_key_labels), ("1. dotted", _parse_numbered_dot),
                         ("author-year", _parse_author_year), ("APA", _parse_apa)]:
        found = parser(block)
        say(f"  {name:<14} {0 if not found else len(found)}")
    headers = list(AUTHOR_YEAR_HEADER.finditer(block))
    say(f"  author-year headers matched in the block: {len(headers)}")
    for m in headers[:4]:
        say(f"      header: {m.group(1)[:100]}")

    result = extract_references(raw)
    say(f"\nWHAT THE APP DOES: style = {result.style}, {len(result.entries)} entries")
    for label, entry in result.entries[:3]:
        say(f"  first  [{label}] ({len(entry)} chars) {entry[:160]}")
    for label, entry in result.entries[-2:]:
        say(f"  last   [{label}] ({len(entry)} chars) {entry[:160]}")
    for word in words:
        say(f"\nENTRIES THE APP BUILT THAT CONTAIN '{word}'")
        hits = [(label, entry) for label, entry in result.entries if word.lower() in entry.lower()]
        say(f"  {len(hits)} entr{'y' if len(hits) == 1 else 'ies'}")
        for label, entry in hits[:6]:
            at = entry.lower().find(word.lower())
            say(f"   [{label}] ({len(entry)} chars; '{word}' at character {at}) {entry[:200]}")

    say("\nTHE FIRST 700 CHARACTERS OF THE LIST (raw)")
    say(block[:700])
    say("\nTHE LAST 500 CHARACTERS OF THE LIST (raw)")
    say(block[-500:])

    for word in words:
        say(f"\nRAW TEXT AROUND '{word}' INSIDE THE LIST")
        hits = [m.start() for m in re.finditer(re.escape(word), block)]
        say(f"  {len(hits)} hit(s)")
        for h in hits[:5]:
            say("   ..." + block[max(0, h - 150):h + 250] + "...")

    name = "inspect_" + os.path.splitext(os.path.basename(path))[0] + (f"_paper{paper}" if paper else "") + ".txt"
    with open(name, "w", encoding="utf-8") as f:
        f.write("\n".join(LINES))
    print(f"\nSaved {name}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python run_inspect.py file.pdf [--paper N] [word ...]")
    else:
        args = sys.argv[2:]
        paper = None
        if "--paper" in args:
            at = args.index("--paper")
            paper = int(args[at + 1])
            args = args[:at] + args[at + 2:]
        main(sys.argv[1], args, paper)