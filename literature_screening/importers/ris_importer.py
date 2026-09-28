"""
importers/ris_importer.py
============================
Importer generik file RIS (.ris) — opsional, dipakai sebagai alternatif
ekspor manual Scopus/WoS (Phase 5) atau IEEE bila tersedia dalam format RIS.

Menggunakan library `rispy`. Memetakan minimal: title, abstract, authors,
year, doi, journal, document_type ke schema standar (Bagian 2.6).
"""

from __future__ import annotations

from typing import Any, Optional

try:
    import rispy

    _HAS_RISPY = True
except ImportError:  # pragma: no cover - fallback bila rispy belum terinstall
    _HAS_RISPY = False
    print(
        "[RIS Importer] PERINGATAN: paket 'rispy' tidak ditemukan, memakai "
        "parser RIS minimal bawaan. Untuk hasil lebih robust: pip install rispy."
    )

from processing.normalize import (
    empty_record,
    make_record_id,
    normalize_doi,
    normalize_document_type,
    normalize_year,
    now_iso,
)

# Pemetaan tipe RIS -> label generik (RIS memakai kode seperti JOUR, CPAPER)
_RIS_TYPE_MAP = {
    "jour": "article",
    "cpaper": "conference paper",
    "conf": "conference paper",
    "chap": "book chapter",
}


def _map_ris_type(ris_type: Optional[str]) -> Optional[str]:
    if not ris_type:
        return None
    return _RIS_TYPE_MAP.get(ris_type.lower(), normalize_document_type(ris_type))


# Pemetaan tag RIS standar -> nama field (dipakai fallback parser minimal)
_RIS_TAG_MAP = {
    "TY": "type_of_reference",
    "TI": "title",
    "T1": "title",
    "AB": "abstract",
    "N2": "abstract",
    "AU": "authors",
    "A1": "authors",
    "PY": "year",
    "Y1": "year",
    "DO": "doi",
    "JO": "journal_name",
    "JF": "journal_name",
    "T2": "secondary_title",
    "PB": "publisher",
    "UR": "url",
}


def _parse_ris_minimal(text: str) -> list[dict[str, Any]]:
    """Parser RIS minimal (line-based), fallback bila 'rispy' tidak
    terinstall. Format RIS: tiap baris "TAG  - value", entry dipisah "ER  -".
    """
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or "-" not in line:
            continue
        tag = line[:2].strip()
        # format standar: "TAG  - value"
        if len(line) < 6 or line[2:6].count("-") == 0:
            sep_idx = line.find("-")
            value = line[sep_idx + 1 :].strip()
        else:
            value = line.split("-", 1)[1].strip()

        if tag == "TY":
            current = {"type_of_reference": value}
        elif tag == "ER":
            if current:
                entries.append(current)
            current = {}
        else:
            field_name = _RIS_TAG_MAP.get(tag)
            if not field_name:
                continue
            if field_name == "authors":
                current.setdefault("authors", []).append(value)
            else:
                current[field_name] = value

    if current:
        entries.append(current)
    return entries


def import_ris(file_path: str, source_database: str) -> list[dict[str, Any]]:
    """Baca file .ris dan kembalikan list record dalam schema standar."""
    with open(file_path, "r", encoding="utf-8") as f:
        text = f.read()

    if _HAS_RISPY:
        import io

        entries = rispy.load(io.StringIO(text))
    else:
        entries = _parse_ris_minimal(text)

    records: list[dict[str, Any]] = []
    for entry in entries:
        rec = empty_record()

        title = entry.get("title") or entry.get("primary_title")
        doi = normalize_doi(entry.get("doi"))
        authors = entry.get("authors") or []
        year = normalize_year(entry.get("year") or entry.get("publication_year"))
        journal = entry.get("journal_name") or entry.get("secondary_title")
        doc_type = _map_ris_type(entry.get("type_of_reference"))
        abstract = entry.get("abstract")
        publisher = entry.get("publisher")
        url = entry.get("url")

        rec.update(
            {
                "record_id": make_record_id(source_database, doi, title or ""),
                "title": title,
                "abstract": abstract,
                "authors": list(authors),
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
        records.append(rec)

    print(f"[RIS Importer] {len(records)} record diimpor dari {file_path} (source={source_database})")
    return records
