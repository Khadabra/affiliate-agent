# DOKUMEN SERAH-TERIMA (HANDOFF)

Dokumen ini memuat status kerja terkini proyek **AI Affiliate Content Factory** untuk memastikan kontinuitas antarsesi asisten AI. Setiap sesi AI wajib memperbarui dokumen ini dan membuat commit Git sebelum mengakhiri sesi.

---

## 1. Tujuan Proyek
Membangun sistem semi-otomatis modular untuk memproduksi, mengaudit kepatuhan, dan melacak konversi konten afiliasi Shopee Indonesia berbasis Python deterministik, penyimpanan lokal SQLite, dan persetujuan manusia.

## 2. Fase Saat Ini
**Phase 2 Selesai Penuh** — Modul pencatatan metrik performa affiliate (`PerformanceRecord`), analitik konversi (CTR, Click-to-Order, Komisi per Pesanan), dan subperintah CLI (`performance record`, `performance show`, `performance summary`) telah diimplementasikan penuh. Sistem mempertahankan riwayat snapshot tanpa menimpa data historis, mencegah penghitungan ganda atas counter kumulatif, memvalidasi anomali tanpa menolak data nyata, dan mempertahankan nilai tidak diketahui (`None`) tanpa disulap menjadi nol. Seluruh 55 unit test lolos pengujian tanpa error (`exit code 0`).

## 3. Daftar Selesai & Riwayat Commit
- `1463915`: Inisialisasi Git, `.gitignore`, dan dokumen piagam tata kelola proyek.
- `fa466d6`: Penambahan dokumen bukti sumber resmi Shopee dan koreksi satuan waktu log uji.
- `b6f0aa7`: Kontrak Pydantic (M1), database SQLite, modul deterministik M2 (intake, compliance, claim checker, orchestrator), slot modul video stub, dan studi kelayakan animasi 3D (V0).
- `15d1078`: Perbaikan bukti sumber harfiah (01-05), verifikasi kutipan asli, dan pemisahan klaim HAKI vs AI vs disclosure.
- `28314f6`: Pemangkasan netral AGENTS.md, pembuatan docs/HANDOFF.md, dan generator tools/make_context_pack.py.
- `05c48bc`: Phase 1 MVP implementasi penuh (intake CLI, prompting, import-draft, inspect, human review gate show/claim/approve/reject, content pack exporter atomik, 35 unit test).
- `5186c01`: Phase 1.1 audit review gate dan isolasi klaim per versi draf (`prompt_version`), migrasi SQLite aman tanpa fabrikasi data, invariant terminal state draf, fail-closed pada klaim `SOURCED`, proteksi symlink & rollback pada eksportir (44 unit test).
- `Phase 2 (Saat Ini)`: Performance Tracking & Conversion Analytics via CLI (`performance record`, `performance show`, `performance summary`), validasi metrik non-negatif, preservasi `None`, deteksi anomali diagnostik, strategi agregasi snapshot non-double-counting, dan audit event (55 unit test).

## 4. Keputusan Terkunci
1. **Runtime:** Python 3.12 pada `.venv` lokal menggunakan `uv`.
2. **Kontrak Data:** Pydantic v2 dengan validasi skema ketat (`extra="forbid"`). Model `PerformanceRecord` memvalidasi angka non-negatif (`>= 0`) dan memvalidasi `content_id` serta `platform` non-kosong.
3. **Penyimpanan Snapshot:** Setiap observasi performa disimpan sebagai snapshot tersendiri dengan ID unik (`perf_<content_id>_<platform>_<timestamp>_<uuid>`). Pengeditan snapshot lama harus eksplisit via ID. Riwayat snapshot lama tidak pernah tertimpa saat observasi baru masuk.
4. **Strategi Agregasi Non-Double-Counting:** Karena metrik pada platform media sosial/afiliasi berformat kumulatif, agregasi performa ringkasan mengambil **snapshot terbaru** untuk setiap kombinasi unik `(content_id, platform)`, lalu menjumlahkan snapshot terbaru tersebut. Sistem dilarang menjumlahkan seluruh snapshot dari konten yang sama.
5. **Preservasi Nilai Tidak Diketahui (`None`):** Nilai metrik yang tidak diukur/tidak diketahui tetap tersimpan dan ditampilkan sebagai `None` / `N/A`, tidak pernah disulap menjadi `0`.
6. **Rasio Konversi yang Didukung Data:** CTR dihitung dari `(clicks / views) * 100` dan Click-to-Order dihitung dari `(orders / clicks) * 100`. Jika penyebut adalah 0 atau None, rasio tidak dihitung (`None` / `N/A`).
7. **Pemisahan Status Posting & Rekam Metrik:** Pencatatan performa tidak mengubah status draf menjadi `posted` secara sepihak untuk mencegah fabrikasi status publikasi.

## 5. Hal Terbuka & Belum Terverifikasi (`NOT_VERIFIED`)
1. Kredensial Shopee Affiliate Open API (`AppId` dan `Secret`) pengguna belum tersedia; seluruh data performa saat ini bersumber manual (`data_source="manual"`).
2. Mekanisme integrasi feed otomatis dari dashboard Shopee belum tersedia tanpa API resmi atau persetujuan pengguna.
3. Korelasi antara angle naskah promosi dan tingkat konversi masih membutuhkan data empiris yang lebih besar untuk menghasilkan kesimpulan statistik valid.

## 6. Tugas Berikutnya (Hanya Satu)
> **Membangun modul pemeringkatan dan rekomendasi angle naskah (`AngleRanker` / `CopywritingAdvisor`) berdasarkan perbandingan CTR dan Click-to-Order dari metrik performa historis.**

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
