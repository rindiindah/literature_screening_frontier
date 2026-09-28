# Semi-Automated Literature Screening — Multi-Database

Sistem bantu **retrieval → normalisasi → deduplikasi → filtering →
screening semi-manual (Include/Exclude) → ekspor `included.bib` +
statistik + log reproducibility**, untuk revisi mini-review Frontiers
*"Multimodal Intelligence for Air Quality Modeling"*.

**Lima database final:** IEEE Xplore (import-only), OpenAlex (API),
Crossref (API), Scopus (API bila kredensial ada / import manual
sementara), Web of Science (API bila kredensial ada / import manual
sementara). Sistem **hanya membantu** — keputusan akademik akhir tetap
di tangan peneliti.

---

## 1. Instalasi (Windows)

1. Install Python 3.10+ dari [python.org](https://www.python.org/downloads/)
   (centang "Add Python to PATH" saat instalasi).
2. Buka **Command Prompt** atau **PowerShell**, lalu masuk ke folder proyek:

   ```powershell
   cd path\ke\literature_screening
   ```

3. (Disarankan) Buat virtual environment:

   ```powershell
   python -m venv venv
   venv\Scripts\activate
   ```

4. Install dependency:

   ```powershell
   pip install -r requirements.txt
   ```

5. Salin `.env.example` menjadi `.env`, lalu isi email/API key Anda:

   ```powershell
   copy .env.example .env
   notepad .env
   ```

   Minimal isi:
   - `OPENALEX_MAILTO` = email Anda (wajib untuk polite pool; `OPENALEX_API_KEY` opsional).
   - `CROSSREF_MAILTO` = email Anda (wajib).
   - `SCOPUS_API_KEY`, `SCOPUS_INSTTOKEN` = kosongkan bila belum ada izin.
   - `WOS_API_KEY` = kosongkan bila belum ada izin.

   **Jangan pernah commit file `.env` (isi asli) ke Git.**

---

## 2. Menjalankan Pipeline

Jalankan tiap tahap dari folder `literature_screening/`.

### Tahap 1 — Ambil data dari OpenAlex & Crossref (dan Scopus/WOS bila ada key)

```powershell
python main.py fetch
```

- Hanya sumber dengan kredensial tersedia yang benar-benar dipanggil;
  Scopus/WOS otomatis di-skip dengan pesan jelas bila key kosong.
- Hasil mentah disimpan di `data/raw/<source>_<tanggal>.json` (raw
  cache harian — rerun di hari yang sama tidak memanggil API ulang,
  kecuali pakai `--force-refresh`).
- Hasil ternormalisasi digabung ke `data/processed/combined_raw_records.json`.

Opsi:
```powershell
python main.py fetch --sources openalex crossref
python main.py fetch --start-year 2024 --end-year 2026 --limit 500
python main.py fetch --force-refresh
```

### Tahap 2 — Impor hasil IEEE final (sudah ada keputusan Include/Exclude)

```powershell
python main.py import-ieee --file data\raw\ieee_final_import.bib
```

Mendukung `.bib`, `.csv`, `.xlsx`, `.ris`. Kolom `decision` (dan
opsional `exclusion_reason`, `notes`) pada file akan **dipertahankan**,
bukan diminta screening ulang.

### Tahap 3 — (Opsional, interim) Impor ekspor manual Scopus/WoS

Selama kredensial Scopus/WOS API belum ada, ekspor hasil pencarian dari
portal masing-masing (`.bib`/`.ris`/`.csv`) lalu:

```powershell
python main.py import-manual --file data\raw\scopus_export.csv --source Scopus
python main.py import-manual --file data\raw\wos_export.ris --source WoS
```

### Tahap 4 — Filtering + gabung IEEE + Deduplikasi

```powershell
python main.py process
```

- Filter tahun (`START_YEAR`–`END_YEAR`) & document type (konfigurabel
  di `config/settings.py`). Record IEEE (sudah punya decision) tidak
  disaring ulang.
- Deduplikasi lintas sumber: DOI → judul ternormalisasi → fuzzy title
  (dengan pencatatan). Hasil disimpan di `data/processed/filtered_records.json`.
- Pasangan fuzzy confidence-sedang (perlu tinjauan manual) dicatat di
  `logs/fuzzy_review_log.json`.

### Tahap 5 — Siapkan lembar screening

```powershell
python main.py prepare-screening
```

Menghasilkan:
- `data/output/screening_results.xlsx` (dengan dropdown Include/Exclude
  dan daftar exclusion reason) — **buka file ini di Excel dan isi kolom
  `decision` (dan `exclusion_reason` bila Exclude) untuk tiap paper.**
- `data/output/screening_results.csv` (alternatif, tanpa dropdown).

Kolom `ai_suggestion` / `ai_reason` (bila AI-assist aktif) hanya
rekomendasi pendukung — keputusan akhir tetap kolom `decision` yang Anda isi.

### Tahap 6 — Finalisasi: `included.bib` + statistik

Setelah selesai mengisi kolom `decision` di Excel, simpan filenya, lalu:

```powershell
python main.py finalize --file data\output\screening_results.xlsx
```

Menghasilkan:
- `data/output/included.bib` — hanya paper `decision = Include`.
- `data/output/screening_results.csv` — versi final dengan semua keputusan.
- `data/output/statistics.json` — statistik per tahap (Bagian 18 spesifikasi).
- `logs/search_log.json` — log reproducibility tiap run (query aktual, tanggal, jumlah).

### Jalankan semua tahap otomatis sekaligus (fetch → process → prepare-screening)

```powershell
python main.py run-all
```

(Import IEEE/manual dan `finalize` tetap dijalankan terpisah karena
membutuhkan input dari peneliti.)

---

## 3. Struktur Folder

```text
literature_screening/
├── config/settings.py          # tahun, master query, kriteria, threshold dedup, path
├── connectors/                 # openalex.py, crossref.py, scopus.py, wos.py
├── importers/                  # bibtex_importer.py, ris_importer.py, csv_importer.py
├── processing/                 # normalize, filtering, deduplicate, screening, statistics
├── export/                     # csv_export, xlsx_export, bibtex_export
├── data/{raw,processed,output}/
├── logs/                       # search_log.json, fuzzy_review_log.json
├── main.py
├── requirements.txt
└── .env.example
```

---

## 4. Catatan Teknis Penting

- **OpenAlex**: abstract direkonstruksi dari `abstract_inverted_index`.
  Bila null di sumber → `abstract = None` (tidak dikarang).
- **Crossref**: abstract sering kosong (hanya ada bila publisher
  menyetor JATS XML); bila ada, tag XML dibersihkan otomatis.
- **Scopus**: Search API tidak menyertakan abstract penuh → diambil
  lewat Abstract Retrieval API tahap kedua, hanya untuk record yang
  lolos filter (hemat kuota).
- **Web of Science**: connector memakai **Starter API** (didokumentasikan
  di kode) — abstract penuh TIDAK tersedia di tier ini (perlu Expanded API).
- **IEEE**: import-only, tidak ada connector API. Keputusan final
  dipertahankan, tidak di-screen ulang.
- Kredensial kosong (Scopus/WOS) → connector cetak pesan jelas & skip
  aman; pipeline tetap lanjut ke sumber lain.
- Semua threshold, kriteria, rentang tahun, dan tipe dokumen yang
  diizinkan **dapat diedit** di `config/settings.py`.

---

## 5. Statistik yang Dihasilkan (`data/output/statistics.json`)

```text
IEEE (imported, final):   XXX   (Include: XX / Exclude: XX)
OpenAlex retrieved:       XXX
Crossref retrieved:       XXX
Scopus retrieved:         XXX   (atau: skipped — no credentials)
WoS retrieved:            XXX   (atau: skipped — no credentials)

Total retrieved:          XXX
After year/type filter:   XXX
Duplicates removed:       XXX
Unique records screened:  XXX
Include:                  XXX
Exclude:                  XXX
```

Statistik ini bisa langsung dipakai untuk PRISMA-style flow diagram
pada manuskrip revisi.
