"""
crossref.py -- look references up on CrossRef (free API), politely.

* CrossRef allows 3 requests/second if you identify yourself with an e-mail address
  (the "polite pool") and only 1 request/second, one at a time, if you do not.
  Sending more makes the API reject almost everything, so requests are rate limited here.
* Every reference gets one of three statuses:
      found      CrossRef returned a candidate record (it is the NEAREST match, not proof it is the right paper)
      not_found  CrossRef returned nothing
      error      the request failed after retries (network problem, rate limit, ...)
"""
import html
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote

import requests

API_URL = "https://api.crossref.org/works"
DATACITE_URL = "https://api.datacite.org/dois/"
HANDLE_URL = "https://doi.org/api/handles/"
MAX_QUERY_CHARS = 1000


class RateLimiter:
    """Lets at most `per_second` requests start per second, across all threads."""

    def __init__(self, per_second):
        self.interval = 1.0 / per_second
        self._lock = threading.Lock()
        self._next = time.monotonic()

    def wait(self):
        with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next - now)
            self._next = max(now, self._next) + self.interval
        if delay > 0:
            time.sleep(delay)


def _clean(text):
    """CrossRef titles can contain markup (<i>..</i>), HTML entities (&amp;) and line breaks."""
    if not text:
        return None
    text = re.sub(r"<[^>]+>", "", text)
    return " ".join(html.unescape(text).split()) or None


def _authors(item, limit=50):
    """['Given Family', ...] from a CrossRef record (organisations use their 'name')."""
    names = []
    for person in (item.get("author") or [])[:limit]:
        name = _clean(f"{person.get('given', '')} {person.get('family', '')}".strip() or person.get("name", ""))
        if name:
            names.append(name)
    return names


def _year(item):
    """Publication year from the first date field that has one."""
    for key in ("issued", "published-print", "published-online", "created"):
        parts = (item.get(key) or {}).get("date-parts") or [[]]
        if parts and parts[0] and parts[0][0]:
            return parts[0][0]
    return None


def _record(status, item=None, error=None):
    """One result dict. Keys are always the same so callers never need to check for missing ones."""
    item = item or {}
    return {"status": status,
            "title": _clean((item.get("title") or [""])[0]),
            "authors": _authors(item),
            "year": _year(item),
            "venue": _clean((item.get("container-title") or [""])[0]),
            "publisher": _clean(item.get("publisher")),
            "type": item.get("type"),
            "doi": item.get("DOI"),
            "score": item.get("score", 0) if status == "found" else (0 if status == "not_found" else None),
            "error": error}


def check_reference(text, mailto="", limiter=None, max_retries=3, timeout=15):
    """Look up ONE reference. Returns a dict: status, title, authors, year, venue, publisher, type, doi, score, error."""
    params = {"query.bibliographic": text[:MAX_QUERY_CHARS], "rows": 1}
    agent = "proceedings-reference-checker/0.1"
    if mailto:
        params["mailto"] = mailto
        agent += f" (mailto:{mailto})"
    headers = {"User-Agent": agent}

    last_error = "unknown error"
    for attempt in range(max_retries):
        if limiter:
            limiter.wait()
        try:
            response = requests.get(API_URL, params=params, headers=headers, timeout=timeout)
            if response.status_code == 429:
                last_error = "HTTP 429 (rate limited)"
                time.sleep(1.0 * (attempt + 1))
                continue
            if response.status_code != 200:
                last_error = f"HTTP {response.status_code}"
                time.sleep(0.5)
                continue
            items = response.json()["message"]["items"]
            if not items:
                return _record("not_found")
            return _record("found", items[0])
        except Exception as exc:                      # network error, bad JSON, ...
            last_error = str(exc)
            time.sleep(0.5)
    return _record("error", error=last_error)


def _lookup_parallel(keys, worker, workers, progress, cache):
    """
    Run worker(key) for every key not yet in `cache`, a few at a time. `progress(done, total)` is called
    after each one. If the run is interrupted (the page was touched, the tab was closed), lookups that
    have not started yet are cancelled; the ones finished so far stay in `cache`.
    """
    todo = [k for k in dict.fromkeys(keys) if k not in cache]
    if todo:
        done = 0
        pool = ThreadPoolExecutor(max_workers=workers)
        try:
            futures = {pool.submit(worker, k): k for k in todo}
            for future in as_completed(futures):
                cache[futures[future]] = future.result()
                done += 1
                if progress:
                    progress(done, len(todo))
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
    return [cache[k] for k in keys]


def check_many(texts, mailto="", progress=None, cache=None):
    """
    Look up many references by their text. Identical texts are looked up once (the `cache` dict can be
    shared across papers). `progress(done, total)` is called after each lookup.
    Returns a list of result dicts in the same order as `texts`.
    """
    cache = {} if cache is None else cache
    limiter = RateLimiter(3 if mailto else 1)
    return _lookup_parallel(texts, lambda t: check_reference(t, mailto, limiter),
                            3 if mailto else 1, progress, cache)


# ---------------------------------------------------------------- DOI lookups

def _doi_result(status, source=None, item=None, error=None):
    """Same keys for every DOI result. status: found / exists / not_found / error."""
    item = item or {}
    return {"status": status, "source": source, "title": item.get("title"), "authors": item.get("authors", []),
            "year": item.get("year"), "venue": item.get("venue"), "publisher": item.get("publisher"),
            "type": item.get("type"), "doi": item.get("doi"), "error": error}


def _from_crossref(message):
    record = _record("found", message)
    return {k: record[k] for k in ("title", "authors", "year", "venue", "publisher", "type", "doi")}


def _from_datacite(data):
    attrs = (data.get("data") or {}).get("attributes") or {}
    titles = attrs.get("titles") or []
    authors = []
    for creator in attrs.get("creators") or []:
        name = _clean(f"{creator.get('givenName', '')} {creator.get('familyName', '')}".strip() or creator.get("name", ""))
        if name:
            authors.append(name)
    publisher = attrs.get("publisher")
    if isinstance(publisher, dict):
        publisher = publisher.get("name")
    return {"title": _clean(titles[0].get("title")) if titles else None, "authors": authors,
            "year": attrs.get("publicationYear"), "venue": _clean((attrs.get("container") or {}).get("title")),
            "publisher": _clean(publisher), "type": ((attrs.get("types") or {}).get("resourceTypeGeneral") or "").lower() or None,
            "doi": attrs.get("doi")}


def check_doi(doi, mailto="", limiter=None, max_retries=3, timeout=15):
    """
    Look up ONE DOI exactly: CrossRef first, then DataCite (arXiv-style, Zenodo and dataset DOIs live there),
    then the DOI registry itself, which can say that a DOI exists even when nobody shares its details.
        found       a record with details was returned (see "source")
        exists      the DOI is registered but no details are available
        not_found   no such DOI anywhere
        error       a request failed after retries
    """
    agent = "proceedings-reference-checker/0.1" + (f" (mailto:{mailto})" if mailto else "")
    headers = {"User-Agent": agent}
    quoted = quote(doi, safe="/")

    def fetch(url, params=None):
        """(http status, parsed json or None, error). 200 and 404 are answers; anything else is retried."""
        last_error = "unknown error"
        for attempt in range(max_retries):
            if limiter:
                limiter.wait()
            try:
                response = requests.get(url, params=params, headers=headers, timeout=timeout)
                if response.status_code == 200:
                    return 200, response.json(), None
                if response.status_code == 404:
                    return 404, None, None
                last_error = f"HTTP {response.status_code}"
                time.sleep(1.0 * (attempt + 1) if response.status_code == 429 else 0.5)
            except Exception as exc:
                last_error = str(exc)
                time.sleep(0.5)
        return None, None, last_error

    code, data, error = fetch(f"{API_URL}/{quoted}", {"mailto": mailto} if mailto else None)
    if code == 200:
        return _doi_result("found", "CrossRef", _from_crossref(data["message"]))
    if code is None:
        return _doi_result("error", error=error)

    code, data, error = fetch(DATACITE_URL + quoted)
    if code == 200:
        return _doi_result("found", "DataCite", _from_datacite(data))
    if code is None:
        return _doi_result("error", error=error)

    code, data, error = fetch(HANDLE_URL + quoted)
    if code == 200 and data.get("responseCode") == 1:
        return _doi_result("exists", "doi.org", {"doi": doi})
    if code is None:
        return _doi_result("error", error=error)
    return _doi_result("not_found")


def check_dois(dois, mailto="", progress=None, cache=None):
    """Look up many DOIs (each once). Returns {doi: result dict}."""
    cache = {} if cache is None else cache
    limiter = RateLimiter(3 if mailto else 1)
    _lookup_parallel(dois, lambda d: check_doi(d, mailto, limiter), 3 if mailto else 1, progress, cache)
    return {d: cache[d] for d in dois}