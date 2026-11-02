# AI AFFILIATE CONTENT FACTORY — OPERATING RULES

## 1. Tujuan Proyek
Sistem ini membangun AI Affiliate Content Factory semi-otomatis untuk memproduksi dan mengevaluasi konten afiliasi Shopee Indonesia berbasis modul Python deterministik. Fokus sistem adalah kegunaan nyata dengan menghasilkan draf naskah terstruktur, memeriksa kepatuhan klaim, dan mencatat performa konversi secara terukur. Seluruh alur kerja menempatkan kontrol keputusan pada manusia sebelum materi dipublikasikan.

## 2. Aturan Keras (Hard Invariants)
1. **Tidak Ada Scraping Shopee:** Dilarang menggunakan bot, spider, scraper headless, atau skrip otomatis pengumpul informasi terhadap antarmuka Shopee.
2. **Tidak Ada Auto-Posting:** Tidak ada konten yang dipublikasikan atau diunggah ke platform luar tanpa persetujuan manusia eksplisit (`APPROVE`).
3. **Tidak Ada Secret:** Dilarang keras menulis API key, token, atau password di source code, dokumen commit, atau log. Gunakan local `.env`.
4. **Tidak Ada Dependensi Baru:** Dilarang menginstal pustaka eksternal baru tanpa persetujuan eksplisit pengguna. Gunakan hanya modul yang disetujui (`pydantic` dan pustaka bawaan Python).

## 3. Definisi Status Bukti
- `VERIFIED`: Fakta terbukti dari dokumen resmi yang dibuka langsung dengan kutipan persis harfiah (bahasa asli halaman).
- `DOCUMENTATION_ONLY`: Tertulis pada dokumentasi integrasi/portal pihak ketiga, namun belum diverifikasi pada dokumen publik resmi atau kredensial aktif.
- `NOT_VERIFIED`: Asumsi, klaim tanpa kutipan persis, atau informasi yang tidak ditemukan pada dokumen resmi.
- `TESTED`: Telah diuji langsung pada lingkungan lokal dengan catatan perintah, exit code, dan output aktual.

## 4. Definisi "Selesai" (Definition of Done)
Suatu tugas atau modul hanya dapat dinyatakan selesai jika:
1. Seluruh unit test terkait lolos pengujian tanpa error (`exit code 0`).
2. Perintah pengujian, exit code, dan output aktual tercatat di `docs/VERIFICATION_LOG.md`.
3. Seluruh perubahan berkas telah di-commit ke Git dengan pesan deskriptif.

## 5. Protokol Awal dan Akhir Sesi
- **Awal Sesi:** Baca `docs/HANDOFF.md`, periksa status Git (`git status`), jalankan seluruh unit test untuk memastikan titik awal bersih, dan verifikasi kondisi aktual sebelum mengubah berkas.
- **Akhir Sesi:** Jalankan seluruh unit test, perbarui `docs/VERIFICATION_LOG.md`, perbarui `docs/HANDOFF.md` (hanya satu tugas berikutnya), lalu lakukan commit ke Git sebelum berhenti.
