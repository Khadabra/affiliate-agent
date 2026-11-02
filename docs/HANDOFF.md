# DOKUMEN SERAH-TERIMA (HANDOFF)

Dokumen ini memuat status kerja terkini proyek **AI Affiliate Content Factory** untuk memastikan kontinuitas antarsesi asisten AI. Setiap sesi AI wajib memperbarui dokumen ini dan membuat commit Git sebelum mengakhiri sesi.

---

## 1. Tujuan Proyek
Membangun sistem semi-otomatis modular untuk memproduksi, mengaudit kepatuhan, dan melacak konversi konten afiliasi Shopee Indonesia berbasis Python deterministik, penyimpanan lokal SQLite, dan persetujuan manusia.

## 2. Fase Saat Ini
**Phase 1.1 Selesai Penuh** — Audit gerbang penelaahan manusia (review gate) dan isolasi versi draf konten tuntas. Seluruh klaim kini terikat pada versi prompt draf (`prompt_version`), draf yang telah disetujui (`approved`) atau ditolak (`rejected`) tidak dapat diubah klaimnya, eksportir paket konten terlindungi dari path traversal, symlink, dan penimpaan gagal (atomic staging & rollback). Seluruh 44 unit test lolos pengujian tanpa error (`exit code 0`). Menuju Phase 2.

## 3. Daftar Selesai & Riwayat Commit
- `1463915`: Inisialisasi Git, `.gitignore`, dan dokumen piagam tata kelola proyek.
- `fa466d6`: Penambahan dokumen bukti sumber resmi Shopee dan koreksi satuan waktu log uji.
- `b6f0aa7`: Kontrak Pydantic (M1), database SQLite, modul deterministik M2 (intake, compliance, claim checker, orchestrator), slot modul video stub, dan studi kelayakan animasi 3D (V0).
- `15d1078`: Perbaikan bukti sumber harfiah (01-05), verifikasi kutipan asli, dan pemisahan klaim HAKI vs AI vs disclosure.
- `28314f6`: Pemangkasan netral AGENTS.md, pembuatan docs/HANDOFF.md, dan generator tools/make_context_pack.py.
- `05c48bc`: Phase 1 MVP implementasi penuh (intake CLI, prompting, import-draft, inspect, human review gate show/claim/approve/reject, content pack exporter atomik, 35 unit test).
- `Phase 1.1 (Saat Ini)`: Isolasi versi klaim (`prompt_version`), migrasi SQLite aman tanpa fabrikasi data, invariant terminal state draf, fail-closed pada klaim `SOURCED`, proteksi symlink & rollback pada eksportir. Total 44 unit test lolos.

## 4. Keputusan Terkunci
1. **Runtime:** Python 3.12 pada `.venv` lokal menggunakan `uv`.
2. **Kontrak Data:** Pydantic v2 dengan validasi skema ketat (`extra="forbid"`). Model `Claim` memiliki field `prompt_version: str | None = None`.
3. **Penyimpanan:** SQLite lokal dengan konstrain `UNIQUE` pencegah duplikasi, composite primary key `(draft_id, prompt_version)` pada compliance reports, indeks komposit `(draft_id, prompt_version)` pada claims, dan tabel `events` append-only.
4. **Isolasi Versi Klaim:** Klaim dari versi prompt sebelumnya (misal v1.0) tidak boleh memblokir persetujuan versi prompt yang lebih baru (misal v2.0), dan ekspor v2.0 tidak boleh memuat klaim dari v1.0.
5. **Invariant Review Gate:** Klaim pada draf `approved` tidak dapat dimodifikasi; klaim pada draf `rejected` tidak dapat ditelaah (wajib membuat draf versi revisi baru).
6. **Gerbang Ekspor Atomik:** Ekspor ke `output/packs/<draft_id>` menggunakan staging atomik. Jika penimpaan gagal, direktori asli dipulihkan dari cadangan. Symlink dan path traversal dilarang keras.

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
