r"""
Second chance for references still "not found": ask OpenAlex (it covers venues CrossRef misses: PMLR, CEUR-WS, ...).

    python run_openalex.py coling_results_validated.json YOUR_OPENALEX_KEY [max searches, default 900]

Free key: make an account at openalex.org, copy the key from openalex.org/settings/api.
The free budget is about 1,000 searches per day: if it runs out, run the same command tomorrow (answers are remembered).
Writes <input name>_openalex.json -- open it in the app.
"""
import json
import os
import re
import sys
import time

import requests

from refcheck.matching import judge_match
from refcheck.pipeline import count_statuses

URL = "https://api.openalex.org/works"
CACHE_FILE = "openalex_cache.json"
VERY_LONG_ENTRY = 1500


def record_from(work):
    source = ((work.get("primary_location") or {}).get("source") or {}).get("display_name")
    return {"title": work.get("display_name") or work.get("title"),
            "authors": [(a.get("author") or {}).get("display_name") for a in (work.get("authorships") or [])
                        if (a.get("author") or {}).get("display_name")][:50],
            "year": work.get("publication_year"), "venue": source, "type": work.get("type"),
            "doi": (work.get("doi") or "").replace("https://doi.org/", "") or None}


def clean_query(text):
    """Letters, digits and spaces only, in lower case: quotes, brackets, colons and AND/OR/NOT are query syntax for OpenAlex."""
    return " ".join(re.sub(r"[^\w\s]|_", " ", text).lower().split())[:250]


def search(text, key):
    """Up to 5 candidate records, or None if the daily budget is used up. Raises on other failures."""
    last = "unknown"
    for attempt in range(3):
        try:
            response = requests.get(URL, params={"search": clean_query(text), "per_page": 5, "api_key": key}, timeout=30)
        except requests.RequestException as exc:                  # a timeout or a dropped connection: try again
            last = type(exc).__name__
            time.sleep(2 + attempt)
            continue
        if response.status_code == 429:
            return None
        if response.status_code == 200:
            return [record_from(w) for w in response.json().get("results", [])]
        last = f"HTTP {response.status_code}"
        time.sleep(1 + attempt)
    raise RuntimeError(last)


def main(path, key, limit=900):
    analysis = json.load(open(path, encoding="utf-8"))
    cache = json.load(open(CACHE_FILE, encoding="utf-8")) if os.path.exists(CACHE_FILE) else {}
    refs = [r for p in analysis["papers"] for r in p["references"] if r["status"] == "not_found"]
    todo = list(dict.fromkeys(r["text"] for r in refs if r["text"] not in cache))
    print(f"{len(refs)} references are 'not found'; {len(todo)} still to ask OpenAlex (budget this run: {limit}).", flush=True)
    asked, exhausted = 0, False
    try:
        for text in todo[:limit]:
            try:
                candidates = search(text, key)
            except Exception as exc:
                print(f"  a search failed ({exc}); it will be asked again next time")
                continue
            if candidates is None:
                exhausted = True
                break
            cache[text] = candidates
            asked += 1
            if asked % 100 == 0:
                print(f"  {asked} of {min(limit, len(todo))}", flush=True)
                json.dump(cache, open(CACHE_FILE, "w", encoding="utf-8"), ensure_ascii=False)
            time.sleep(0.15)
    finally:
        json.dump(cache, open(CACHE_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    if exhausted:
        print("The daily OpenAlex budget is used up. Run the same command tomorrow to continue.")

    changed = 0
    for ref in refs:
        best = None
        for record in cache.get(ref["text"], []):
            verdict, similarity, note = judge_match(ref["text"], record)
            if verdict == "match" and len(ref["text"]) > VERY_LONG_ENTRY:
                verdict, note = "check", "Very long entry, probably several references merged; the match may cover only part of it."
            rank = {"match": 2, "check": 1}.get(verdict, 0)
            if rank and (best is None or (rank, similarity) > (best[0], best[1])):
                best = (rank, similarity, verdict, note, record)
        if best:
            _, similarity, verdict, note, record = best
            note = note.replace("CrossRef's", "OpenAlex's").replace("CrossRef says", "OpenAlex says")
            ref.update({"status": "found" if verdict == "match" else "check", "source": "OpenAlex search",
                        "match_title": record["title"], "authors": record["authors"], "year": record["year"],
                        "venue": record["venue"], "type": record["type"], "doi": record["doi"],
                        "title_similarity": round(similarity, 3), "note": note, "score": None})
            ref["evidence"].append({"source": "OpenAlex search", "verdict": verdict, "title_similarity": round(similarity, 3),
                                    "title": record["title"], "year": record["year"], "note": note})
            changed += 1

    out = os.path.splitext(path)[0] + "_openalex.json"
    json.dump(analysis, open(out, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"\nOpenAlex turned {changed} of {len(refs)} 'not found' references into found/check.")
    print(f"Saved {out}\n  " + " | ".join(f"{k}: {v}" for k, v in count_statuses(analysis).items()))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: python run_openalex.py results_validated.json YOUR_OPENALEX_KEY [max searches]")
    else:
        main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 900)