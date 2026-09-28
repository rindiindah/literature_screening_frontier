"""
connectors/wos.py
====================
Connector API Web of Science (Clarivate) — AKTIF OTOMATIS bila WOS_API_KEY
tersedia; SKIP AMAN bila tidak.

Referensi resmi: https://developer.clarivate.com/apis/wos-starter
(Web of Science Starter API — REST, JSON, autentikasi via header X-ApiKey).

Catatan teknis wajib (Bagian 2.5):
- Starter API menyediakan metadata bibliografis dasar (judul, penulis,
  sumber, identifiers, doctypes) TAPI TIDAK menyediakan abstract penuh.
  Abstract lengkap hanya tersedia di WOS Expanded API (butuh entitlement
  berbeda/lebih tinggi). Karena spesifikasi hanya meminta "starter API
  jika Expanded belum ada", kita implementasikan Starter API dan
  mendokumentasikan keterbatasan ini secara eksplisit -> field `abstract`
  akan bernilai None untuk hasil WOS Starter (bukan cacat, memang
  keterbatasan API tier ini).
- Query: parameter `q` dengan sintaks field tag WOS, mis.
  TS=(...) untuk Topic Search, AND/OR eksplisit, PY=tahun untuk rentang.
- Pagination: `limit` (maks 50/halaman pada Starter API) + `page`.

Jika WOS_API_KEY tidak ada -> connector cetak pesan jelas & return [].
"""

from __future__ import annotations

from typing import Any, Optional

from config import settings
from connectors.http_utils import ConnectorError, request_with_retry
from connectors.raw_cache import load_cache, save_cache
from processing.normalize import normalize_wos_record

BASE_URL = "https://api.clarivate.com/apis/wos-starter/v1/documents"
SOURCE_NAME = "WoS"

API_TIER_USED = "Web of Science Starter API"
AVAILABLE_FIELDS_NOTE = (
    "Starter API menyediakan: uid, title, authors, source (journal, tahun), "
    "doctypes, identifiers (DOI, ISSN). TIDAK menyediakan abstract penuh "
    "(memerlukan WOS Expanded API dengan entitlement terpisah)."
)


def is_available() -> bool:
    return bool(settings.WOS_API_KEY)


def build_query_string(query_concept: dict[str, list[str]]) -> str:
    """Bangun query WOS Starter dari master query konseptual.

    Sintaks WOS: TS=(...) untuk Topic Search (judul+abstract+keyword),
    dengan operator boolean AND/OR eksplisit dan tanda kutip untuk frasa.
    """
    def group(terms: list[str]) -> str:
        quoted = " OR ".join(f'"{t}"' for t in terms)
        return f"({quoted})"

    a = group(query_concept["group_a"])
    b = group(query_concept["group_b"])
    c = group(query_concept["group_c"])
    return f"TS=({a} AND {b} AND {c})"


def _headers() -> dict[str, str]:
    return {"X-ApiKey": settings.WOS_API_KEY or "", "Accept": "application/json"}


def search(
    query: dict[str, list[str]],
    start_year: int = settings.START_YEAR,
    end_year: int = settings.END_YEAR,
    limit: Optional[int] = settings.DEFAULT_LIMIT_PER_SOURCE,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    """Ambil dokumen dari WOS Starter API. Skip aman bila key tidak ada."""
    if not is_available():
        print(
            "[WoS] WOS_API_KEY tidak tersedia di environment; connector "
            "di-skip. Gunakan importer manual (.bib/.ris/.csv) sebagai "
            "jalur sementara (lihat importers/)."
        )
        return []

    query_string = build_query_string(query)

    if not force_refresh:
        cached = load_cache(SOURCE_NAME)
        if cached is not None:
            return _normalize_hits(cached, query_string)

    print(f"[WoS] Menggunakan {API_TIER_USED}. {AVAILABLE_FIELDS_NOTE}")
    print(f"[WoS] Query aktual: {query_string} | tahun={start_year}-{end_year}")

    raw_hits: list[dict[str, Any]] = []
    page = 1
    page_limit = min(settings.WOS_PAGE_SIZE, 50)  # 50 = maksimum Starter API

    while True:
        params = {
            "db": "WOS",
            "q": f"{query_string} AND PY=({start_year}-{end_year})",
            "limit": page_limit,
            "page": page,
        }
        try:
            resp = request_with_retry(
                "GET", BASE_URL, params=params, headers=_headers(), source_name=SOURCE_NAME
            )
        except ConnectorError as exc:
            print(f"[WoS] Gagal mengambil data, pipeline lanjut ke sumber lain. Detail: {exc}")
            break

        payload = resp.json()
        hits = payload.get("hits", [])
        raw_hits.extend(hits)

        total_found = payload.get("metadata", {}).get("total", 0)
        if limit is not None and len(raw_hits) >= limit:
            raw_hits = raw_hits[:limit]
            break
        if not hits or page * page_limit >= total_found:
            break
        page += 1

    if raw_hits:
        save_cache(SOURCE_NAME, raw_hits)
    return _normalize_hits(raw_hits, query_string)


def _normalize_hits(raw_hits: list[dict[str, Any]], query_string: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for doc in raw_hits:
        try:
            results.append(normalize_wos_record(doc, query_string))
        except Exception as exc:  # noqa: BLE001
            print(f"[WoS] Gagal memparse satu record ({doc.get('uid')}): {exc}")
    print(f"[WoS] Total record diambil: {len(results)}")
    return results
