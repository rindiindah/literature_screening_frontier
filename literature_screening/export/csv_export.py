"""
export/csv_export.py
======================
Ekspor dataset screening ke CSV (Bagian 16).

Kolom output:
record_id | title | abstract | authors | year | doi | journal | publisher |
document_type | url | source_database | duplicate_group_id |
deduplication_method | decision | exclusion_reason | notes
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

OUTPUT_COLUMNS = [
    "record_id",
    "title",
    "abstract",
    "authors",
    "year",
    "doi",
    "journal",
    "publisher",
    "document_type",
    "url",
    "source_database",
    "duplicate_group_id",
    "deduplication_method",
    "decision",
    "exclusion_reason",
    "notes",
]


def _to_dataframe(records: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for rec in records:
        row = {col: rec.get(col) for col in OUTPUT_COLUMNS}
        authors = row.get("authors")
        if isinstance(authors, list):
            row["authors"] = "; ".join(authors)
        rows.append(row)
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def export_csv(records: list[dict[str, Any]], output_path: Path) -> None:
    df = _to_dataframe(records)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"[CSV Export] {len(df)} baris ditulis ke {output_path}")
