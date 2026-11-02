# ARCHITECTURE DECISION RECORDS (ADR)

Dokumen ini mencatat keputusan arsitektur yang diusulkan untuk **AI Affiliate Content Factory**, termasuk latar belakang, konsekuensi, alternatif, dan status terkininya.

> **Status Keputusan:**
> Seluruh ADR berstatus `PROPOSED` hingga disetujui secara formal oleh pengguna. Tidak ada klaim keputusan final tanpa persetujuan tertulis.

---

## ADR-001: Pengelolaan Runtime Python & Virtual Environment via `uv`

- **Status:** `PROPOSED` (Telah diuji pada Phase 0B)
- **Tanggal:** 2026-11-02
- **Konteks:** Sistem host Windows 11 memiliki Python 3.15.0 sebagai interpreter sistem global. Pustaka komputasi AI dan data science pada umumnya belum memiliki prebuilt wheel stabil untuk Python 3.15. Sementara itu, `uv 0.13.5` terpasang di host dan memiliki akses ke `cpython-3.12.15`.
- **Keputusan:** Menggunakan `uv` untuk membuat dan mengelola virtual environment proyek dengan target **Python 3.12** (`uv venv .venv --python 3.12`).
- **Bukti Uji:** Environment `.venv` berhasil dibuat pada 2026-11-02 menggunakan CPython 3.12.15 dengan `exit code 0`.
- **Konsekuensi:**
  - *Positif:* Menjamin kompatibilitas wheel paket dan isolasi penuh dari lingkungan global.
  - *Negatif:* Eksekusi script wajib dilakukan melalui interpreter `.venv\Scripts\python.exe` atau `uv run`.
- **Alternatif Dipertimbangkan:** Menggunakan Python 3.15 sistem (Ditolak: risiko ketidakcocokan dependensi biner C/C++).

---

## ADR-002: Standarisasi Kontrak Data Menggunakan Pydantic

- **Status:** `PROPOSED` (Telah diuji pada Phase 0B)
- **Tanggal:** 2026-11-02
- **Konteks:** Sistem membutuhkan validasi data yang ketat pada setiap batas modul (input produk manual, draft naskah, review manusia, dan pencatatan hasil).
- **Keputusan:** Menggunakan **Pydantic v2** sebagai standar tunggal pemodelan skema data.
- **Bukti Uji:** `pydantic 2.14.2` berhasil dipasang di `.venv` dan lolos smoke test model data dengan `exit code 0`.
- **Konsekuensi:**
  - *Positif:* Menghindari kesalahan parsing data runtime, mempermudah ekspor JSON, dan type-safe.
  - *Negatif:* Menambah dependensi `pydantic` dan `pydantic-core`.
- **Alternatif Dipertimbangkan:** Python `dataclasses` bawaan (Ditolak: validasi tipe saat runtime terbatas dan tanpa validasi string/format otomatis).

---

## ADR-003: Mesin Pemrosesan Video & Kebijakan Encoder FFmpeg

- **Status:** `PROPOSED` (Koreksi Bukti Empiris Phase 0B)
- **Tanggal:** 2026-11-02
- **Konteks:** Pembuatan video membutuhkan konversi dan penggabungan aset media ke rasio vertikal 9:16 (1080x1920).
- **Keputusan:** Menggunakan binary **FFmpeg** native via `subprocess` dengan encoder baseline **`libx264` (CPU)**.
- **Koreksi & Bukti Uji:**
  - Uji CPU (`libx264`): Berhasil merender video sintetis 5 detik 1080x1920 dalam 1,64 detik (`exit code 0`).
  - Uji GPU (`h264_nvenc`): **Gagal** dengan `exit code -40`. Build FFmpeg 9.0.2 membutuhkan NVENC API 13.1 (driver NVIDIA 610.00+), sedangkan driver host saat ini adalah 581.32 (NVENC API 13.0).
  - *Aturan:* Sesuai protokol, tidak ada pengubahan driver yang dipaksakan. Sistem menetapkan `libx264` sebagai encoder default yang terbukti andal.
- **Konsekuensi:**
  - *Positif:* Deterministic, tidak bergantung pada versi driver GPU, dan terbukti cepat untuk video pendek di CPU modern.
  - *Negatif:* Pemrosesan batch video panjang akan menggunakan sumber daya CPU.
- **Alternatif Dipertimbangkan:** MoviePy (Ditolak: lambat dan berisiko memory leak di Windows).

---

## ADR-004: Strategi Orkestrasi Workflow — Sekuensial Sederhana vs LangGraph

- **Status:** `PROPOSED`
- **Tanggal:** 2026-11-02
- **Konteks:** Alur kerja MVP yang direvisi difokuskan pada: input produk manual, pembuatan draft teks, human approval, ekspor paket, dan pencatatan hasil.
- **Keputusan:** Menggunakan **fungsi Python modular sekuensial sederhana** dengan state disimpan ke file/SQLite lokal untuk MVP Phase 1. Evaluasi `LangGraph` ditunda (`DEFERRED`) sampai workflow membutuhkan percabangan multi-agen dinamis atau rollback kompleks.
- **Alasan:**
  1. Menghindari penambahan dependensi `langchain-core` pada tahap awal di mana alur masih linier dan dikendalikan manusia.
  2. Mengurangi kompleksitas debugging di lingkungan Windows lokal.
- **Konsekuensi:**
  - *Positif:* Minimal dependensi, eksekusi transparan, dan mudah dipelihara.
  - *Negatif:* Jika alur kerja di masa depan menjadi sangat bercabang, perlu refactor ke framework state machine.

---

## ADR-005: Kebijakan Akses Data Shopee, Anti-Scraping & Kepatuhan Konten

- **Status:** `PROPOSED` (Dilengkapi Bukti Resmi Shopee Indonesia)
- **Tanggal:** 2026-11-02
- **Konteks:** Perlindungan akun afiliasi, kepatuhan hukum, dan aturan hak cipta platform e-commerce.
- **Keputusan:**
  1. **Metode Akses:** Input produk pada MVP menggunakan **kurasi manual terstruktur**. Dilarang menggunakan web scraper otomatis/headless browser untuk membypass bot detection Shopee.
  2. **Jalur API Resmi:** Jika integrasi otomatis dilakukan di masa depan, wajib menggunakan **Shopee Affiliate Open API** resmi (`https://open-api.affiliate.shopee.co.id/graphql`) menggunakan autentikasi tanda tangan SHA-256 (`AppId` + `Timestamp` + `Payload` + `Secret`), bukan Shopee Open Platform milik seller.
  3. **Kebijakan AI & Hak Cipta Shopee Video:**
     - Shopee Video mewajibkan pelabelan konten AI jika video dihasilkan atau diedit signifikan dengan AI.
     - Dilarang keras mengunduh dan mengunggah ulang video/materi kreator lain (*content theft*) tanpa izin pemilik hak cipta.
- **Konsekuensi:**
  - *Positif:* Akun terhindar dari sanksi pemblokiran, penalti kesehatan akun, atau pelanggaran HAKI.
  - *Negatif:* Diperlukan seleksi manual produk dan aset oleh pengguna pada tahap awal.

---

## ADR-006: Pemisahan Antara Model Antigravity dan Runtime Aplikasi

- **Status:** `PROPOSED`
- **Tanggal:** 2026-11-02
- **Konteks:** Perbedaan antara asisten pengembang (Antigravity IDE) dan aplikasi mandiri yang akan dijalankan oleh pengguna di terminal atau backend.
- **Keputusan:** Runtime aplikasi mengandalkan konfigurasi API LLM mandiri via file `.env` lokal (misalnya API key Google AI Studio, OpenAI, dll). Sesi interaktif Antigravity tidak dianggap sebagai provider token runtime aplikasi.
- **Konsekuensi:**
  - *Positif:* Aplikasi sepenuhnya mandiri dan dapat dijalankan di mana saja tanpa ketergantungan pada IDE Antigravity.
  - *Negatif:* Pengguna perlu menyediakan kredensial API LLM sendiri saat pengujian pembuatan naskah dimulai.

---

## ADR-007: Gerbang Persetujuan Manusia (Human-in-the-Loop)

- **Status:** `PROPOSED`
- **Tanggal:** 2026-11-02
- **Konteks:** Kualitas naskah, akurasi klaim produk, dan kepatuhan terhadap pedoman komunitas media sosial.
- **Keputusan:** Setiap draft naskah dan paket konten **WAJIB** melalui gerbang persetujuan manusia (`APPROVE` / `REVISE` / `REJECT`). Sistem tidak memiliki fitur publikasi otomatis tanpa tindakan manusia.
- **Konsekuensi:**
  - *Positif:* 100% kendali mutu dan keamanan materi konten di tangan pengguna.
  - *Negatif:* Proses produksi tidak sepenuhnya tanpa pengawasan (*unattended*).
