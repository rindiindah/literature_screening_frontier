"""
export/bibtex_export.py
=========================
Ekspor `included.bib` (Bagian 17): hanya paper dengan decision == Include
(IEEE Include + hasil Include database lain). Exclude TIDAK disertakan.

- Gunakan DOI sebagai basis metadata bila ada.
- Citation key konsisten & tidak duplicate (author+year+judul-disambiguated).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def _first_author_surname(authors: list[str]) -> str:
    if not authors:
        return "unknown"
    first = authors[0].strip()
    # Ambil kata terakhir sebagai surname (asumsi format "Given Family")
    parts = first.split()
    surname = parts[-1] if parts else first
    surname = re.sub(r"[^A-Za-z]", "", surname).lower()
    return surname or "unknown"


def _slug_word(title: str) -> str:
    words = re.sub(r"[^A-Za-z0-9\s]", "", title or "").split()
    return words[0].lower() if words else "paper"


def _make_citation_key(rec: dict[str, Any], used_keys: set[str]) -> str:
    surname = _first_author_surname(rec.get("authors") or [])
    year = rec.get("year") or "nd"
    word = _slug_word(rec.get("title") or "")
    base_key = f"{surname}{year}{word}"

    key = base_key
    suffix = ord("a")
    while key in used_keys:
        key = f"{base_key}{chr(suffix)}"
        suffix += 1
    used_keys.add(key)
    return key


def _escape_bibtex(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("{", "").replace("}", "")


def _entry_type(document_type: str | None) -> str:
    if not document_type:
        return "article"
    dt = document_type.lower()
    if "conference" in dt or "proceedings" in dt:
        return "inproceedings"
    if "book" in dt:
        return "incollection"
    return "article"


def export_bibtex(records: list[dict[str, Any]], output_path: Path) -> None:
    included = [r for r in records if (r.get("decision") or "").strip() == "Include"]

    used_keys: set[str] = set()
    lines: list[str] = []

    for rec in included:
        key = _make_citation_key(rec, used_keys)
        entry_type = _entry_type(rec.get("document_type"))

        authors = rec.get("authors") or []
        authors_str = " and ".join(authors) if authors else ""

        fields = {
            "author": authors_str,
            "title": _escape_bibtex(rec.get("title")),
            "year": _escape_bibtex(rec.get("year")),
            "doi": _escape_bibtex(rec.get("doi")),
            "url": _escape_bibtex(rec.get("url")),
        }
        if entry_type == "inproceedings":
            fields["booktitle"] = _escape_bibtex(rec.get("journal"))
        else:
            fields["journal"] = _escape_bibtex(rec.get("journal"))
        if rec.get("publisher"):
            fields["publisher"] = _escape_bibtex(rec.get("publisher"))

        field_lines = [f"  {k} = {{{v}}}," for k, v in fields.items() if v]
        # Hapus koma trailing pada baris terakhir
        if field_lines:
            field_lines[-1] = field_lines[-1].rstrip(",")

        entry = f"@{entry_type}{{{key},\n" + "\n".join(field_lines) + "\n}\n"
        lines.append(entry)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"[BibTeX Export] {len(included)} paper Include ditulis ke {output_path}")
