"""
arxiv.py -- look arXiv identifiers up on arXiv itself.

arXiv's public API takes a list of IDs and returns one record per ID that exists (title, authors,
date), so this is an exact lookup. Many IDs can be asked for in ONE request, and arXiv asks for at
most one request every 3 seconds, so IDs are sent in batches.

Every ID gets one of three statuses:
    found       arXiv has this ID (the record is returned)
    not_found   arXiv has no paper with this ID
    error       the request failed after retries
"""
import re
import time
import xml.etree.ElementTree as ET

import requests

API_URL = "https://export.arxiv.org/api/query"
BATCH_SIZE = 40
PAUSE_SECONDS = 3.0
_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"


def _clean(text):
    return " ".join((text or "").split()) or None


def parse_feed(xml_text):
    """Atom feed -> ({arxiv_id: record}, had_error_entry). IDs come back without the version suffix."""
    root = ET.fromstring(xml_text)
    records, had_error = {}, False
    for entry in root.findall(f"{_ATOM}entry"):
        id_url = entry.findtext(f"{_ATOM}id") or ""
        if "/api/errors" in id_url:                    # arXiv reports a malformed ID as an entry titled "Error"
            had_error = True
            continue
        match = re.search(r"/abs/(.+?)(?:v\d+)?$", id_url.strip())
        if not match:
            continue
        published = entry.findtext(f"{_ATOM}published") or ""
        records[match.group(1)] = {
            "title": _clean(entry.findtext(f"{_ATOM}title")),
            "authors": [_clean(a.findtext(f"{_ATOM}name")) for a in entry.findall(f"{_ATOM}author")
                        if _clean(a.findtext(f"{_ATOM}name"))],
            "year": int(published[:4]) if published[:4].isdigit() else None,
            "venue": _clean(entry.findtext(f"{_ARXIV}journal_ref")) or "arXiv preprint",
            "doi": _clean(entry.findtext(f"{_ARXIV}doi")),
            "url": id_url.strip(),
        }
    return records, had_error


def _result(status, record=None, error=None):
    record = record or {}
    return {"status": status, "title": record.get("title"), "authors": record.get("authors", []),
            "year": record.get("year"), "venue": record.get("venue"), "doi": record.get("doi"),
            "url": record.get("url"), "error": error}


def _request(ids, mailto, max_retries=3, timeout=30):
    """One API call for a list of IDs. Returns (records, had_error, error_message)."""
    headers = {"User-Agent": "proceedings-reference-checker/0.1" + (f" (mailto:{mailto})" if mailto else "")}
    params = {"id_list": ",".join(ids), "max_results": len(ids)}
    last_error = "unknown error"
    for attempt in range(max_retries):
        try:
            response = requests.get(API_URL, params=params, headers=headers, timeout=timeout)
            if response.status_code == 200:
                records, had_error = parse_feed(response.text)
                return records, had_error, None
            last_error = f"HTTP {response.status_code}"
        except Exception as exc:                       # network error, malformed XML, ...
            last_error = str(exc)
        if attempt < max_retries - 1:
            time.sleep(PAUSE_SECONDS * (attempt + 1))
    return {}, False, last_error


def check_ids(ids, mailto="", progress=None, cache=None):
    """
    Look up arXiv IDs. Returns {id: result dict}. IDs already in `cache` are not asked for again;
    `progress(done, total)` is called after every request.
    """
    cache = {} if cache is None else cache
    todo = [i for i in dict.fromkeys(ids) if i not in cache]
    batches = [todo[k:k + BATCH_SIZE] for k in range(0, len(todo), BATCH_SIZE)]
    done_ids, requests_made = 0, 0

    def ask(batch):
        nonlocal requests_made
        if requests_made:
            time.sleep(PAUSE_SECONDS)                  # arXiv asks for one request per 3 seconds
        requests_made += 1
        return _request(batch, mailto)

    for batch in batches:
        records, had_error, error = ask(batch)
        if error:
            for i in batch:
                cache[i] = _result("error", error=error)
        else:
            if had_error and len(batch) > 1 and not records:
                # one malformed ID can spoil a batch: ask for each ID on its own
                for i in batch:
                    single, _, single_error = ask([i])
                    cache[i] = (_result("error", error=single_error) if single_error
                                else _result("found", single[i]) if i in single else _result("not_found"))
            else:
                for i in batch:
                    cache[i] = _result("found", records[i]) if i in records else _result("not_found")
        done_ids += len(batch)
        if progress:
            progress(done_ids, len(todo))
    return {i: cache[i] for i in ids}