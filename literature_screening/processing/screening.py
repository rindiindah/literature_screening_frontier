"""
processing/screening.py
=========================
Logika screening Include/Exclude (Bagian 13-15).

Prinsip:
- Sistem hanya MEMBANTU (menyiapkan sheet, opsional rekomendasi AI).
  Keputusan akhir selalu di tangan peneliti.
- Keputusan hanya `Include` / `Exclude` — TIDAK ADA `Maybe`.
- Record IEEE yang sudah punya `decision` final TIDAK diminta screening
  ulang; ditandai `decision_source = IEEE_manual` dan dipertahankan.
- AI-assisted screening (opsional, Bagian 15): hanya memberi rekomendasi/
  bukti pendukung (human_decision, ai_suggestion, ai_reason disimpan
  terpisah). Diimplementasikan sebagai fungsi heuristik keyword-based
  ringan (tanpa memerlukan API LLM eksternal) agar tetap berjalan penuh
  secara offline; bisa diganti/dilengkapi dengan pemanggilan LLM nyata.
"""

from __future__ import annotations

from typing import Any, Optional

from config import settings

AIR_QUALITY_TERMS = ["air quality", "air pollution", "pm2.5", "pm10", "particulate matter", "aqi"]
FORECAST_TERMS = ["forecast", "predict", "estimation", "estimating", "modeling", "modelling"]
MULTIMODAL_TERMS = ["multimodal", "multi-modal", "data fusion", "multisource", "multi-source", "multi source"]


def _contains_any(text: Optional[str], terms: list[str]) -> bool:
    if not text:
        return False
    low = text.lower()
    return any(term in low for term in terms)


def ai_assisted_screening(record: dict[str, Any]) -> dict[str, Any]:
    """Heuristik ringan berbasis keyword pada title+abstract untuk
    memberi REKOMENDASI (bukan keputusan). Bagian 15.

    Return dict: {air_quality, multimodal, forecasting, ai_suggestion, ai_reason}
    """
    text = f"{record.get('title') or ''} {record.get('abstract') or ''}"

    air_quality = _contains_any(text, AIR_QUALITY_TERMS)
    forecasting = _contains_any(text, FORECAST_TERMS)
    multimodal = _contains_any(text, MULTIMODAL_TERMS)

    year = record.get("year")
    year_ok = year is not None and settings.START_YEAR <= int(year) <= settings.END_YEAR

    suggestion = "Include" if (air_quality and forecasting and multimodal and year_ok) else "Exclude"
    reason_parts = [
        f"air_quality={'YES' if air_quality else 'NO'}",
        f"multimodal/data_fusion={'YES' if multimodal else 'NO'}",
        f"forecasting/prediction={'YES' if forecasting else 'NO'}",
        f"year_in_range={'YES' if year_ok else 'NO/UNKNOWN'}",
    ]

    return {
        "ai_air_quality": air_quality,
        "ai_multimodal": multimodal,
        "ai_forecasting": forecasting,
        "ai_suggestion": suggestion,
        "ai_reason": "; ".join(reason_parts),
    }


def prepare_screening_dataset(
    records: list[dict[str, Any]], use_ai_assist: bool = True
) -> list[dict[str, Any]]:
    """Siapkan dataset screening: record IEEE dengan decision final ditandai
    `decision_source=IEEE_manual` dan tidak diminta screening ulang; record
    lain diberi kolom kosong `decision`/`exclusion_reason`/`notes` (+ opsional
    rekomendasi AI) untuk diisi peneliti secara manual di spreadsheet.
    """
    prepared: list[dict[str, Any]] = []
    for rec in records:
        rec = dict(rec)

        already_decided = rec.get("decision") in ("Include", "Exclude")
        if already_decided:
            rec.setdefault("decision_source", "IEEE_manual" if "IEEE" in (rec.get("source_database") or "") else "prior_manual")
            rec.setdefault("exclusion_reason", rec.get("exclusion_reason"))
            rec.setdefault("notes", rec.get("notes"))
        else:
            rec["decision"] = ""  # kosong -> diisi peneliti di spreadsheet
            rec.setdefault("exclusion_reason", "")
            rec.setdefault("notes", "")
            rec["decision_source"] = "pending_manual_screening"

            if use_ai_assist:
                ai_result = ai_assisted_screening(rec)
                rec["human_decision"] = ""  # sinonim decision, disediakan utk transparansi Bagian 15
                rec.update(ai_result)

        prepared.append(rec)

    return prepared


def validate_decisions(records: list[dict[str, Any]]) -> list[str]:
    """Validasi setelah peneliti mengisi kolom decision di spreadsheet:
    - decision harus salah satu dari DECISION_VALUES atau kosong.
    - Bila decision == Exclude, exclusion_reason wajib diisi.
    Return list pesan warning (tidak menghentikan proses, hanya informasi).
    """
    warnings: list[str] = []
    for rec in records:
        decision = (rec.get("decision") or "").strip()
        if not decision:
            continue
        if decision not in settings.DECISION_VALUES:
            warnings.append(
                f"[Validasi] record_id={rec.get('record_id')}: nilai decision "
                f"'{decision}' tidak valid (harus Include/Exclude, tanpa Maybe)."
            )
        if decision == "Exclude" and not (rec.get("exclusion_reason") or "").strip():
            warnings.append(
                f"[Validasi] record_id={rec.get('record_id')}: decision=Exclude "
                f"tapi exclusion_reason kosong."
            )
    return warnings
