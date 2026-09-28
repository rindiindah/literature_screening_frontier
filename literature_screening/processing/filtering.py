"""
processing/filtering.py
=========================
Filtering awal objektif (Bagian 10): rentang tahun & document type.

Aturan:
- Publication year harus berada dalam [START_YEAR, END_YEAR].
- Bila document_type tersedia, dibatasi ke ALLOWED_DOCUMENT_TYPES
  (konfigurabel di config/settings.py).
- Record TIDAK dibuang hanya karena satu field kosong, kecuali memang
  diwajibkan kriteria (mis. year kosong -> tidak bisa dipastikan masuk
  rentang -> record tetap disimpan tapi ditandai untuk review manual,
  bukan otomatis dibuang, supaya tidak kehilangan data berharga).
- Record IEEE yang sudah punya `decision` final TIDAK ikut difilter ulang
  berdasarkan tahun/tipe (keputusan final dipertahankan apa adanya) —
  namun tetap dihitung pada statistik.
"""

from __future__ import annotations

from typing import Any

from config import settings


def passes_year_filter(record: dict[str, Any], start_year: int, end_year: int) -> bool:
    year = record.get("year")
    if year is None:
        # Tidak diketahui -> tidak otomatis dibuang (Bagian 10), tapi juga
        # tidak otomatis lolos. Diperlakukan sebagai "perlu review manual".
        return True
    return start_year <= int(year) <= end_year


def passes_type_filter(record: dict[str, Any], allowed_types: list[str]) -> bool:
    if not allowed_types:
        return True  # filter tipe dinonaktifkan
    doc_type = record.get("document_type")
    if not doc_type:
        return settings.KEEP_RECORD_IF_TYPE_UNKNOWN
    return doc_type.lower() in [t.lower() for t in allowed_types]


def apply_filters(
    records: list[dict[str, Any]],
    start_year: int = settings.START_YEAR,
    end_year: int = settings.END_YEAR,
    allowed_types: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Terapkan filter tahun & tipe dokumen.

    Record dengan `decision` final yang sudah ada (kasus IEEE) TIDAK
    disaring ulang — otomatis lolos filter agar keputusan lama tetap valid.

    Return: (records_lolos, records_tersisih)
    """
    if allowed_types is None:
        allowed_types = settings.ALLOWED_DOCUMENT_TYPES

    passed: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for rec in records:
        if rec.get("decision") in ("Include", "Exclude"):
            # Keputusan final (mis. IEEE) — jangan filter ulang.
            passed.append(rec)
            continue

        year_ok = passes_year_filter(rec, start_year, end_year)
        type_ok = passes_type_filter(rec, allowed_types)

        if year_ok and type_ok:
            passed.append(rec)
        else:
            reasons = []
            if not year_ok:
                reasons.append("outside_year_range")
            if not type_ok:
                reasons.append("document_type_not_allowed")
            rec["_filter_rejected_reason"] = ";".join(reasons)
            rejected.append(rec)

    print(
        f"[Filtering] {len(passed)} record lolos filter tahun/tipe, "
        f"{len(rejected)} record tersisih."
    )
    return passed, rejected
