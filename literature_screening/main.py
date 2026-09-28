#!/usr/bin/env python3
"""
main.py
========
Orkestrasi pipeline Semi-Automated Literature Screening Multi-Database.

Sumber tak-siap (Scopus/WOS tanpa kredensial) di-skip aman; pipeline lanjut.
Jalankan `python main.py --help` untuk melihat semua subperintah.

Alur umum (Bagian 21 & 23):
  1. fetch          -> ambil dari OpenAlex & Crossref (+ Scopus/WOS bila ada key)
  2. import-ieee     -> impor hasil IEEE final (BibTeX/CSV), pertahankan decision
  3. import-manual    -> impor ekspor manual Scopus/WoS (.bib/.ris/.csv)
  4. process          -> normalize (sudah dilakukan saat fetch/import) + filter + dedup
  5. prepare-screening -> ekspor CSV/XLSX untuk diisi peneliti (kolom decision)
  6. finalize          -> baca kembali hasil screening, validasi, ekspor
                          included.bib + statistik + log

Setiap tahap menyimpan hasil antara ke data/processed/ sehingga tahap
berikutnya bisa dijalankan terpisah (modular, sesuai Bagian 5).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from config import settings
from connectors import crossref, openalex, scopus, wos
from connectors.http_utils import ConnectorError
from export.bibtex_export import export_bibtex
from export.csv_export import OUTPUT_COLUMNS, export_csv
from export.xlsx_export import export_xlsx
from importers.bibtex_importer import import_bibtex
from importers.csv_importer import import_csv
from importers.ris_importer import import_ris
from processing.deduplicate import deduplicate
from processing.filtering import apply_filters
from processing.screening import prepare_screening_dataset, validate_decisions
from processing.statistics import SearchLog, build_statistics, count_by_source, save_statistics

COMBINED_RAW_PATH = settings.PROCESSED_DIR / "combined_raw_records.json"
IEEE_RECORDS_PATH = settings.PROCESSED_DIR / "ieee_records.json"
FILTERED_PATH = settings.PROCESSED_DIR / "filtered_records.json"
FUZZY_REVIEW_LOG_PATH = settings.LOGS_DIR / "fuzzy_review_log.json"


# ------------------------------------------------------------------
# Helper I/O JSON sederhana untuk menyimpan state antar-tahap
# ------------------------------------------------------------------
def _save_json(records: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"[main] {len(records)} record disimpan ke {path}")


def _load_json(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------------
# Tahap 1: fetch dari connector API (OpenAlex, Crossref, Scopus, WOS)
# ------------------------------------------------------------------
def cmd_fetch(args: argparse.Namespace) -> None:
    query = settings.MASTER_QUERY_CONCEPT
    search_log = SearchLog(settings.SEARCH_LOG_PATH)
    all_records: list[dict[str, Any]] = []

    sources_to_run = args.sources or ["openalex", "crossref", "scopus", "wos"]

    if "openalex" in sources_to_run:
        try:
            records = openalex.search(query, args.start_year, args.end_year, args.limit, force_refresh=args.force_refresh)
            all_records.extend(records)
            search_log.add_entry(
                "OpenAlex", openalex.build_query_string(query), args.start_year, args.end_year, len(records)
            )
        except ConnectorError as exc:
            print(f"[main] OpenAlex gagal: {exc}. Pipeline lanjut.")

    if "crossref" in sources_to_run:
        try:
            records = crossref.search(query, args.start_year, args.end_year, args.limit, force_refresh=args.force_refresh)
            all_records.extend(records)
            search_log.add_entry(
                "Crossref", crossref.build_query_string(query), args.start_year, args.end_year, len(records)
            )
        except ConnectorError as exc:
            print(f"[main] Crossref gagal: {exc}. Pipeline lanjut.")

    if "scopus" in sources_to_run:
        records = scopus.search(query, args.start_year, args.end_year, args.limit, force_refresh=args.force_refresh)
        all_records.extend(records)
        search_log.add_entry(
            "Scopus", scopus.build_query_string(query), args.start_year, args.end_year, len(records),
            note=None if scopus.is_available() else "skipped — no credentials",
        )

    if "wos" in sources_to_run:
        records = wos.search(query, args.start_year, args.end_year, args.limit, force_refresh=args.force_refresh)
        all_records.extend(records)
        search_log.add_entry(
            "WoS", wos.build_query_string(query), args.start_year, args.end_year, len(records),
            note=None if wos.is_available() else "skipped — no credentials",
        )

    search_log.save()

    existing = _load_json(COMBINED_RAW_PATH)
    # Hindari duplikasi kasar bila fetch dijalankan berkali-kali untuk sumber
    # yang berbeda: gabungkan berdasarkan record_id.
    existing_ids = {r["record_id"] for r in existing}
    merged = existing + [r for r in all_records if r["record_id"] not in existing_ids]

    _save_json(merged, COMBINED_RAW_PATH)
    print(f"[main] Fetch selesai. Total record (API) terkumpul: {len(merged)}")


# ------------------------------------------------------------------
# Tahap 2: import IEEE final (pertahankan decision, tandai source=IEEE)
# ------------------------------------------------------------------
def cmd_import_ieee(args: argparse.Namespace) -> None:
    ext = Path(args.file).suffix.lower()
    if ext == ".bib":
        records = import_bibtex(args.file, source_database="IEEE", default_decision_source="IEEE_manual")
    elif ext in (".csv", ".xlsx", ".xls"):
        records = import_csv(args.file, source_database="IEEE", default_decision_source="IEEE_manual")
    elif ext == ".ris":
        records = import_ris(args.file, source_database="IEEE")
    else:
        print(f"[main] Format file tidak dikenali: {ext}. Gunakan .bib/.csv/.xlsx/.ris.")
        sys.exit(1)

    n_with_decision = sum(1 for r in records if r.get("decision") in ("Include", "Exclude"))
    print(f"[main] IEEE import: {len(records)} record, {n_with_decision} sudah punya decision final.")

    _save_json(records, IEEE_RECORDS_PATH)


# ------------------------------------------------------------------
# Tahap 3: import manual Scopus/WoS (.bib/.ris/.csv) — interim
# ------------------------------------------------------------------
def cmd_import_manual(args: argparse.Namespace) -> None:
    ext = Path(args.file).suffix.lower()
    if ext == ".bib":
        records = import_bibtex(args.file, source_database=args.source)
    elif ext in (".csv", ".xlsx", ".xls"):
        records = import_csv(args.file, source_database=args.source)
    elif ext == ".ris":
        records = import_ris(args.file, source_database=args.source)
    else:
        print(f"[main] Format file tidak dikenali: {ext}. Gunakan .bib/.csv/.xlsx/.ris.")
        sys.exit(1)

    existing = _load_json(COMBINED_RAW_PATH)
    existing_ids = {r["record_id"] for r in existing}
    merged = existing + [r for r in records if r["record_id"] not in existing_ids]
    _save_json(merged, COMBINED_RAW_PATH)
    print(f"[main] Import manual '{args.source}': {len(records)} record ditambahkan ke pool gabungan.")


# ------------------------------------------------------------------
# Tahap 4: process = filter (tahun/tipe) + gabung IEEE + dedup
# ------------------------------------------------------------------
def cmd_process(args: argparse.Namespace) -> None:
    api_records = _load_json(COMBINED_RAW_PATH)
    ieee_records = _load_json(IEEE_RECORDS_PATH)

    if not api_records and not ieee_records:
        print("[main] Tidak ada data untuk diproses. Jalankan 'fetch' dan/atau 'import-ieee' terlebih dahulu.")
        sys.exit(1)

    # Filter tahun/tipe HANYA untuk record tanpa decision final (IEEE dilewati
    # otomatis di dalam apply_filters).
    filtered, rejected = apply_filters(api_records, args.start_year, args.end_year)

    combined_before_dedup = filtered + ieee_records
    print(f"[main] Pool sebelum dedup (API lolos filter + IEEE): {len(combined_before_dedup)}")

    unique_records, fuzzy_log = deduplicate(combined_before_dedup)

    _save_json(unique_records, FILTERED_PATH)
    _save_json(rejected, settings.PROCESSED_DIR / "rejected_by_filter.json")
    with open(FUZZY_REVIEW_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(fuzzy_log, f, ensure_ascii=False, indent=2)
    print(f"[main] Fuzzy review log ({len(fuzzy_log)} pasangan) disimpan ke {FUZZY_REVIEW_LOG_PATH}")

    # Simpan juga info untuk statistik nanti
    stats_context = {
        "retrieved_per_source": count_by_source(api_records),
        "before_dedup_count": len(combined_before_dedup),
        "after_filter_count": len(filtered),
    }
    with open(settings.PROCESSED_DIR / "stats_context.json", "w", encoding="utf-8") as f:
        json.dump(stats_context, f, indent=2)

    print(f"[main] Process selesai. {len(unique_records)} record unik siap discreening.")


# ------------------------------------------------------------------
# Tahap 5: prepare-screening = ekspor CSV/XLSX untuk diisi peneliti
# ------------------------------------------------------------------
def cmd_prepare_screening(args: argparse.Namespace) -> None:
    unique_records = _load_json(FILTERED_PATH)
    if not unique_records:
        print("[main] Belum ada data hasil 'process'. Jalankan 'process' dahulu.")
        sys.exit(1)

    prepared = prepare_screening_dataset(unique_records, use_ai_assist=not args.no_ai)

    export_csv(prepared, settings.SCREENING_CSV_PATH)
    export_xlsx(prepared, settings.SCREENING_XLSX_PATH)

    # Simpan versi "prepared" (dengan kolom AI dsb.) agar finalize bisa
    # mencocokkan record_id dengan hasil isian peneliti.
    _save_json(prepared, settings.PROCESSED_DIR / "prepared_for_screening.json")

    print(
        f"[main] Silakan isi kolom 'decision' (Include/Exclude) dan "
        f"'exclusion_reason' pada {settings.SCREENING_XLSX_PATH}, lalu jalankan "
        f"'finalize --file {settings.SCREENING_XLSX_PATH}'."
    )


# ------------------------------------------------------------------
# Tahap 6: finalize = baca hasil screening peneliti, validasi, export
# ------------------------------------------------------------------
def cmd_finalize(args: argparse.Namespace) -> None:
    screened_path = Path(args.file)
    if screened_path.suffix.lower() in (".xlsx", ".xls"):
        df = pd.read_excel(screened_path)
    else:
        df = pd.read_csv(screened_path)

    screened_by_id = {row["record_id"]: row.to_dict() for _, row in df.iterrows()}

    prepared = _load_json(settings.PROCESSED_DIR / "prepared_for_screening.json")
    ieee_records = _load_json(IEEE_RECORDS_PATH)

    final_records: list[dict[str, Any]] = []
    for rec in prepared:
        rec = dict(rec)
        row = screened_by_id.get(rec["record_id"])
        if row is not None:
            decision = str(row.get("decision") or "").strip()
            exclusion_reason = str(row.get("exclusion_reason") or "").strip()
            notes = str(row.get("notes") or "").strip()
            if decision and decision.lower() != "nan":
                rec["decision"] = decision
            if exclusion_reason and exclusion_reason.lower() != "nan":
                rec["exclusion_reason"] = exclusion_reason
            if notes and notes.lower() != "nan":
                rec["notes"] = notes
        final_records.append(rec)

    warnings = validate_decisions(final_records)
    for w in warnings:
        print(w)

    export_csv(final_records, settings.SCREENING_CSV_PATH)
    export_bibtex(final_records, settings.INCLUDED_BIB_PATH)

    api_records = _load_json(COMBINED_RAW_PATH)
    stats_context_path = settings.PROCESSED_DIR / "stats_context.json"
    stats_context = {}
    if stats_context_path.exists():
        with open(stats_context_path, "r", encoding="utf-8") as f:
            stats_context = json.load(f)

    stats = build_statistics(
        retrieved_per_source=stats_context.get("retrieved_per_source", count_by_source(api_records)),
        after_filter=[None] * stats_context.get("after_filter_count", 0),  # hanya butuh len()
        before_dedup_count=stats_context.get("before_dedup_count", len(final_records)),
        unique_records=final_records,
        ieee_records=ieee_records,
    )
    save_statistics(stats, settings.STATISTICS_PATH)

    print(f"[main] Finalize selesai. included.bib -> {settings.INCLUDED_BIB_PATH}")
    print(json.dumps(stats, indent=2, ensure_ascii=False))


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Semi-Automated Literature Screening Multi-Database Pipeline"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="Ambil data dari connector API (OpenAlex, Crossref, Scopus, WOS)")
    p_fetch.add_argument("--sources", nargs="+", choices=["openalex", "crossref", "scopus", "wos"], default=None)
    p_fetch.add_argument("--start-year", type=int, default=settings.START_YEAR)
    p_fetch.add_argument("--end-year", type=int, default=settings.END_YEAR)
    p_fetch.add_argument("--limit", type=int, default=settings.DEFAULT_LIMIT_PER_SOURCE)
    p_fetch.add_argument("--force-refresh", action="store_true", help="Abaikan raw cache, panggil API ulang")
    p_fetch.set_defaults(func=cmd_fetch)

    p_ieee = sub.add_parser("import-ieee", help="Impor hasil IEEE final (.bib/.csv/.xlsx/.ris)")
    p_ieee.add_argument("--file", required=True)
    p_ieee.set_defaults(func=cmd_import_ieee)

    p_manual = sub.add_parser("import-manual", help="Impor ekspor manual Scopus/WoS (.bib/.ris/.csv)")
    p_manual.add_argument("--file", required=True)
    p_manual.add_argument("--source", required=True, choices=["Scopus", "WoS"])
    p_manual.set_defaults(func=cmd_import_manual)

    p_process = sub.add_parser("process", help="Filter tahun/tipe + gabung IEEE + deduplikasi")
    p_process.add_argument("--start-year", type=int, default=settings.START_YEAR)
    p_process.add_argument("--end-year", type=int, default=settings.END_YEAR)
    p_process.set_defaults(func=cmd_process)

    p_prep = sub.add_parser("prepare-screening", help="Ekspor CSV/XLSX untuk diisi peneliti")
    p_prep.add_argument("--no-ai", action="store_true", help="Nonaktifkan rekomendasi AI-assisted screening")
    p_prep.set_defaults(func=cmd_prepare_screening)

    p_final = sub.add_parser("finalize", help="Baca hasil screening, validasi, ekspor included.bib + statistik")
    p_final.add_argument("--file", required=True, help="Path CSV/XLSX hasil screening yang sudah diisi peneliti")
    p_final.set_defaults(func=cmd_finalize)

    p_all = sub.add_parser("run-all", help="Jalankan fetch + process + prepare-screening berurutan")
    p_all.add_argument("--start-year", type=int, default=settings.START_YEAR)
    p_all.add_argument("--end-year", type=int, default=settings.END_YEAR)
    p_all.add_argument("--limit", type=int, default=settings.DEFAULT_LIMIT_PER_SOURCE)
    p_all.add_argument("--force-refresh", action="store_true")
    p_all.add_argument("--no-ai", action="store_true")
    p_all.set_defaults(func=None)  # ditangani khusus di main()

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "run-all":
        fetch_args = argparse.Namespace(
            sources=None, start_year=args.start_year, end_year=args.end_year,
            limit=args.limit, force_refresh=args.force_refresh,
        )
        cmd_fetch(fetch_args)
        cmd_process(argparse.Namespace(start_year=args.start_year, end_year=args.end_year))
        cmd_prepare_screening(argparse.Namespace(no_ai=args.no_ai))
        return

    args.func(args)


if __name__ == "__main__":
    main()