"""
connectors/scopus.py
======================
Connector API Scopus (Elsevier Developer Portal) — AKTIF OTOMATIS bila
SCOPUS_API_KEY tersedia di environment; SKIP AMAN bila tidak.

Referensi resmi:
- Scopus Search API: https://dev.elsevier.com/documentation/ScopusSearchAPI.wadl
  Endpoint: GET https://api.elsevier.com/content/search/scopus
  Header wajib: X-ELS-APIKey; opsional: X-ELS-Insttoken (akses institusi).
  Query boolean lewat parameter `query` menggunakan sintaks Scopus
  (mis. TITLE-ABS-KEY(...), AND, OR, PUBYEAR).
  Pagination: `start` (offset) + `count` (jumlah per halaman).
- Abstract Retrieval API: https://dev.elsevier.com/documentation/AbstractRetrievalAPI.wadl
  Endpoint: GET https://api.elsevier.com/content/abstract/doi/{doi}
  Dipakai karena Scopus Search API TIDAK menyertakan abstract penuh
  (Bagian 2.4) -> retrieval abstract dilakukan sebagai tahap KEDUA,
  hanya untuk record yang sudah lolos filter tahun/tipe (hemat kuota).

Bila SCOPUS_API_KEY kosong: connector mencetak pesan jelas dan
mengembalikan list kosong ([]) TANPA melempar exception yang mematikan
pipeline (Bagian 2.4, prinsip skip aman).
"""

from __future__ import annotations

from typing import Any, Optional

from config import settings
from connectors.http_utils import ConnectorError, request_with_retry
from connectors.raw_cache import load_cache, save_cache
from processing.normalize import normalize_doi, normalize_scopus_record

SEARCH_URL = "https://api.elsevier.com/content/search/scopus"
ABSTRACT_URL_TEMPLATE = "https://api.elsevier.com/content/abstract/doi/{doi}"
SOURCE_NAME = "Scopus"


def is_available() -> bool:
    return bool(settings.SCOPUS_API_KEY)


def build_query_string(query_concept: dict[str, list[str]]) -> str:
    """Bangun query Scopus dari master query konseptual.

    Sintaks Scopus mendukung field code TITLE-ABS-KEY untuk mencari pada
    judul+abstract+keyword, serta operator boolean AND/OR eksplisit.
    """
    def group(terms: list[str]) -> str:
        quoted = " OR ".join(f'"{t}"' for t in terms)
        return f"({quoted})"

    a = group(query_concept["group_a"])
    b = group(query_concept["group_b"])
    c = group(query_concept["group_c"])
    return f"TITLE-ABS-KEY({a} AND {b} AND {c})"


def _headers() -> dict[str, str]:
    headers = {
        "X-ELS-APIKey": settings.SCOPUS_API_KEY or "",
        "Accept": "application/json",
    }
    if settings.SCOPUS_INSTTOKEN:
        headers["X-ELS-Insttoken"] = settings.SCOPUS_INSTTOKEN
    return headers


def _fetch_abstract(doi: Optional[str]) -> Optional[str]:
    """Panggil Abstract Retrieval API untuk satu DOI. Return None bila
    tidak ada DOI, gagal, atau abstract memang tidak tersedia."""
    if not doi:
        return None
    url = ABSTRACT_URL_TEMPLATE.format(doi=doi)
    try:
        resp = request_with_retry(
            "GET", url, headers=_headers(), source_name="Scopus-AbstractRetrieval"
        )
    except ConnectorError as exc:
        print(f"[Scopus] Gagal ambil abstract untuk DOI {doi}: {exc}")
        return None

    try:
        payload = resp.json()
        coredata = (
            payload.get("abstracts-retrieval-response", {}).get("coredata", {})
        )
        return coredata.get("dc:description")
    except Exception as exc:  # noqa: BLE001
        print(f"[Scopus] Gagal parse abstract untuk DOI {doi}: {exc}")
        return None


def search(
    query: dict[str, list[str]],
    start_year: int = settings.START_YEAR,
    end_year: int = settings.END_YEAR,
    limit: Optional[int] = settings.DEFAULT_LIMIT_PER_SOURCE,
    fetch_abstracts: bool = True,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    """Ambil dokumen dari Scopus Search API, lalu lengkapi abstract lewat
    Abstract Retrieval API (tahap kedua). Skip aman bila key tidak ada."""
    if not is_available():
        print(
            "[Scopus] SCOPUS_API_KEY tidak tersedia di environment; "
            "connector di-skip. Gunakan importer manual (.bib/.ris/.csv) "
            "sebagai jalur sementara (lihat importers/)."
        )
        return []

    query_string = build_query_string(query)

    if not force_refresh:
        cached = load_cache(SOURCE_NAME)
        if cached is not None:
            return _finalize(cached, query_string, fetch_abstracts, limit)

    date_range = f"{start_year}-{end_year}"
    print(f"[Scopus] Query aktual: {query_string} | date={date_range}")

    raw_entries: list[dict[str, Any]] = []
    start = 0
    count = settings.SCOPUS_PAGE_SIZE

    while True:
        params = {
            "query": query_string,
            "date": date_range,
            "start": start,
            "count": count,
            "httpAccept": "application/json",
        }
        try:
            resp = request_with_retry(
                "GET", SEARCH_URL, params=params, headers=_headers(), source_name="Scopus"
            )
        except ConnectorError as exc:
            print(f"[Scopus] Gagal mengambil data, pipeline lanjut ke sumber lain. Detail: {exc}")
            if raw_entries:
                save_cache(SOURCE_NAME, raw_entries)
            return _finalize(raw_entries, query_string, fetch_abstracts, limit)

        payload = resp.json()
        search_results = payload.get("search-results", {})
        entries = search_results.get("entry", [])

        # Scopus mengembalikan satu entry berisi "error" bila query kosong/salah
        if entries and "error" in entries[0]:
            print(f"[Scopus] API mengembalikan error: {entries[0]['error']}")
            break

        raw_entries.extend(entries)

        total_results = int(search_results.get("opensearch:totalResults", 0))
        start += count
        if start >= total_results or not entries:
            break
        if limit is not None and len(raw_entries) >= limit:
            raw_entries = raw_entries[:limit]
            break

    save_cache(SOURCE_NAME, raw_entries)
    return _finalize(raw_entries, query_string, fetch_abstracts, limit)


def _finalize(
    raw_entries: list[dict[str, Any]],
    query_string: str,
    fetch_abstracts: bool,
    limit: Optional[int],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for entry in raw_entries:
        try:
            doi = normalize_doi(entry.get("prism:doi"))
            abstract_text = _fetch_abstract(doi) if (fetch_abstracts and doi) else None
            results.append(normalize_scopus_record(entry, query_string, abstract_text))
        except Exception as exc:  # noqa: BLE001
            print(f"[Scopus] Gagal memparse satu record ({entry.get('eid')}): {exc}")

    print(f"[Scopus] Total record diambil: {len(results)}")
    return results
