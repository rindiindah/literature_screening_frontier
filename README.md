# Semi-Automated Literature Screening — Multi-Database

A support system for **retrieval → normalization → deduplication → filtering → semi-manual screening (Include/Exclude) → export of `included.bib` + statistics + reproducibility logs**, developed to support the revision of the Frontiers mini-review:

*"Multimodal Intelligence for Air Quality Modeling"*.

**Five final databases:** IEEE Xplore (import-only), OpenAlex (API), Crossref (API), Scopus (API when credentials are available / manual import temporarily), and Web of Science (API when credentials are available / manual import temporarily).

The system **only provides support** — final academic decisions remain with the researcher.

---

## 1. Installation (Windows)

1. Install Python 3.10+ from [python.org](https://www.python.org/downloads/)
   (check "Add Python to PATH" during installation).

2. Open **Command Prompt** or **PowerShell**, then navigate to the project folder:

   ```powershell
   cd path\ke\literature_screening
   ```

3. (Recommended) Create a virtual environment:

   ```powershell
   python -m venv venv
   venv\Scripts\activate
   ```

4. Install the dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

5. Copy `.env.example` to `.env`, then enter your email/API keys:

   ```powershell
   copy .env.example .env
   notepad .env
   ```

   Minimum configuration:

   * `OPENALEX_MAILTO` = your email (required for the polite pool; `OPENALEX_API_KEY` is optional).
   * `CROSSREF_MAILTO` = your email (required).
   * `SCOPUS_API_KEY`, `SCOPUS_INSTTOKEN` = leave empty if access has not been granted.
   * `WOS_API_KEY` = leave empty if access has not been granted.

   **Never commit your actual `.env` file to Git.**

---

## 2. Running the Pipeline

Run each stage from the `literature_screening/` directory.

### Stage 1 — Retrieve data from OpenAlex & Crossref (and Scopus/WoS when credentials are available)

```powershell
python main.py fetch
```

* Only sources with available credentials are queried.
  Scopus/WoS are automatically skipped with a clear message when their keys are empty.
* Raw results are stored in `data/raw/<source>_<date>.json` (daily raw cache — rerunning on the same day does not call the API again unless `--force-refresh` is used).
* Normalized results are combined into `data/processed/combined_raw_records.json`.

Options:

```powershell
python main.py fetch --sources openalex crossref
python main.py fetch --start-year 2024 --end-year 2026 --limit 500
python main.py fetch --force-refresh
```

### Stage 2 — Import final IEEE results (with existing Include/Exclude decisions)

```powershell
python main.py import-ieee --file data\raw\ieee_final_import.bib
```

Supports `.bib`, `.csv`, `.xlsx`, and `.ris`. The `decision` column (and optional `exclusion_reason` and `notes`) in the file will be **preserved** rather than screened again.

### Stage 3 — (Optional, interim) Import manual Scopus/WoS exports

While Scopus/WoS API credentials are not available, export the search results from the respective portals (`.bib`/`.ris`/`.csv`), then run:

```powershell
python main.py import-manual --file data\raw\scopus_export.csv --source Scopus
python main.py import-manual --file data\raw\wos_export.ris --source WoS
```

### Stage 4 — Filtering + IEEE integration + Deduplication

```powershell
python main.py process
```

* Filter by year (`START_YEAR`–`END_YEAR`) and document type (configurable in `config/settings.py`). IEEE records with existing decisions are not filtered again.
* Cross-source deduplication: DOI → normalized title → fuzzy title matching, with matching records logged. Results are saved to `data/processed/filtered_records.json`.
* Medium-confidence fuzzy matches that require manual review are recorded in `logs/fuzzy_review_log.json`.

### Stage 5 — Prepare the screening sheet

```powershell
python main.py prepare-screening
```

Generates:

* `data/output/screening_results.xlsx` (with Include/Exclude dropdowns and a list of exclusion reasons) — **open this file in Excel and fill in the `decision` column (and `exclusion_reason` when Exclude) for each paper.**
* `data/output/screening_results.csv` (alternative format without dropdowns).

The `ai_suggestion` / `ai_reason` columns (when AI assistance is enabled) are only supporting recommendations — the final decision remains in the `decision` column completed by the researcher.

### Stage 6 — Finalization: `included.bib` + statistics

After completing the `decision` column in Excel, save the file, then run:

```powershell
python main.py finalize --file data\output\screening_results.xlsx
```

Generates:

* `data/output/included.bib` — only papers with `decision = Include`.
* `data/output/screening_results.csv` — final version containing all decisions.
* `data/output/statistics.json` — statistics for each pipeline stage (Section 18 specification).
* `logs/search_log.json` — reproducibility log for each run (actual query, date, and record count).

### Run all automated stages at once (fetch → process → prepare-screening)

```powershell
python main.py run-all
```

(IEEE/manual imports and `finalize` must still be run separately because they require researcher input.)

---

## 3. Folder Structure

```text
literature_screening/
├── config/settings.py          # years, master query, criteria, dedup thresholds, paths
├── connectors/                 # openalex.py, crossref.py, scopus.py, wos.py
├── importers/                  # bibtex_importer.py, ris_importer.py, csv_importer.py
├── processing/                 # normalize, filtering, deduplicate, screening, statistics
├── export/                     # csv_export, xlsx_export, bibtex_export
├── data/{raw,processed,output}/
├── logs/                       # search_log.json, fuzzy_review_log.json
├── main.py
├── requirements.txt
└── .env.example
```

---

## 4. Important Technical Notes

* **OpenAlex**: Abstracts are reconstructed from `abstract_inverted_index`. If the source value is null, `abstract = None` is used rather than generating an abstract.
* **Crossref**: Abstracts are often unavailable and are only included when provided by the publisher through JATS XML. XML tags are automatically removed when an abstract is available.
* **Scopus**: The Search API does not provide full abstracts. They are retrieved through the Abstract Retrieval API in a second stage, only for records that pass the filtering step to reduce API usage.
* **Web of Science**: The connector uses the **Starter API** (documented in the code). Full abstracts are NOT available through this tier and require the Expanded API.
* **IEEE**: Import-only; there is no API connector. Existing final decisions are preserved and the records are not screened again.
* Empty credentials (Scopus/WoS) → the connector displays a clear message and safely skips the source; the pipeline continues with the other available sources.
* All thresholds, criteria, year ranges, and allowed document types **can be edited** in `config/settings.py`.

---

## 5. Generated Statistics (`data/output/statistics.json`)

```text
IEEE (imported, final):   XXX   (Include: XX / Exclude: XX)
OpenAlex retrieved:       XXX
Crossref retrieved:       XXX
Scopus retrieved:         XXX   (or: skipped — no credentials)
WoS retrieved:            XXX   (or: skipped — no credentials)

Total retrieved:          XXX
After year/type filter:   XXX
Duplicates removed:       XXX
Unique records screened:  XXX
Include:                  XXX
Exclude:                  XXX
```

These statistics can be directly used to create a PRISMA-style flow diagram for the revised manuscript.
