# Reference Validator

A Streamlit app that reads a paper, or a whole conference proceedings PDF, splits it into papers, extracts each
paper's reference list, and checks every reference against arXiv, DOI registries (CrossRef, DataCite), CrossRef
search and, as a second chance, OpenAlex. It also runs an *extraction audit* that flags lists that look incomplete or
wrongly split. The app is generic: any paper or proceedings PDF works. COLING 2025 was used as the large test case.

## What it does

1. **Splits a proceedings PDF into papers** using its bookmarks. If the PDF has none, it recognises each paper's title
   page from the layout (a title, then "Abstract").
2. **Extracts the references** of each paper. Handled styles: `[1]` numbered, `[Key]` keyed, `1.` dotted,
   author-year (ACL), authors-first (NeurIPS/ICML), `Authors (2019).` (APA), `Surname, I., 2015.` (Elsevier).
3. **Audits the extraction**: numbering gaps, lost citations (cited in the text but absent from the list), merged or
   duplicated entries, very short or very long entries, suspiciously few references.
4. **Validates each reference** (optional, needs internet): exact arXiv-ID and DOI lookups first, then a CrossRef
   title search; references still not found can be tried on OpenAlex. Result per reference: *Found*, *Check*,
   *Not found*, or *Error*, with the evidence shown.
5. **Exports** every reference with its label and the record found (title, authors, venue, type, year, DOI, source,
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
| `run_openalex.py <validated.json> <key> [max]` | Asks OpenAlex about the references still *not found*. Needs a free OpenAlex API key (about 1,000 searches per day) |
| `run_answer_key.py <ids.txt> <email>` | Measures extraction accuracy on arXiv papers, using the LaTeX bibliography as the answer key |
| `run_inspect.py <pdf> [--paper N]` | Shows why one paper's list was read the way it was |
| `run_lookup.py`, `run_selftest.py` | Lookup checks |

Typical use for a proceedings volume cut into several PDFs:

```
python run_export_all.py samples\proceedings
python run_validate_all.py proceedings_results.json you@example.com
python run_openalex.py proceedings_results_validated.json YOUR_KEY
```

Then open the last file in the app. Verifying about 32,000 references takes several hours; the run can be stopped and
started again without repeating any lookup.

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
| Found | 1,697 | 76.0% |
| Check | 161 | 7.2% |
| Not found | 375 | 16.8% |
| Error | 0 | 0% |

Found by: CrossRef search 1,124, arXiv ID 563, OpenAlex 10. OpenAlex, asked only about the 430 references that CrossRef
and arXiv could not confirm, turned 55 of them into found (10) or check (45). The rest are mostly work that none of the
sources index: workshop proceedings (CEUR-WS), JMLR/PMLR papers, web pages, reports and theses. The matcher also
correctly rejects look-alike records, for example a record by the same authors with a different title.

## Limitations

- *Found* means a source holds a record with a matching title. It is evidence that a reference exists, not proof that
  it is cited correctly.
- *Not found* does not mean a reference is wrong. Websites, theses, technical reports, workshop papers and some
  proceedings are not covered by the databases used.
- OpenAlex needs a free API key since February 2026; the free budget is about 1,000 searches per day.
- Reference styles outside the list above (for example astronomy's `Surname, I., Title. Year, Journal` with no period)
  are split poorly. Organisations as authors written in lower case, and typos in a paper's own bibliography, can
  merge or split entries; the audit usually flags these.
- Layout-based paper detection (PDFs without bookmarks) is tuned to ACL-style first pages and can miss papers whose
  first page has no "Abstract".
- Scanned PDFs without a text layer are not supported (no OCR).

## Privacy

PDFs are processed on your computer. Only reference text, titles, DOIs and arXiv IDs are sent to arXiv, CrossRef,
DataCite and OpenAlex when you validate.