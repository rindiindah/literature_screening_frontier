"""
connectors/openalex.py
========================
Connector API OpenAlex (https://api.openalex.org/works).

Referensi resmi: https://docs.openalex.org/api-entities/works/search-works
- Pencarian teks bebas: parameter `search` (full-text relevance search).
- Filter tahun: `filter=publication_year:2024-2026` atau
  `from_publication_date` / `to_publication_date`.
- Autentikasi: tanpa API key tetap bisa akses "polite pool" dengan
  menyertakan `mailto=<email>` -> rate limit lebih baik & stabil.
  Bila `OPENALEX_API_KEY` tersedia, disertakan sebagai `api_key` untuk
  kuota/rate limit lebih tinggi (opsional, sesuai Bagian 6).
- Pagination: cursor-based (`cursor=*` lalu ikuti `meta.next_cursor`),
  direkomendasikan untuk deep paging dan dipakai di sini.
- Abstract dikirim sebagai `abstract_inverted_index` -> direkonstruksi
  oleh processing.normalize.reconstruct_openalex_abstract().

Bila `abstract_inverted_index` null, abstract di-set None (tidak dikarang).
"""

from __future__ import annotations

from typing import Any, Optional

from config import settings
from connectors.http_utils import ConnectorError, request_with_retry
from connectors.raw_cache import load_cache, save_cache
from processing.normalize import normalize_openalex_record

BASE_URL = "https://api.openalex.org/works"
SOURCE_NAME = "OpenAlex"


def build_query_string(query_concept: dict[str, list[str]]) -> str:
    """Bangun query OpenAlex dari master query konseptual.

    OpenAlex mendukung sintaks boolean sederhana pada parameter `search`:
    tanda kutip untuk frasa, `OR`, dan spasi berarti AND antar term.
    Kita satukan tiap grup dengan OR di dalam tanda kurung, lalu AND
    antar grup (secara implisit lewat penggabungan search string dengan
    kata kunci AND — OpenAlex mendukung operator AND/OR/NOT eksplisit
    pada parameter `search` sejak beberapa versi API; sebagai fallback
    yang aman kita tulis eksplisit).
    """
    def group(terms: list[str]) -> str:
        quoted = [f'"{t}"' for t in terms]
        return "(" + " OR ".join(quoted) + ")"

    parts = [
        group(query_concept["group_a"]),
        group(query_concept["group_b"]),
        group(query_concept["group_c"]),
    ]
    return " AND ".join(parts)


def fetch_raw(
    query: dict[str, list[str]],
    start_year: int = settings.START_YEAR,
    end_year: int = settings.END_YEAR,
    limit: Optional[int] = settings.DEFAULT_LIMIT_PER_SOURCE,
    force_refresh: bool = False,
) -> tuple[list[dict[str, Any]], str]:
    """Ambil raw work items dari OpenAlex (sebelum normalisasi).

    Memakai raw cache harian (data/raw/openalex_<tanggal>.json) agar
    idempotent: rerun di hari yang sama tidak memanggil API ulang kecuali
    force_refresh=True. Return (raw_items, search_query_string).
    """
    search_str = build_query_string(query)

    if not force_refresh:
        cached = load_cache(SOURCE_NAME)
        if cached is not None:
            return cached, search_str

    if not settings.OPENALEX_MAILTO:
        print(
            "[OpenAlex] PERINGATAN: OPENALEX_MAILTO tidak diset. "
            "Tetap mencoba tanpa polite pool (rate limit lebih ketat)."
        )

    print(f"[OpenAlex] Query aktual: {search_str}")

    raw_items: list[dict[str, Any]] = []
    cursor = "*"
    page_size = settings.OPENALEX_PAGE_SIZE

    while True:
        params: dict[str, Any] = {
            "search": search_str,
            "filter": f"publication_year:{start_year}-{end_year}",
            "per_page": page_size,
            "cursor": cursor,
        }
        if settings.OPENALEX_MAILTO:
            params["mailto"] = settings.OPENALEX_MAILTO
        if settings.OPENALEX_API_KEY:
            params["api_key"] = settings.OPENALEX_API_KEY

        resp = request_with_retry("GET", BASE_URL, params=params, source_name=SOURCE_NAME)
        payload = resp.json()

        works = payload.get("results", [])
        raw_items.extend(works)

        if limit is not None and len(raw_items) >= limit:
            raw_items = raw_items[:limit]
            break

        cursor = (payload.get("meta") or {}).get("next_cursor")
        if not cursor or not works:
            break

    save_cache(SOURCE_NAME, raw_items)
    return raw_items, search_str


def search(
    query: dict[str, list[str]],
    start_year: int = settings.START_YEAR,
    end_year: int = settings.END_YEAR,
    limit: Optional[int] = settings.DEFAULT_LIMIT_PER_SOURCE,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    """Ambil works dari OpenAlex sesuai master query & rentang tahun,
    lalu normalisasi ke schema standar (termasuk rekonstruksi abstract
    dari abstract_inverted_index)."""
    raw_items, search_str = fetch_raw(query, start_year, end_year, limit, force_refresh)

    results: list[dict[str, Any]] = []
    for work in raw_items:
        try:
            results.append(normalize_openalex_record(work, search_str))
        except Exception as exc:  # noqa: BLE001 - jangan gagal total karena 1 record rusak
            print(f"[OpenAlex] Gagal memparse satu record ({work.get('id')}): {exc}")

    print(f"[OpenAlex] Total record diambil: {len(results)}")
    return results
