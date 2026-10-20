r"""
Verify the references of ALL papers in a saved results file (arXiv IDs, DOIs, CrossRef search) and save the
verified results for the app:

    python run_validate_all.py coling_results.json you@example.com        (all papers; several hours for COLING)
    python run_validate_all.py coling_results.json you@example.com 50     (only the first 50 papers: a sample)

Safe to stop (Ctrl+C) and to start again: every real answer is remembered in lookup_cache.json and never asked twice.
Failed lookups (timeouts, throttling) are forgotten and asked again, in up to 3 passes.
Writes <input name>_validated.json -- open it in the app with "Open saved results (JSON)".
"""
import json
import os
import sys
import time

from refcheck.pipeline import count_statuses, lookup_plan, validate_papers

CACHE_FILE = "lookup_cache.json"
SAVE_EVERY = 200            # save the remembered answers after this many lookups
SHOW_EVERY = 100


def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(caches):
    snapshot = {name: dict(list(table.items())) for name, table in list(caches.items())}
    temporary = CACHE_FILE + ".tmp"
    with open(temporary, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False)
    os.replace(temporary, CACHE_FILE)                      # never leaves a half-written file


def failed_lookups(caches):
    """Number of remembered answers that are failures (a timeout, HTTP 429 ...), not real answers."""
    return sum(1 for table in caches.values() for v in table.values() if isinstance(v, dict) and v.get("status") == "error")


def forget_failures(caches):
    """A failed lookup says nothing about the reference; remove it so it is asked again."""
    removed = 0
    for table in caches.values():
        for key in [k for k, v in table.items() if isinstance(v, dict) and v.get("status") == "error"]:
            del table[key]
            removed += 1
    return removed


def main(path, mailto, limit=None):
    with open(path, encoding="utf-8") as f:
        analysis = json.load(f)
    caches = load_cache()
    remembered = sum(len(table) for table in caches.values())
    plan = lookup_plan(analysis, caches, limit)
    rate = 3 if mailto else 1
    minutes = (-(-plan["arxiv_ids"] // 40) * 3 + plan["dois"] / rate + plan["texts"] / rate) / 60
    print(f"{plan['references']} references. Still to look up: {plan['arxiv_ids']} arXiv IDs, {plan['dois']} DOIs, "
          f"{plan['texts']} texts ({remembered} answers already remembered). About {minutes:.0f} minutes.\n", flush=True)

    started, calls = time.time(), [0]
    forgotten = forget_failures(caches)
    if forgotten:
        print(f"Forgot {forgotten} failed lookups from an earlier run; they will be asked again.\n", flush=True)

    def progress(label, done, total):
        calls[0] += 1
        if done == total or done % SHOW_EVERY == 0:
            print(f"  {label}: {done} of {total}  ({(time.time() - started) / 60:.1f} min)", flush=True)
        if calls[0] % SAVE_EVERY == 0:
            save_cache(caches)

    try:
        for attempt in range(1, 4):                        # CrossRef sometimes refuses a few requests: ask again, up to 3 passes
            validate_papers(analysis, limit, mailto, caches, progress)
            failed = failed_lookups(caches)
            save_cache(caches)
            if not failed or attempt == 3:
                break
            print(f"\n{failed} lookups failed (probably throttling). Waiting 60 seconds, then asking those again ...", flush=True)
            time.sleep(60)
            forget_failures(caches)
    except KeyboardInterrupt:
        save_cache(caches)
        print("\nStopped. Run the same command again to continue; nothing already looked up is repeated.")
        return
    finally:
        save_cache(caches)

    out = os.path.splitext(path)[0] + "_validated.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False)
    counts = count_statuses(analysis)
    print(f"\nSaved {out} ({os.path.getsize(out) / 1e6:.1f} MB)")
    print("  " + " | ".join(f"{name}: {n}" for name, n in counts.items()))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: python run_validate_all.py coling_results.json your.name@example.com [number of papers]")
    else:
        main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else None)