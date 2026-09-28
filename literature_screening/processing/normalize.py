"""
processing/normalize.py
=========================
Mengubah response mentah dari tiap sumber (OpenAlex, Crossref, Scopus,
WOS, dan hasil import IEEE/manual) menjadi SATU schema standar
(Bagian 7 spesifikasi).

Field standar:
    record_id, title, abstract, authors, year, doi, journal, publisher,
    document_type, url, open_access, source_database, source_id,
    search_query, retrieved_at

Aturan wajib:
- Field yang tidak tersedia dari suatu sumber -> None / kosong. TIDAK
  BOLEH diisi karangan (Bagian 7, Bagian 22 prinsip #4).
- OpenAlex: abstract dikirim sebagai abstract_inverted_index -> harus
  direkonstruksi menjadi teks utuh (Bagian 2.2, 22.15).
- Crossref: abstract sering kosong; bila ada, dalam format JATS/XML ->
  harus dibersihkan jadi teks polos (Bagian 2.3, 22.16).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

STANDARD_FIELDS = [
    "record_id",
    "title",
    "abstract",
    "authors",
    "year",
    "doi",
    "journal",
    "publisher",
    "document_type",
    "url",
    "open_access",
    "source_database",
    "source_id",
    "search_query",
    "retrieved_at",
]

# Pemetaan document_type mentah (berbagai istilah tiap sumber) ke label
# generik yang dipakai untuk filtering (Bagian 10, config.ALLOWED_DOCUMENT_TYPES).
_DOCUMENT_TYPE_MAP = {
    # OpenAlex "type"
    "article": "article",
    "journal-article": "article",
    "proceedings-article": "proceedings paper",
    "proceedings": "proceedings paper",
    "book-chapter": "book chapter",
    "review": "review",
    "preprint": "preprint",
    "posted-content": "preprint",
    "dataset": "dataset",
    "other": "other",
    # Crossref "type"
    "journal-article-crossref": "article",
    "proceedings-article-crossref": "proceedings paper",
    # BibTeX ENTRYTYPE (importer IEEE/manual)
    "inproceedings": "conference paper",
    "incollection": "book chapter",
    "inbook": "book chapter",
    "techreport": "other",
    "phdthesis": "other",
    "mastersthesis": "other",
    "unpublished": "other",
    "misc": "other",
    # Scopus "subtypeDescription" / "aggregationType"
    "article-scopus": "article",
    "conference paper": "conference paper",
    "conference-paper": "conference paper",
    "review-scopus": "review",
    # WOS "doctype"
    "article; proceedings paper": "conference paper",
    "proceedings paper": "proceedings paper",
    "meeting abstract": "other",
}


def now_iso() -> str:
    """Timestamp ISO 8601 dengan offset lokal (dipakai untuk retrieved_at)."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def empty_record() -> dict[str, Any]:
    return {field: None for field in STANDARD_FIELDS}


def make_record_id(source_database: str, source_id: Optional[str], fallback_seed: str) -> str:
    """Buat record_id stabil: SOURCE-ID (huruf besar untuk sumber)."""
    prefix = source_database.upper().replace(" ", "")
    if source_id:
        clean_id = str(source_id).strip().replace(" ", "_")
        return f"{prefix}-{clean_id}"
    # fallback bila source_id tidak ada: hash pendek dari judul/DOI
    import hashlib

    h = hashlib.sha1(fallback_seed.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}-{h}"


def normalize_document_type(raw_type: Optional[str]) -> Optional[str]:
    if not raw_type:
        return None
    key = str(raw_type).strip().lower()
    return _DOCUMENT_TYPE_MAP.get(key, key)  # simpan apa adanya bila tidak dikenal


def normalize_doi(raw_doi: Optional[str]) -> Optional[str]:
    """DOI -> lowercase, hapus prefix URL, trim (dipakai juga saat dedup)."""
    if not raw_doi:
        return None
    doi = str(raw_doi).strip().lower()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)
    doi = doi.strip().strip("/")
    return doi or None


def normalize_year(raw_year: Any) -> Optional[int]:
    if raw_year is None:
        return None
    try:
        return int(str(raw_year)[:4])
    except (ValueError, TypeError):
        return None


# ----------------------------------------------------------------------
# OpenAlex
# ----------------------------------------------------------------------
def reconstruct_openalex_abstract(inverted_index: Optional[dict[str, list[int]]]) -> Optional[str]:
    """Rekonstruksi teks abstract dari abstract_inverted_index OpenAlex.

    Format: {"word": [posisi0, posisi1, ...], ...}
    Jika None/kosong -> None (jangan mengarang).
    """
    if not inverted_index:
        return None
    position_map: dict[int, str] = {}
    for word, positions in inverted_index.items():
        for pos in positions:
            position_map[pos] = word
    if not position_map:
        return None
    max_pos = max(position_map.keys())
    words = [position_map.get(i, "") for i in range(max_pos + 1)]
    text = " ".join(w for w in words if w)
    return text.strip() or None


def normalize_openalex_record(work: dict[str, Any], search_query: str) -> dict[str, Any]:
    rec = empty_record()

    openalex_id_full = work.get("id") or ""
    source_id = openalex_id_full.rsplit("/", 1)[-1] if openalex_id_full else None

    title = work.get("display_name") or work.get("title")

    abstract = reconstruct_openalex_abstract(work.get("abstract_inverted_index"))

    authors = []
    for authorship in work.get("authorships") or []:
        name = (authorship.get("author") or {}).get("display_name")
        if name:
            authors.append(name)

    primary_location = work.get("primary_location") or {}
    source_info = primary_location.get("source") or {}
    journal = source_info.get("display_name")
    publisher = source_info.get("host_organization_name") or source_info.get("publisher")

    doi = normalize_doi(work.get("doi"))
    year = normalize_year(work.get("publication_year"))
    doc_type = normalize_document_type(work.get("type"))
    open_access = ((work.get("open_access") or {}).get("is_oa"))
    url = work.get("id") or (work.get("primary_location") or {}).get("landing_page_url")

    rec.update(
        {
            "record_id": make_record_id("OpenAlex", source_id, title or openalex_id_full or ""),
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "year": year,
            "doi": doi,
            "journal": journal,
            "publisher": publisher,
            "document_type": doc_type,
            "url": url,
            "open_access": open_access,
            "source_database": "OpenAlex",
            "source_id": source_id,
            "search_query": search_query,
            "retrieved_at": now_iso(),
        }
    )
    return rec


# ----------------------------------------------------------------------
# Crossref
# ----------------------------------------------------------------------
_JATS_TAG_RE = re.compile(r"<[^>]+>")


def strip_jats_xml(raw_abstract: Optional[str]) -> Optional[str]:
    """Bersihkan abstract Crossref dari tag JATS/XML menjadi teks polos.

    Bila tidak ada abstract -> None (bukan cacat, memang wajar kosong
    di Crossref sesuai Bagian 2.3).
    """
    if not raw_abstract:
        return None
    text = _JATS_TAG_RE.sub(" ", raw_abstract)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def normalize_crossref_record(item: dict[str, Any], search_query: str) -> dict[str, Any]:
    rec = empty_record()

    doi = normalize_doi(item.get("DOI"))
    title_list = item.get("title") or []
    title = title_list[0] if title_list else None

    abstract = strip_jats_xml(item.get("abstract"))

    authors = []
    for a in item.get("author") or []:
        given = a.get("given", "")
        family = a.get("family", "")
        full = f"{given} {family}".strip()
        if full:
            authors.append(full)
        elif a.get("name"):  # organisasi sebagai author
            authors.append(a["name"])

    year = None
    date_parts = ((item.get("published") or {}).get("date-parts")) or (
        (item.get("published-print") or {}).get("date-parts")
    ) or ((item.get("published-online") or {}).get("date-parts"))
    if date_parts and date_parts[0]:
        year = normalize_year(date_parts[0][0])

    container_title = item.get("container-title") or []
    journal = container_title[0] if container_title else None
    publisher = item.get("publisher")
    doc_type = normalize_document_type(item.get("type"))
    url = item.get("URL")

    rec.update(
        {
            "record_id": make_record_id("Crossref", doi, title or ""),
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "year": year,
            "doi": doi,
            "journal": journal,
            "publisher": publisher,
            "document_type": doc_type,
            "url": url,
            "open_access": None,  # Crossref tidak konsisten menyediakan status OA
            "source_database": "Crossref",
            "source_id": doi,
            "search_query": search_query,
            "retrieved_at": now_iso(),
        }
    )
    return rec


# ----------------------------------------------------------------------
# Scopus
# ----------------------------------------------------------------------
def normalize_scopus_record(entry: dict[str, Any], search_query: str, abstract_text: Optional[str] = None) -> dict[str, Any]:
    rec = empty_record()

    doi = normalize_doi(entry.get("prism:doi"))
    eid = entry.get("eid")
    title = entry.get("dc:title")

    # Author search API tidak selalu memberi list author lengkap;
    # field "dc:creator" biasanya hanya penulis pertama.
    authors = []
    creator = entry.get("dc:creator")
    if creator:
        authors.append(creator)
    for author_entry in entry.get("author") or []:
        name = author_entry.get("authname")
        if name and name not in authors:
            authors.append(name)

    year = None
    cover_date = entry.get("prism:coverDate")
    if cover_date:
        year = normalize_year(cover_date[:4])

    journal = entry.get("prism:publicationName")
    publisher = None  # Scopus Search API tidak selalu punya field publisher eksplisit
    doc_type = normalize_document_type(entry.get("subtypeDescription") or entry.get("aggregationType"))
    url = None
    for link in entry.get("link") or []:
        if link.get("@ref") == "scopus":
            url = link.get("@href")
            break
    open_access = None
    oa_flag = entry.get("openaccessFlag")
    if oa_flag is not None:
        open_access = bool(oa_flag)

    rec.update(
        {
            "record_id": make_record_id("Scopus", eid or doi, title or ""),
            "title": title,
            "abstract": abstract_text,  # diisi dari Abstract Retrieval API (tahap terpisah)
            "authors": authors,
            "year": year,
            "doi": doi,
            "journal": journal,
            "publisher": publisher,
            "document_type": doc_type,
            "url": url,
            "open_access": open_access,
            "source_database": "Scopus",
            "source_id": eid,
            "search_query": search_query,
            "retrieved_at": now_iso(),
        }
    )
    return rec


# ----------------------------------------------------------------------
# Web of Science (Starter API)
# ----------------------------------------------------------------------
def normalize_wos_record(doc: dict[str, Any], search_query: str) -> dict[str, Any]:
    rec = empty_record()

    uid = doc.get("uid")
    title = None
    for t in (doc.get("title") or []):
        if isinstance(t, dict) and t.get("type") == "item":
            title = t.get("title")
            break
    if title is None and isinstance(doc.get("title"), str):
        title = doc.get("title")

    # WOS Starter API TIDAK menyediakan abstract penuh (lihat Bagian 2.5) ->
    # tetap None kecuali dokumen memuatnya eksplisit.
    abstract = doc.get("abstract")

    authors = []
    names = (doc.get("names") or {}).get("authors") or []
    for a in names:
        name = a.get("displayName") or a.get("wosStandard")
        if name:
            authors.append(name)

    year = normalize_year((doc.get("source") or {}).get("publishYear"))
    journal = (doc.get("source") or {}).get("sourceTitle")
    publisher = None
    doc_type = None
    doctypes = doc.get("doctypes") or []
    if doctypes:
        doc_type = normalize_document_type(doctypes[0])

    doi = None
    for identifier in (doc.get("identifiers") or {}).get("other") or []:
        if identifier.get("type", "").lower() == "doi":
            doi = normalize_doi(identifier.get("value"))
            break
    if not doi:
        doi = normalize_doi((doc.get("identifiers") or {}).get("doi"))

    url = f"https://www.webofscience.com/wos/woscc/full-record/{uid}" if uid else None

    rec.update(
        {
            "record_id": make_record_id("WoS", uid, title or ""),
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "year": year,
            "doi": doi,
            "journal": journal,
            "publisher": publisher,
            "document_type": doc_type,
            "url": url,
            "open_access": None,
            "source_database": "WoS",
            "source_id": uid,
            "search_query": search_query,
            "retrieved_at": now_iso(),
        }
    )
    return rec
