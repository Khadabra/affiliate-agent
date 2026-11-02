# DOKUMEN SERAH-TERIMA (HANDOFF)

Dokumen ini memuat status kerja terkini proyek **AI Affiliate Content Factory** untuk memastikan kontinuitas antarsesi asisten AI. Setiap sesi AI wajib memperbarui dokumen ini dan membuat commit Git sebelum mengakhiri sesi.

---

## 1. Tujuan Proyek
Membangun sistem semi-otomatis modular untuk memproduksi, mengaudit kepatuhan, dan melacak konversi konten afiliasi Shopee Indonesia berbasis Python deterministik, penyimpanan lokal SQLite, dan persetujuan manusia.

## 2. Fase Saat Ini
**Phase 1 MVP Selesai Penuh** — Seluruh alur teks, validasi produk, intake CLI, prompting anti-fabrikasi, import draft, human review gate per klaim, dan ekspor paket konten atomik selesai serta terverifikasi 100% (35 unit test lolos). Menuju Phase 2.

## 3. Daftar Selesai & Riwayat Commit
- `1463915`: Inisialisasi Git, `.gitignore`, dan dokumen piagam tata kelola proyek.
- `fa466d6`: Penambahan dokumen bukti sumber resmi Shopee dan koreksi satuan waktu log uji.
- `b6f0aa7`: Kontrak Pydantic (M1), database SQLite, modul deterministik M2 (intake, compliance, claim checker, orchestrator), slot modul video stub, dan studi kelayakan animasi 3D (V0).
- `15d1078`: Perbaikan bukti sumber harfiah (01-05), verifikasi kutipan asli, dan pemisahan klaim HAKI vs AI vs disclosure.
- `28314f6`: Pemangkasan netral AGENTS.md, pembuatan docs/HANDOFF.md, dan generator tools/make_context_pack.py.
- `Phase 1 MVP (Fondasi CLI & Prompting)`: Modul CLI `python -m affiliate_factory.cli` (`intake`, `prompt`, `import-draft`, `inspect`), validasi non-negatif & URL scheme di `Product`, generator prompt anti-fabrikasi di `prompting.py`, parser output AI terstruktur dengan invariant klaim `UNVERIFIED`.
- `Phase 1 MVP (Review Gate & Exporter)`: Human review gate di `review.py` (`review show`, `review claim`, `review approve`, `review reject`), migrasi transparan composite key `compliance_reports`, dan eksportir paket konten atomik di `exporter.py` (`export`) dengan sanitasi path traversal dan manifest SHA-256. Total 35 test case lolos.

## 4. Keputusan Terkunci
1. **Runtime:** Python 3.12 pada `.venv` lokal menggunakan `uv`.
2. **Kontrak Data:** Pydantic v2 dengan validasi skema ketat (`extra="forbid"`).
3. **Penyimpanan:** SQLite lokal dengan konstrain `UNIQUE` pencegah duplikasi, composite primary key `(draft_id, prompt_version)` pada compliance reports, dan tabel `events` append-only.
4. **Arsitektur:** Modul Python deterministik sekuensial tanpa framework multi-agent berat.
5. **Media:** Modul video dan audio TTS ditunda (`DEFERRED`); baseline render video ditetapkan pada FFmpeg `libx264` (CPU).
6. **Persetujuan Manusia & Ekspor:** Persetujuan hanya dapat dilakukan dari `waiting_approval` jika seluruh klaim telah berstatus `VERIFIED` oleh manusia. Ekspor hanya diizinkan untuk draf `approved`.

## 5. Hal Terbuka & Belum Terverifikasi (`NOT_VERIFIED`)
1. Kredensial Shopee Affiliate Open API (`AppId` dan `Secret`) pengguna belum tersedia; metode signature hanya bisa dipastikan dengan akun nyata.
2. Aturan harfiah kewajiban disclosure hubungan afiliasi berstatus `NOT_FOUND` pada dokumen Shopee yang diperiksa (dijalankan berbasis etika periklanan umum).
3. Provider LLM runtime untuk penulisan naskah lokal belum ditentukan oleh pengguna (saat ini menggunakan adapter `ManualPaste` hemat biaya Rp0).

## 6. Tugas Berikutnya (Hanya Satu)
> **Membangun antarmuka CLI pencatatan metrik performa manual (`PerformanceRecord`) dan evaluasi konversi per draf konten yang telah diposting.**

## 7. Larangan Keras
- Dilarang scraping antarmuka web Shopee atau membypass mekanisme proteksi bot.
- Dilarang auto-posting tanpa persetujuan manusia (`APPROVE`).
- Dilarang menyimpan secret atau API key di dalam repositori atau log.
- Dilarang menambah dependensi baru di luar `pydantic` dan library standar Python tanpa keputusan pengguna.

## 8. Cara Menjalankan Tes
Eksekusi dari root direktori proyek di Windows PowerShell:
```powershell
$env:PYTHONPATH="src;."; & ".\.venv\Scripts\python.exe" -m unittest discover -s tests -p "test_*.py" -v
```
