"""
importers/bibtex_importer.py
==============================
Importer generik file BibTeX (.bib), dipakai untuk:
- Hasil IEEE Xplore final (Phase 4) — SUDAH memiliki keputusan
  Include/Exclude yang harus dipertahankan (JANGAN ditimpa/screen ulang).
- Ekspor manual Scopus / Web of Science (Phase 5) selama connector API
  belum aktif (kredensial pending).

Memetakan minimal: title, abstract, authors, year, doi, journal,
document_type ke schema standar (Bagian 2.6). Bila entry BibTeX punya
field custom `decision` / `exclusion_reason` / `notes` (kasus IEEE),
field tersebut dipertahankan apa adanya.
"""

from __future__ import annotations

import re
from typing import Any, Optional

try:
    import bibtexparser

    _HAS_BIBTEXPARSER = True
except ImportError:  # pragma: no cover - fallback bila bibtexparser belum terinstall
    _HAS_BIBTEXPARSER = False
    print(
        "[BibTeX Importer] PERINGATAN: paket 'bibtexparser' tidak ditemukan, "
        "memakai parser BibTeX minimal bawaan (regex-based). Untuk hasil "
        "yang lebih robust terhadap format BibTeX kompleks: pip install bibtexparser."
    )

from processing.normalize import (
    empty_record,
    make_record_id,
    normalize_doi,
    normalize_document_type,
    normalize_year,
    now_iso,
)

VALID_DECISIONS = {"include", "exclude"}


def _split_authors(raw_author_field: Optional[str]) -> list[str]:
    if not raw_author_field:
        return []
    # BibTeX memisahkan penulis dengan " and "
    parts = [a.strip() for a in raw_author_field.split(" and ") if a.strip()]
    cleaned = []
    for p in parts:
        # Format umum "Family, Given" -> ubah jadi "Given Family" agar konsisten
        if "," in p:
            family, given = [x.strip() for x in p.split(",", 1)]
            cleaned.append(f"{given} {family}".strip())
        else:
            cleaned.append(p)
    return cleaned


_ENTRY_RE = re.compile(r"@(\w+)\s*\{\s*([^,]+),", re.MULTILINE)
_FIELD_RE = re.compile(r"(\w+)\s*=\s*(\{((?:[^{}]|\{[^{}]*\})*)\}|\"([^\"]*)\"|([^,\n]+))", re.MULTILINE)


def _parse_bibtex_minimal(text: str) -> list[dict[str, Any]]:
    """Parser BibTeX minimal (regex-based), dipakai sebagai fallback bila
    paket 'bibtexparser' tidak terinstall. Menangani kasus umum: entry
    @type{key, field = {value}, field = "value", field = value, ...}.
    Tidak menangani semua edge-case BibTeX (nested brace ekstrem, string
    macro @string, dsb.) — cukup untuk ekspor standar IEEE/Scopus/WoS.
    """
    entries: list[dict[str, Any]] = []
    entry_starts = list(_ENTRY_RE.finditer(text))

    for idx, match in enumerate(entry_starts):
        entry_type = match.group(1).lower()
        entry_id = match.group(2).strip()
        body_start = match.end()
        body_end = entry_starts[idx + 1].start() if idx + 1 < len(entry_starts) else len(text)
        # Potong body sampai sebelum brace penutup entry terakhir (heuristik:
        # ambil semua sampai body_end, lalu buang trailing "}\n" penutup).
        body = text[body_start:body_end]
        last_brace = body.rfind("}")
        if last_brace != -1:
            body = body[:last_brace]

        fields: dict[str, str] = {"ENTRYTYPE": entry_type, "ID": entry_id}
        for fm in _FIELD_RE.finditer(body):
            field_name = fm.group(1).strip().lower()
            value = fm.group(3) if fm.group(3) is not None else (fm.group(4) if fm.group(4) is not None else fm.group(5))
            if value is not None:
                fields[field_name] = value.strip().rstrip(",").strip()
        entries.append(fields)

    return entries


def _extract_decision(entry: dict[str, Any]) -> Optional[str]:
    raw = (entry.get("decision") or entry.get("note_decision") or "").strip()
    if not raw:
        return None
    low = raw.lower()
    if low in VALID_DECISIONS:
        return "Include" if low == "include" else "Exclude"
    return None  # nilai tidak dikenal -> tidak dipaksakan


def import_bibtex(
    file_path: str,
    source_database: str,
    default_decision_source: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Baca file .bib dan kembalikan list record dalam schema standar.

    Args:
        file_path: path ke file .bib.
        source_database: label sumber, mis. "IEEE", "Scopus", "WoS".
        default_decision_source: bila diisi (mis. "IEEE_manual"), field
            `decision_source` akan diisi untuk tiap record yang punya
            `decision` valid dari file — dipakai untuk menandai bahwa
            keputusan berasal dari screening manual sebelumnya (IEEE).
    """
    with open(file_path, "r", encoding="utf-8") as f:
        text = f.read()

    if _HAS_BIBTEXPARSER:
        import io

        bib_database = bibtexparser.load(io.StringIO(text))
        entries = bib_database.entries
    else:
        entries = _parse_bibtex_minimal(text)

    records: list[dict[str, Any]] = []
    for entry in entries:
        rec = empty_record()

        title = entry.get("title", "").strip("{}").strip() or None
        doi = normalize_doi(entry.get("doi"))
        authors = _split_authors(entry.get("author"))
        year = normalize_year(entry.get("year"))
        journal = entry.get("journal") or entry.get("booktitle")
        doc_type = normalize_document_type(entry.get("entrytype") or entry.get("ENTRYTYPE"))
        abstract = entry.get("abstract") or None
        publisher = entry.get("publisher")
        url = entry.get("url")
        bib_key = entry.get("ID")

        rec.update(
            {
                "record_id": make_record_id(source_database, doi or bib_key, title or bib_key or ""),
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
                "source_id": bib_key,
                "search_query": None,  # tidak berasal dari API run ini
                "retrieved_at": now_iso(),
            }
        )

        decision = _extract_decision(entry)
        if decision:
            rec["decision"] = decision
            rec["exclusion_reason"] = entry.get("exclusion_reason") or None
            rec["notes"] = entry.get("notes") or None
            if default_decision_source:
                rec["decision_source"] = default_decision_source

        records.append(rec)

    print(f"[BibTeX Importer] {len(records)} record diimpor dari {file_path} (source={source_database})")
    return records
