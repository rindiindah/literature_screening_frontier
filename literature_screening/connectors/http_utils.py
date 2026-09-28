"""
connectors/http_utils.py
=========================
Utilitas HTTP bersama untuk semua connector (OpenAlex, Crossref, Scopus,
WOS): request dengan retry wajar (bukan infinite), timeout, backoff, dan
penanganan error HTTP yang konsisten + logging ringkas ke stdout.

Prinsip (Bagian 22 spesifikasi):
- Jangan mengarang data bila API gagal/tidak dapat diakses -> raise
  ConnectorError yang jelas, connector pemanggil menangkapnya dan skip aman.
- Retry wajar: MAX_RETRIES kali dengan exponential backoff, hanya untuk
  error yang masuk akal untuk di-retry (timeout, 429, 5xx).
"""

from __future__ import annotations

import time
from typing import Any, Optional

import requests

from config import settings


class ConnectorError(Exception):
    """Error yang dilempar ketika sebuah connector gagal mengambil data
    secara sah (kredensial tidak ada, API tidak dapat diakses, dsb.)."""


def request_with_retry(
    method: str,
    url: str,
    *,
    params: Optional[dict[str, Any]] = None,
    headers: Optional[dict[str, str]] = None,
    json_body: Optional[dict[str, Any]] = None,
    timeout: int = settings.REQUEST_TIMEOUT_SECONDS,
    max_retries: int = settings.MAX_RETRIES,
    source_name: str = "unknown",
) -> requests.Response:
    """Kirim HTTP request dengan retry wajar untuk kondisi transient.

    Melempar ConnectorError bila semua percobaan gagal, atau bila
    response berstatus error yang tidak layak di-retry (400, 401, 403, 404).
    """
    last_exc: Optional[Exception] = None
    headers = dict(headers or {})
    headers.setdefault("User-Agent", settings.USER_AGENT)

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.request(
                method=method,
                url=url,
                params=params,
                headers=headers,
                json=json_body,
                timeout=timeout,
            )
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            print(f"[{source_name}] Percobaan {attempt}/{max_retries} gagal (network): {exc}")
            _sleep_backoff(attempt)
            continue

        if resp.status_code == 200:
            return resp

        # Non-retryable client errors -> gagal langsung dengan pesan jelas
        if resp.status_code in (400, 401, 403, 404):
            raise ConnectorError(
                f"[{source_name}] HTTP {resp.status_code} pada {url} — "
                f"kemungkinan kredensial salah/tidak berizin, atau endpoint/parameter salah. "
                f"Body: {resp.text[:500]}"
            )

        # Retryable: 429 (rate limit) atau 5xx (server error)
        if resp.status_code == 429 or 500 <= resp.status_code < 600:
            last_exc = ConnectorError(
                f"[{source_name}] HTTP {resp.status_code} (retryable) pada {url}"
            )
            print(f"[{source_name}] Percobaan {attempt}/{max_retries} gagal: HTTP {resp.status_code}. Retrying...")
            _sleep_backoff(attempt)
            continue

        # Status lain yang tidak diantisipasi -> gagal dengan pesan jelas
        raise ConnectorError(
            f"[{source_name}] HTTP {resp.status_code} tidak terduga pada {url}. "
            f"Body: {resp.text[:500]}"
        )

    raise ConnectorError(
        f"[{source_name}] Gagal setelah {max_retries} percobaan pada {url}. "
        f"Error terakhir: {last_exc}"
    )


def _sleep_backoff(attempt: int) -> None:
    delay = settings.RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
    time.sleep(delay)
