"""
config/settings.py
===================
Satu-satunya tempat konfigurasi yang dipakai seluruh pipeline
(literature_screening). Semua nilai yang mungkin berubah antar-run
(rentang tahun, master query, kriteria screening, threshold dedup,
path, dsb.) HARUS diletakkan di sini — jangan hard-code di modul lain.

Kredensial (API key, mailto) dibaca dari environment variable
(lihat .env.example) memakai python-dotenv. Jangan pernah menaruh
nilai kredensial asli langsung di file ini.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ----------------------------------------------------------------------
# Muat .env (bila ada) sebelum membaca environment variable apa pun.
# ----------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# ----------------------------------------------------------------------
# 1. Rentang tahun (Bagian 4 spesifikasi)
# ----------------------------------------------------------------------
START_YEAR = int(os.getenv("LIT_START_YEAR", "2024"))
END_YEAR = int(os.getenv("LIT_END_YEAR", "2026"))

# ----------------------------------------------------------------------
# 2. Master query konseptual (Bagian 3)
#    Representasi terstruktur ini dipakai oleh query adapter
#    tiap connector untuk membangun sintaks native API masing-masing.
#    JANGAN kirim string ini mentah-mentah ke API manapun.
# ----------------------------------------------------------------------
MASTER_QUERY_CONCEPT = {
    "group_a": ["multimodal", "data fusion", "multisource"],
    "group_b": ["air quality", "air pollution"],
    "group_c": ["forecasting", "prediction", "modeling", "estimation"],
}

MASTER_QUERY_HUMAN_READABLE = (
    '("multimodal" OR "data fusion" OR "multisource") '
    'AND ("air quality" OR "air pollution") '
    'AND ("forecasting" OR "prediction" OR "modeling" OR "estimation")'
)

# ----------------------------------------------------------------------
# 3. Lima database final (JANGAN tambah/ganti)
# ----------------------------------------------------------------------
VALID_SOURCES = ["IEEE", "OpenAlex", "Crossref", "Scopus", "WoS"]

# ----------------------------------------------------------------------
# 4. Document type yang dipertahankan pada filtering awal (Bagian 10)
#    Dibuat konfigurabel; kosongkan list untuk menonaktifkan filter tipe.
#    Nilai di sini adalah representasi generik; setiap connector/importer
#    memetakan tipe aslinya ke salah satu label ini melalui
#    processing.normalize.normalize_document_type().
# ----------------------------------------------------------------------
ALLOWED_DOCUMENT_TYPES = [
    "article",
    "conference paper",
    "proceedings paper",
]
# Bila True, record dengan document_type kosong/tidak dikenali TETAP
# dipertahankan (tidak dibuang hanya karena field ini kosong — sesuai
# prinsip Bagian 10: "Jangan hapus record hanya karena satu field kosong").
KEEP_RECORD_IF_TYPE_UNKNOWN = True

# ----------------------------------------------------------------------
# 5. Deduplication (Bagian 11)
# ----------------------------------------------------------------------
FUZZY_TITLE_THRESHOLD = int(os.getenv("LIT_FUZZY_THRESHOLD", "92"))  # 0-100 (rapidfuzz)
FUZZY_REVIEW_LOWER_BOUND = int(os.getenv("LIT_FUZZY_REVIEW_LOWER", "85"))
# Kandidat dengan skor di [FUZZY_REVIEW_LOWER_BOUND, FUZZY_TITLE_THRESHOLD)
# dicatat ke log untuk ditinjau manual, tapi TIDAK otomatis digabung.

# ----------------------------------------------------------------------
# 6. Kriteria Screening (Bagian 14) — dapat diedit sesuai protokol review
# ----------------------------------------------------------------------
SCREENING_CRITERIA = {
    "include": [
        "Air quality / air pollution sebagai domain.",
        "Forecasting / prediction / modeling / estimation.",
        "Multimodal / data fusion / multisource / penggabungan beberapa sumber/jenis data.",
        "Merupakan research article / conference paper sesuai scope.",
        "Publication year dalam rentang.",
        "Informasi cukup untuk dinilai dari title/abstract.",
    ],
    "exclude": [
        "Tidak terkait air quality/pollution.",
        "Tidak terkait forecasting/prediction/modeling/estimation.",
        "Hanya satu modality/source & tidak relevan dengan fokus multimodal.",
        "Di luar rentang tahun.",
        "Review/survey (bila review/survey bukan studi utama).",
        "Di luar scope.",
        "Duplicate.",
        "Title/abstract menunjukkan tidak membahas tujuan relevan.",
    ],
}

EXCLUSION_REASONS = [
    "Wrong domain",
    "Wrong task",
    "Single modality",
    "Wrong publication type",
    "Outside year range",
    "Review paper",
    "Duplicate",
    "Out of scope",
    "Insufficient relevance",
]

DECISION_VALUES = ["Include", "Exclude"]  # TIDAK ADA "Maybe"

# ----------------------------------------------------------------------
# 7. Path (Bagian 5 & 9)
# ----------------------------------------------------------------------
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
OUTPUT_DIR = DATA_DIR / "output"
LOGS_DIR = BASE_DIR / "logs"

for _d in (RAW_DIR, PROCESSED_DIR, OUTPUT_DIR, LOGS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

SEARCH_LOG_PATH = LOGS_DIR / "search_log.json"
MERGED_RAW_PATH = PROCESSED_DIR / "merged_raw.csv"
DEDUPLICATED_PATH = PROCESSED_DIR / "deduplicated.csv"
SCREENING_CSV_PATH = OUTPUT_DIR / "screening_results.csv"
SCREENING_XLSX_PATH = OUTPUT_DIR / "screening_results.xlsx"
INCLUDED_BIB_PATH = OUTPUT_DIR / "included.bib"
STATISTICS_PATH = OUTPUT_DIR / "statistics.json"

# ----------------------------------------------------------------------
# 8. Kredensial & pengaturan koneksi (dibaca dari .env)
# ----------------------------------------------------------------------
OPENALEX_API_KEY = os.getenv("OPENALEX_API_KEY", "").strip() or None
OPENALEX_MAILTO = os.getenv("OPENALEX_MAILTO", "").strip() or None

CROSSREF_MAILTO = os.getenv("CROSSREF_MAILTO", "").strip() or None

SCOPUS_API_KEY = os.getenv("SCOPUS_API_KEY", "").strip() or None
SCOPUS_INSTTOKEN = os.getenv("SCOPUS_INSTTOKEN", "").strip() or None

WOS_API_KEY = os.getenv("WOS_API_KEY", "").strip() or None

# ----------------------------------------------------------------------
# 9. Pengaturan umum retrieval (rate limit, retry, timeout, page size)
# ----------------------------------------------------------------------
REQUEST_TIMEOUT_SECONDS = 30
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2.0  # exponential backoff: backoff * (2 ** attempt)

OPENALEX_PAGE_SIZE = 200          # max per_page OpenAlex = 200
CROSSREF_PAGE_SIZE = 200           # rows per halaman Crossref (wajar; max 1000)
SCOPUS_PAGE_SIZE = 25              # default Scopus "count"
WOS_PAGE_SIZE = 50                 # default WOS Starter "limit" (max 50)

# Batas jumlah maksimum record yang diambil per sumber pada satu run.
# None = tanpa batas (ambil semua sesuai pagination hingga habis).
DEFAULT_LIMIT_PER_SOURCE = None

USER_AGENT = (
    "LiteratureScreeningTool/1.0 "
    f"(mailto:{CROSSREF_MAILTO or OPENALEX_MAILTO or 'unknown@example.com'})"
)
