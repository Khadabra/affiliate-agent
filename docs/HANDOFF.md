# DOKUMEN SERAH-TERIMA (HANDOFF)

Dokumen ini memuat status kerja terkini proyek **AI Affiliate Content Factory** untuk memastikan kontinuitas antarsesi asisten AI. Setiap sesi AI wajib memperbarui dokumen ini dan membuat commit Git sebelum mengakhiri sesi.

---

## 1. Tujuan Proyek
Membangun sistem semi-otomatis modular untuk memproduksi, mengaudit kepatuhan, dan melacak konversi konten afiliasi Shopee Indonesia berbasis Python deterministik, penyimpanan lokal SQLite, dan persetujuan manusia.

## 2. Fase Saat Ini
**Phase 0 (Tahap Fondasi & H0 Selesai)** — Menuju implementasi Phase 1 MVP (Input Produk & Pembuatan Naskah).

## 3. Daftar Selesai & Riwayat Commit
- `1463915`: Inisialisasi Git, `.gitignore`, dan dokumen piagam tata kelola proyek.
- `fa466d6`: Penambahan dokumen bukti sumber resmi Shopee dan koreksi satuan waktu log uji.
- `b6f0aa7`: Kontrak Pydantic (M1), database SQLite, modul deterministik M2 (intake, compliance, claim checker, orchestrator), slot modul video stub, dan studi kelayakan animasi 3D (V0).
- `15d1078`: Perbaikan bukti sumber harfiah (01-05), verifikasi kutipan asli, dan pemisahan klaim HAKI vs AI vs disclosure.
- `HEAD` (H0): Pemangkasan netral AGENTS.md, pembuatan docs/HANDOFF.md, dan generator tools/make_context_pack.py.

## 4. Keputusan Terkunci
1. **Runtime:** Python 3.12 pada `.venv` lokal menggunakan `uv`.
2. **Kontrak Data:** Pydantic v2 dengan validasi skema ketat (`extra="forbid"`).
3. **Penyimpanan:** SQLite lokal dengan konstrain `UNIQUE` pencegah duplikasi dan tabel `events` append-only.
4. **Arsitektur:** Modul Python deterministik sekuensial tanpa framework multi-agent berat.
5. **Media:** Modul video dan audio TTS ditunda (`DEFERRED`); baseline render video ditetapkan pada FFmpeg `libx264` (CPU).

## 5. Hal Terbuka & Belum Terverifikasi (`NOT_VERIFIED`)
1. Kredensial Shopee Affiliate Open API (`AppId` dan `Secret`) pengguna belum tersedia; metode signature hanya bisa dipastikan dengan akun nyata.
2. Aturan harfiah kewajiban disclosure hubungan afiliasi berstatus `NOT_FOUND` pada dokumen Shopee yang diperiksa (dijalankan berbasis etika periklanan umum).
3. Provider LLM runtime untuk penulisan naskah lokal belum ditentukan oleh pengguna.

## 6. Tugas Berikutnya (Hanya Satu)
> **Membangun antarmuka input produk manual (CLI/JSON) dan generator draft naskah berbasis prompt terstruktur untuk Phase 1.**

## 7. Larangan Keras
- Dilarang scraping antarmuka web Shopee atau membypass mekanisme proteksi bot.
- Dilarang auto-posting tanpa persetujuan manusia (`APPROVE`).
- Dilarang menyimpan secret atau API key di dalam repositori atau log.
- Dilarang menambah dependensi baru di luar `pydantic` dan library standar Python tanpa keputusan pengguna.

## 8. Cara Menjalankan Tes
Eksekusi dari root direktori proyek di Windows PowerShell:
```powershell
$env:PYTHONPATH="src"; & ".\.venv\Scripts\python.exe" -m unittest discover -s tests -p "test_*.py" -v
```
