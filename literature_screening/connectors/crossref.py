"""
connectors/crossref.py
========================
Connector API Crossref (https://api.crossref.org/works).

Referensi resmi: https://api.crossref.org/swagger-ui/index.html
dan https://github.com/CrossRef/rest-api-doc

- Tanpa API key. Polite pool diaktifkan dengan menyertakan `mailto=<email>`
  pada query param (kita juga menambahkannya ke User-Agent) -> rate limit
  lebih baik & prioritas server terpisah (Bagian 2.3, 6).
- Query: parameter `query.bibliographic` untuk pencarian bibliografis
  bebas (title+author+dll), lebih relevan untuk kueri seperti master
  query dibanding `query` generik.
- Filter tahun: `filter=from-pub-date:2024-01-01,until-pub-date:2026-12-31`.
- Pagination: `rows` (maks 1000/halaman, kita pakai nilai wajar dari
  config) + `offset`, atau deep-paging dengan `cursor=*` lalu ikuti
  `message.next-cursor`. Kita pakai cursor untuk mendukung deep paging
  dataset besar.
- Abstract sering kosong (hanya ada bila publisher menyetor JATS XML).
  Bila ada -> dibersihkan oleh processing.normalize.strip_jats_xml().
  Bila tidak ada -> None (BUKAN indikasi record cacat).
"""

from __future__ import annotations

from typing import Any, Optional

from config import settings
from connectors.http_utils import ConnectorError, request_with_retry
from connectors.raw_cache import load_cache, save_cache
from processing.normalize import normalize_crossref_record

BASE_URL = "https://api.crossref.org/works"
SOURCE_NAME = "Crossref"


def build_query_string(query_concept: dict[str, list[str]]) -> str:
    """Bangun query bibliografis Crossref dari master query konseptual.

    Crossref `query.bibliographic` tidak mendukung operator boolean
    eksplisit (AND/OR) seperti OpenAlex — ia melakukan relevance ranking
    atas semua term yang diberikan. Untuk mendekati semantik AND antar
    grup & OR di dalam grup, kita kirim seluruh term sebagai satu string
    (Crossref akan me-rank berdasarkan kecocokan), dan penyaringan presisi
    dilakukan lebih lanjut pada tahap screening manual (title/abstract).
    Pendekatan ini didokumentasikan agar transparan (bukan filter presisi
    seperti OpenAlex/Scopus/WOS yang mendukung boolean penuh).
    """
    all_terms = (
        query_concept["group_a"] + query_concept["group_b"] + query_concept["group_c"]
    )
    return " ".join(all_terms)


def fetch_raw(
    query: dict[str, list[str]],
    start_year: int = settings.START_YEAR,
    end_year: int = settings.END_YEAR,
    limit: Optional[int] = settings.DEFAULT_LIMIT_PER_SOURCE,
    force_refresh: bool = False,
) -> tuple[list[dict[str, Any]], str]:
    """Ambil raw items dari Crossref (sebelum normalisasi), dengan raw
    cache harian untuk idempotency. Return (raw_items, bibliographic_query)."""
    bibliographic = build_query_string(query)

    if not force_refresh:
        cached = load_cache(SOURCE_NAME)
        if cached is not None:
            return cached, bibliographic

    if not settings.CROSSREF_MAILTO:
        raise ConnectorError(
            "[Crossref] CROSSREF_MAILTO tidak diset di .env. "
            "Crossref mewajibkan mailto untuk polite pool yang stabil; "
            "isi CROSSREF_MAILTO lalu jalankan ulang."
        )

    print(f"[Crossref] Query aktual (query.bibliographic): {bibliographic}")

    raw_items: list[dict[str, Any]] = []
    cursor = "*"
    rows = settings.CROSSREF_PAGE_SIZE

    while True:
        params = {
            "query.bibliographic": bibliographic,
            "filter": (
                f"from-pub-date:{start_year}-01-01,"
                f"until-pub-date:{end_year}-12-31"
            ),
            "rows": rows,
            "cursor": cursor,
            "mailto": settings.CROSSREF_MAILTO,
        }
        resp = request_with_retry("GET", BASE_URL, params=params, source_name=SOURCE_NAME)
        payload = resp.json()
        message = payload.get("message", {})
        items = message.get("items", [])
        raw_items.extend(items)

        if limit is not None and len(raw_items) >= limit:
            raw_items = raw_items[:limit]
            break

        next_cursor = message.get("next-cursor")
        if not next_cursor or not items:
            break
        cursor = next_cursor

    save_cache(SOURCE_NAME, raw_items)
    return raw_items, bibliographic


def search(
    query: dict[str, list[str]],
    start_year: int = settings.START_YEAR,
    end_year: int = settings.END_YEAR,
    limit: Optional[int] = settings.DEFAULT_LIMIT_PER_SOURCE,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    """Ambil works dari Crossref sesuai master query & rentang tahun,
    lalu normalisasi ke schema standar (termasuk pembersihan JATS/XML)."""
    raw_items, bibliographic = fetch_raw(query, start_year, end_year, limit, force_refresh)

    results: list[dict[str, Any]] = []
    for item in raw_items:
        try:
            results.append(normalize_crossref_record(item, bibliographic))
        except Exception as exc:  # noqa: BLE001
            print(f"[Crossref] Gagal memparse satu record ({item.get('DOI')}): {exc}")

    print(f"[Crossref] Total record diambil: {len(results)}")
    return results
