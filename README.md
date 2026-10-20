# Reference Validator

A Streamlit app that reads a paper, or a whole conference proceedings PDF, splits it into papers, extracts each
paper's reference list, and checks every reference against arXiv, DOI registries (CrossRef, DataCite) and CrossRef
search. It also runs an *extraction audit* that flags lists that look incomplete or wrongly split. The app is generic:
any paper or proceedings PDF works. COLING 2025 was used as the large test case.

## What it does

1. **Splits a proceedings PDF into papers** using its bookmarks. If the PDF has none, it recognises each paper's title
   page from the layout (a title, then "Abstract").
2. **Extracts the references** of each paper. Handled styles: `[1]` numbered, `[Key]` keyed, `1.` dotted,
   author-year (ACL), authors-first (NeurIPS/ICML), `Authors (2019).` (APA), `Surname, I., 2015.` (Elsevier).
3. **Audits the extraction**: numbering gaps, lost citations (cited in the text but absent from the list), merged or
   duplicated entries, very short or very long entries, suspiciously few references.
4. **Validates each reference** (optional, needs internet): exact arXiv-ID and DOI lookups first, then a CrossRef
   title search (top 5 records, best title match). Result per reference: *Found*, *Check*, *Not found*, or *Error*,
   with the evidence shown: where it was found and as what kind of record (journal article, conference paper, book,
   preprint ...).
5. **Explains "Not found"**: each such reference is labelled from its wording as probably a web page, book, thesis,
   report, software, or a paper that these databases do not index.
6. **Exports** every reference with its label and the record found (title, authors, venue, type, year, DOI, source,
   title similarity) as CSV, and the full results as JSON.

## Install and run

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python -m streamlit run app.py
```

In the app, choose **Check a PDF** (then *Only extract* for a no-internet check, or *Validate references*), or
**Open saved results (JSON)** to browse results made earlier, for example for many files at once.
Entering your e-mail address makes CrossRef serve requests faster; it is sent only to CrossRef.

**Try it without running anything:** open `coling_first50_verified.json` with *Open saved results (JSON)*. It holds the
first 50 COLING 2025 papers with all 2,233 references verified.

## Command-line tools

| Script | Purpose |
|---|---|
| `run_batch.py <folder>` | Extraction + audit over every PDF in a folder, with a summary report |
| `run_export_all.py <folder>` | Same, saved as one JSON file the app can open |
| `run_validate_all.py <results.json> <email> [n]` | Verifies references (arXiv ID, DOI, CrossRef) for all papers or the first n. Resumable; failed lookups are retried |
| `run_answer_key.py <ids.txt> <email>` | Measures extraction accuracy on arXiv papers, using the LaTeX bibliography as the answer key |
| `run_inspect.py <pdf> [--paper N]` | Shows why one paper's list was read the way it was |
| `run_lookup.py`, `run_selftest.py` | Lookup checks |

Typical use for a proceedings volume cut into several PDFs:

```
python run_export_all.py samples\proceedings
python run_validate_all.py proceedings_results.json you@example.com
```

Then open `proceedings_results_validated.json` in the app. Verifying about 32,000 references takes several hours; the
run can be stopped and started again without repeating any lookup.

## Use it from your own code

```python
from refcheck.api import validate_reference_texts

results = validate_reference_texts(
    ["Ashish Vaswani, Noam Shazeer, et al. 2017. Attention is all you need. In NeurIPS."], "you@example.com")
print(results[0]["status"], results[0]["found_in"], results[0]["record_kind"])    # found CrossRef preprint
```

Each result has `status` (found, check, not_found, error), where it was found, the kind of record, the matched title,
authors, year and DOI, and, for not-found references, a `probable_kind` (web page, book, thesis, report, software, or
a paper that is not indexed) and the `closest_rejected_record` that was turned down. Pass the same `caches` dict to
every call to avoid repeating lookups.

## How well does it work?

**Extraction**, measured with `run_answer_key.py` (the true bibliography from the arXiv LaTeX source):

| Test set | Papers | References found | Found as their own clean entry |
|---|---|---|---|
| Development (the extractor was tuned on these) | 29 | 99.8% | 98.9% |
| **Hold-out (never seen during tuning)** | 30 | 97.4% | 71.7% overall; median paper 99.7% |

The hold-out figure is the honest one. Two astronomy collaboration papers (Planck 2015 and 2018, 736 references in a
style with no period after the authors) account for 88% of the hold-out failures. Without them the clean rate is 94.7%;
for the 25 machine-learning and NLP papers it is 93.9%, with 20 of 25 papers at 95% or better.

**COLING 2025** (no answer key available): all 757 papers were found (32,154 references), a reference list was located
by heading in 756, and no paper came out with zero references. The extraction audit passed 392 of 757 papers; its
warnings are triage hints (on arXiv it caught 6 of 7 and 7 of 8 problem papers, with about a third of fine papers
flagged anyway).

**Validation** on the first 50 COLING 2025 papers (2,233 references, live lookups):

| | Count | Share |
|---|---|---|
| Found | 1,702 | 76.2% |
| Check | 173 | 7.7% |
| Not found | 358 | 16.0% |
| Error | 0 | 0% |

Found by: arXiv ID 563, CrossRef search 1,139.

Matching rules (word comparison, no similarity model, no guessing): the record's title must match the reference text
word for word at 0.90 or more to count as *Found*; 0.65 to 0.90 is *Check*. A short or inexact title must also share an
author with the reference, and the year may differ by at most 1 (not applied to arXiv copies, whose date is that of
their latest version), otherwise the result is *Check*. CrossRef is asked for its top 5 records and the best title
match is kept.

*Not found* does not mean a reference is wrong. It means none of the sources holds a record with that title: workshop
proceedings (CEUR-WS), JMLR/PMLR papers, web pages, software, reports, books and theses are common causes. Reading a
sample of 15 showed no extraction errors; the matcher also correctly rejects look-alike records, for example a record by
the same authors with a different title.

## Limitations

- *Found* means a source holds a record with a matching title. It is evidence that a reference exists, not proof that
  it is cited correctly.
- The comparison is by words, not meaning: a paper that was retitled between its preprint and published version, or a
  translated title, shows up as *Check* or *Not found*.
- The accuracy of the Found / Not found decisions themselves has not been measured against a hand-labelled sample.
- Reference styles outside the list above (for example astronomy's `Surname, I., Title. Year, Journal` with no period)
  are split poorly. Organisations as authors written in lower case, and typos in a paper's own bibliography, can
  merge or split entries; the audit usually flags these.
- Layout-based paper detection (PDFs without bookmarks) is tuned to ACL-style first pages and can miss papers whose
  first page has no "Abstract".
- Scanned PDFs without a text layer are not supported (no OCR).

## Privacy

PDFs are processed on your computer. Only reference text, titles, DOIs and arXiv IDs are sent to arXiv, CrossRef and
DataCite when you validate.