"""
connectors/raw_cache.py
=========================
Penyimpanan & pembacaan response mentah API (Bagian 9: Raw Data
Preservation) sekaligus mendukung idempotency (Bagian 22 prinsip #14):
"Kode idempotent: bisa rerun tanpa mengulang proses yang tidak perlu
(manfaatkan raw cache)."

Konvensi nama file: data/raw/<source>_<YYYY-MM-DD>.json
Bila file untuk tanggal hari ini sudah ada dan `force_refresh=False`,
connector akan membaca dari cache ini alih-alih memanggil API lagi.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Optional

from config import settings


def _cache_path(source: str, run_date: Optional[str] = None) -> Path:
    run_date = run_date or date.today().isoformat()
    return settings.RAW_DIR / f"{source.lower()}_{run_date}.json"


def load_cache(source: str, run_date: Optional[str] = None) -> Optional[list[dict[str, Any]]]:
    path = _cache_path(source, run_date)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            print(f"[{source}] Memakai raw cache: {path} ({len(data)} item). "
                  f"Gunakan --force-refresh untuk memanggil API ulang.")
            return data
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[{source}] Gagal membaca cache {path}: {exc}. Akan fetch ulang.")
    return None


def save_cache(source: str, raw_items: list[dict[str, Any]], run_date: Optional[str] = None) -> Path:
    path = _cache_path(source, run_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(raw_items, f, ensure_ascii=False)
    print(f"[{source}] Raw response ({len(raw_items)} item) disimpan ke {path}")
    return path
