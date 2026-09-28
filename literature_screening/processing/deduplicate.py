"""
processing/deduplicate.py
============================
Deduplikasi lintas 5 sumber (Bagian 11).

Urutan:
  Level 1 — DOI (normalize -> lowercase -> hapus prefix URL -> trim).
  Level 2 — Judul ternormalisasi (bila DOI tidak ada pada salah satu/
            keduanya): lowercase -> hapus tanda baca -> hapus whitespace
            berlebih.
  Level 3 — Fuzzy title matching (hanya untuk kandidat yang belum match
            di Level 1/2): similarity >= FUZZY_TITLE_THRESHOLD. TIDAK
            dihapus otomatis tanpa mencatat; kandidat di rentang
            [FUZZY_REVIEW_LOWER_BOUND, FUZZY_TITLE_THRESHOLD) dicatat ke
            log untuk ditinjau manual, tidak digabung otomatis.

Tiap record diberi: duplicate_group_id, duplicate_of, deduplication_method.

Saat merge duplicate:
  - source_database digabung (mis. "IEEE; OpenAlex; Crossref").
  - Field kosong dilengkapi dari sumber lain dalam grup yang sama
    (mis. abstract Crossref kosong dilengkapi dari OpenAlex bila DOI cocok).
  - Bila salah satu anggota grup punya `decision` final (IEEE), keputusan
    tersebut dipertahankan pada record hasil merge.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from config import settings

try:
    from rapidfuzz import fuzz as _rapidfuzz_fuzz

    def _token_sort_ratio(a: str, b: str) -> float:
        return _rapidfuzz_fuzz.token_sort_ratio(a, b)

except ImportError:  # pragma: no cover - fallback bila rapidfuzz belum terinstall
    import difflib

    print(
        "[Deduplicate] PERINGATAN: paket 'rapidfuzz' tidak ditemukan, "
        "memakai fallback difflib.SequenceMatcher (lebih lambat & sedikit "
        "kurang akurat). Untuk hasil terbaik: pip install rapidfuzz."
    )

    def _token_sort_ratio(a: str, b: str) -> float:
        """Fallback token_sort_ratio ala rapidfuzz memakai difflib.

        Urutkan token lalu bandingkan dengan SequenceMatcher, skor 0-100.
        """
        tokens_a = " ".join(sorted(a.split()))
        tokens_b = " ".join(sorted(b.split()))
        ratio = difflib.SequenceMatcher(None, tokens_a, tokens_b).ratio()
        return ratio * 100


def normalize_title(title: Optional[str]) -> str:
    if not title:
        return ""
    t = title.lower()
    t = re.sub(r"[^\w\s]", "", t)  # hapus tanda baca
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _merge_group(records: list[dict[str, Any]], group_id: int, method: str) -> dict[str, Any]:
    """Gabungkan satu grup duplikat menjadi satu record representatif."""
    # Pilih record dasar: prioritaskan yang sudah punya decision final (IEEE),
    # lalu yang punya abstract terpanjang (metadata paling lengkap).
    base = None
    for r in records:
        if r.get("decision") in ("Include", "Exclude"):
            base = r
            break
    if base is None:
        base = max(records, key=lambda r: len(r.get("abstract") or ""))

    merged = dict(base)

    # Gabungkan source_database (unik, urutan stabil sesuai kemunculan)
    sources = []
    for r in records:
        src = r.get("source_database")
        if src:
            for s in str(src).split(";"):
                s = s.strip()
                if s and s not in sources:
                    sources.append(s)
    merged["source_database"] = "; ".join(sources)

    # Lengkapi field kosong dari anggota lain dalam grup
    fillable_fields = ["abstract", "doi", "journal", "publisher", "document_type", "url", "open_access", "year"]
    for field in fillable_fields:
        if not merged.get(field):
            for r in records:
                if r.get(field):
                    merged[field] = r[field]
                    break

    # Simpan semua record_id anggota untuk audit
    merged["duplicate_group_id"] = group_id
    merged["duplicate_of"] = ", ".join(r["record_id"] for r in records if r is not base)
    merged["deduplication_method"] = method

    return merged


def deduplicate(
    records: list[dict[str, Any]],
    fuzzy_threshold: int = settings.FUZZY_TITLE_THRESHOLD,
    fuzzy_review_lower: int = settings.FUZZY_REVIEW_LOWER_BOUND,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Deduplikasi lintas sumber. Return (unique_records, fuzzy_review_log).

    unique_records: list record setelah merge duplikat (DOI + title exact),
        masing-masing dengan duplicate_group_id/duplicate_of/deduplication_method
        terisi (None bila tidak berduplikat).
    fuzzy_review_log: pasangan kandidat fuzzy yang skornya di rentang
        [fuzzy_review_lower, fuzzy_threshold) — dicatat untuk tinjauan
        manual, TIDAK digabung otomatis.
    """
    n = len(records)
    for r in records:
        r.setdefault("duplicate_group_id", None)
        r.setdefault("duplicate_of", None)
        r.setdefault("deduplication_method", None)

    parent = list(range(n))  # union-find untuk mengelompokkan duplikat

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    method_by_pair: dict[tuple[int, int], str] = {}

    # ---------------- Level 1: DOI ----------------
    doi_index: dict[str, int] = {}
    for i, r in enumerate(records):
        doi = r.get("doi")
        if not doi:
            continue
        if doi in doi_index:
            union(doi_index[doi], i)
            method_by_pair[(min(doi_index[doi], i), max(doi_index[doi], i))] = "doi"
        else:
            doi_index[doi] = i

    # ---------------- Level 2: Judul ternormalisasi (tanpa DOI match) ----------------
    title_index: dict[str, int] = {}
    for i, r in enumerate(records):
        norm_title = normalize_title(r.get("title"))
        if not norm_title:
            continue
        if norm_title in title_index:
            j = title_index[norm_title]
            if find(i) != find(j):
                union(i, j)
                method_by_pair.setdefault((min(i, j), max(i, j)), "title_exact")
        else:
            title_index[norm_title] = i

    # ---------------- Level 3: Fuzzy title (hanya kandidat belum match) ----------------
    fuzzy_review_log: list[dict[str, Any]] = []
    root_counts: dict[int, int] = {}
    for i in range(n):
        root_counts[find(i)] = root_counts.get(find(i), 0) + 1
    unmatched_indices = [i for i in range(n) if root_counts[find(i)] == 1]
    # Bandingkan tiap pasang di antara unmatched_indices (brute-force wajar
    # untuk skala ratusan-ribuan record hasil filter; untuk dataset sangat
    # besar bisa dioptimasi dengan blocking, namun di luar scope wajib).
    titles_norm = {i: normalize_title(records[i].get("title")) for i in unmatched_indices}
    checked_pairs = set()
    for idx_a in range(len(unmatched_indices)):
        i = unmatched_indices[idx_a]
        if not titles_norm[i]:
            continue
        for idx_b in range(idx_a + 1, len(unmatched_indices)):
            j = unmatched_indices[idx_b]
            if not titles_norm[j] or find(i) == find(j):
                continue
            pair = (i, j)
            if pair in checked_pairs:
                continue
            checked_pairs.add(pair)

            score = _token_sort_ratio(titles_norm[i], titles_norm[j])
            if score >= fuzzy_threshold:
                union(i, j)
                method_by_pair[(min(i, j), max(i, j))] = "fuzzy"
            elif score >= fuzzy_review_lower:
                fuzzy_review_log.append(
                    {
                        "record_id_a": records[i]["record_id"],
                        "title_a": records[i].get("title"),
                        "record_id_b": records[j]["record_id"],
                        "title_b": records[j].get("title"),
                        "similarity_score": score,
                        "note": "Kandidat duplikat confidence sedang — perlu tinjauan manual, TIDAK digabung otomatis.",
                    }
                )

    # ---------------- Bentuk grup akhir & merge ----------------
    groups: dict[int, list[int]] = {}
    for i in range(n):
        root = find(i)
        groups.setdefault(root, []).append(i)

    unique_records: list[dict[str, Any]] = []
    group_counter = 0
    for root, members in groups.items():
        if len(members) == 1:
            rec = records[members[0]]
            rec["duplicate_group_id"] = None
            rec["duplicate_of"] = None
            rec["deduplication_method"] = None
            unique_records.append(rec)
        else:
            group_counter += 1
            group_records = [records[m] for m in members]
            # Tentukan metode dominan untuk grup ini (ambil yang tercatat pertama)
            method = "doi"
            for m1 in members:
                for m2 in members:
                    key = (min(m1, m2), max(m1, m2))
                    if key in method_by_pair:
                        method = method_by_pair[key]
                        break
            merged = _merge_group(group_records, group_counter, method)
            unique_records.append(merged)

    n_duplicates_removed = n - len(unique_records)
    print(
        f"[Deduplicate] {n} record -> {len(unique_records)} unique "
        f"({n_duplicates_removed} duplikat digabung). "
        f"{len(fuzzy_review_log)} pasangan fuzzy confidence-sedang dicatat untuk review."
    )
    return unique_records, fuzzy_review_log
