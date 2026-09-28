"""
importers/csv_importer.py
============================
Importer generik file CSV/XLSX — dipakai untuk:
- Hasil IEEE final dalam bentuk CSV/XLSX yang SUDAH ada kolom keputusan
  (`decision`, opsional `exclusion_reason`, `notes`) — dipertahankan.
- Ekspor manual Scopus/WoS dalam CSV (Phase 5).

Kolom input diharapkan (nama kolom fleksibel via `column_map`), minimal
memetakan ke: title, abstract, authors, year, doi, journal, document_type.
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from processing.normalize import (
    empty_record,
    make_record_id,
    normalize_doi,
    normalize_document_type,
    normalize_year,
    now_iso,
)

DEFAULT_COLUMN_MAP = {
    "title": "title",
    "abstract": "abstract",
    "authors": "authors",
    "year": "year",
    "doi": "doi",
    "journal": "journal",
    "publisher": "publisher",
    "document_type": "document_type",
    "url": "url",
    "decision": "decision",
    "exclusion_reason": "exclusion_reason",
    "notes": "notes",
}

VALID_DECISIONS = {"include", "exclude"}


def _split_authors(raw: Any) -> list[str]:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return []
    raw = str(raw)
    # Dukung pemisah umum: ';', ' and ', ','
    for sep in (";", " and "):
        if sep in raw:
            return [a.strip() for a in raw.split(sep) if a.strip()]
    return [a.strip() for a in raw.split(",") if a.strip()]


def _clean(value: Any) -> Optional[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    value = str(value).strip()
    return value or None


def import_csv(
    file_path: str,
    source_database: str,
    column_map: Optional[dict[str, str]] = None,
    default_decision_source: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Baca file .csv atau .xlsx dan kembalikan list record schema standar."""
    cmap = {**DEFAULT_COLUMN_MAP, **(column_map or {})}

    if file_path.lower().endswith((".xlsx", ".xls")):
        df = pd.read_excel(file_path)
    else:
        df = pd.read_csv(file_path)

    records: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        rec = empty_record()

        title = _clean(row.get(cmap["title"]))
        doi = normalize_doi(_clean(row.get(cmap["doi"])))
        authors = _split_authors(row.get(cmap["authors"]))
        year = normalize_year(row.get(cmap["year"]))
        journal = _clean(row.get(cmap["journal"]))
        publisher = _clean(row.get(cmap["publisher"]))
        doc_type = normalize_document_type(_clean(row.get(cmap["document_type"])))
        abstract = _clean(row.get(cmap["abstract"]))
        url = _clean(row.get(cmap["url"]))

        rec.update(
            {
                "record_id": make_record_id(source_database, doi, title or ""),
                "title": title,
                "abstract": abstract,
                "authors": authors,
                "year": year,
                "doi": doi,
                "journal": journal,
                "publisher": publisher,
                "document_type": doc_type,
                "url": url,
                "open_access": None,
                "source_database": source_database,
                "source_id": doi,
                "search_query": None,
                "retrieved_at": now_iso(),
            }
        )

        decision_raw = _clean(row.get(cmap["decision"]))
        if decision_raw and decision_raw.lower() in VALID_DECISIONS:
            rec["decision"] = "Include" if decision_raw.lower() == "include" else "Exclude"
            rec["exclusion_reason"] = _clean(row.get(cmap["exclusion_reason"]))
            rec["notes"] = _clean(row.get(cmap["notes"]))
            if default_decision_source:
                rec["decision_source"] = default_decision_source

        records.append(rec)

    print(f"[CSV Importer] {len(records)} record diimpor dari {file_path} (source={source_database})")
    return records
