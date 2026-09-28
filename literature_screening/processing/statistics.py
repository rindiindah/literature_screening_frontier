"""
processing/statistics.py
==========================
Statistik screening otomatis (Bagian 18) dan log reproducibility
(Bagian 19). Disimpan agar bisa dipakai untuk PRISMA-style flow di
manuskrip revisi.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from processing.normalize import now_iso


def count_by_source(records: list[dict[str, Any]]) -> dict[str, int]:
    """Hitung jumlah record per source_database. Record hasil merge
    (source_database = "A; B; C") dihitung ke masing-masing sumber
    penyusunnya (Bagian 12 — penting untuk PRISMA-style flow)."""
    counts: dict[str, int] = {}
    for rec in records:
        src_field = rec.get("source_database") or ""
        for src in [s.strip() for s in src_field.split(";") if s.strip()]:
            counts[src] = counts.get(src, 0) + 1
    return counts


def build_statistics(
    retrieved_per_source: dict[str, int],
    after_filter: list[dict[str, Any]],
    before_dedup_count: int,
    unique_records: list[dict[str, Any]],
    ieee_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Susun statistik ringkas sesuai format Bagian 18."""
    total_retrieved = sum(retrieved_per_source.values())

    ieee_include = sum(1 for r in ieee_records if r.get("decision") == "Include")
    ieee_exclude = sum(1 for r in ieee_records if r.get("decision") == "Exclude")

    duplicates_removed = before_dedup_count - len(unique_records)

    screened = [r for r in unique_records if r.get("decision") in ("Include", "Exclude")]
    include_count = sum(1 for r in screened if r.get("decision") == "Include")
    exclude_count = sum(1 for r in screened if r.get("decision") == "Exclude")

    stats = {
        "generated_at": now_iso(),
        "per_source_retrieved": {
            "IEEE_imported": len(ieee_records),
            "IEEE_include": ieee_include,
            "IEEE_exclude": ieee_exclude,
            "OpenAlex": retrieved_per_source.get("OpenAlex", 0),
            "Crossref": retrieved_per_source.get("Crossref", 0),
            "Scopus": retrieved_per_source.get("Scopus", "skipped — no credentials"
                                                  if "Scopus" not in retrieved_per_source else retrieved_per_source.get("Scopus")),
            "WoS": retrieved_per_source.get("WoS", "skipped — no credentials"
                                             if "WoS" not in retrieved_per_source else retrieved_per_source.get("WoS")),
        },
        "total_retrieved": total_retrieved,
        "after_year_type_filter": len(after_filter),
        "duplicates_removed": duplicates_removed,
        "unique_records_screened_pool": len(unique_records),
        "include": include_count,
        "exclude": exclude_count,
        "not_yet_decided": len(unique_records) - len(screened),
    }
    return stats


def save_statistics(stats: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
    print(f"[Statistics] Statistik disimpan ke {path}")


class SearchLog:
    """Log reproducibility per sumber (Bagian 19): search date/time,
    database, query aktual, year range, filter, jumlah tiap tahap."""

    def __init__(self, path: Path):
        self.path = path
        self.entries: list[dict[str, Any]] = []
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                if isinstance(existing, list):
                    self.entries = existing
            except (json.JSONDecodeError, OSError):
                self.entries = []

    def add_entry(
        self,
        database: str,
        query: str,
        start_year: int,
        end_year: int,
        retrieved: int,
        after_filter: int | None = None,
        duplicated: int | None = None,
        screened: int | None = None,
        included: int | None = None,
        excluded: int | None = None,
        note: str | None = None,
    ) -> None:
        self.entries.append(
            {
                "database": database,
                "query": query,
                "start_year": start_year,
                "end_year": end_year,
                "retrieved": retrieved,
                "after_filter": after_filter,
                "duplicated": duplicated,
                "screened": screened,
                "included": included,
                "excluded": excluded,
                "note": note,
                "date": now_iso(),
            }
        )

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.entries, f, indent=2, ensure_ascii=False)
        print(f"[SearchLog] {len(self.entries)} entri log disimpan ke {self.path}")
