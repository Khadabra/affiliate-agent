# DOKUMEN SERAH-TERIMA (HANDOFF)

Dokumen ini memuat status kerja terkini proyek **AI Affiliate Content Factory** untuk memastikan kontinuitas antarsesi asisten AI. Setiap sesi AI wajib memperbarui dokumen ini dan membuat commit Git sebelum mengakhiri sesi.

---

## 1. Tujuan Proyek
Membangun sistem semi-otomatis modular untuk memproduksi, mengaudit kepatuhan, dan melacak konversi konten afiliasi Shopee Indonesia berbasis Python deterministik, penyimpanan lokal SQLite, dan persetujuan manusia.

## 2. Fase Saat Ini
**Phase 2.1.1 Selesai Penuh** — Ketertelusuran dan auditabilitas koreksi performa telah diperkuat secara atomik:
1. **Transaksi Atomik Koreksi & Audit:** Pembaruan snapshot dan penyisipan catatan audit dieksekusi dalam satu transaksi SQLite tunggal (`with conn:` pada `Database.correct_performance_record`). Kegagalan audit event secara otomatis membatalkan (*rollback*) seluruh perubahan snapshot.
2. **Representasi Lengkap Sebelum & Sesudah:** Audit event menyimpan status lengkap sebelum koreksi (`before`) dan sesudah koreksi (`after`) menggunakan kontrak `PerformanceSnapshotState` dan `PerformanceCorrectionPayload`, memungkinkan audit penuh dan pemulihan data historis.
3. **Ketertelusuran Sekuensial:** Koreksi berulang tersimpan secara kronologis dan dapat diaudit secara linier melalui `db.list_correction_events()`.
4. **Validasi Tanpa Efek Samping:** Snapshot ID yang tidak ditemukan atau input tidak valid ditolak tanpa mengubah data dan tanpa meninggalkan event sukses palsu.
Seluruh 71 unit test lolos pengujian tanpa error (`exit code 0`).

## 3. Daftar Selesai & Riwayat Commit
- `1463915`: Inisialisasi Git, `.gitignore`, dan dokumen piagam tata kelola proyek.
- `fa466d6`: Penambahan dokumen bukti sumber resmi Shopee dan koreksi satuan waktu log uji.
- `b6f0aa7`: Kontrak Pydantic (M1), database SQLite, modul deterministik M2 (intake, compliance, claim checker, orchestrator), slot modul video stub, dan studi kelayakan animasi 3D (V0).
- `15d1078`: Perbaikan bukti sumber harfiah (01-05), verifikasi kutipan asli, dan pemisahan klaim HAKI vs AI vs disclosure.
- `28314f6`: Pemangkasan netral AGENTS.md, pembuatan docs/HANDOFF.md, dan generator tools/make_context_pack.py.
- `05c48bc`: Phase 1 MVP implementasi penuh (intake CLI, prompting, import-draft, inspect, human review gate show/claim/approve/reject, content pack exporter atomik, 35 unit test).
- `5186c01`: Phase 1.1 audit review gate dan isolasi klaim per versi draf (`prompt_version`), migrasi SQLite aman tanpa fabrikasi data, invariant terminal state draf, fail-closed pada klaim `SOURCED`, proteksi symlink & rollback pada eksportir (44 unit test).
- `5840ce1`: Phase 2 — Performance Tracking & Conversion Analytics via CLI (`performance record`, `performance show`, `performance summary`), validasi metrik non-negatif, preservasi `None`, deteksi anomali diagnostik, strategi agregasi snapshot non-double-counting, dan audit event (55 unit test).
- `67799ad`: Phase 2.1 — Data Integrity & Analytics Hardening: immutabilitas snapshot historis, subperintah `performance correct`, rasio konversi agregat berbasis kohort lengkap, normalisasi UTC, determinisme tie-breaking, penolakan `NaN`/`Inf`, dan pemberitahuan parsial CLI (65 unit test).
- `Phase 2.1.1 (Saat Ini)`: Performance Correction Auditability: koreksi snapshot atomik transaksional dengan audit payload sebelum/sesudah lengkap, proteksi rollback saat audit gagal, dan penelusuran sekuensial (71 unit test).

## 4. Keputusan Terkunci
1. **Runtime:** Python 3.12 pada `.venv` lokal menggunakan `uv`.
2. **Kontrak Data:** Pydantic v2 dengan validasi skema ketat (`extra="forbid"`). Model `PerformanceRecord` memvalidasi angka non-negatif (`>= 0`), menolak non-finite (`NaN`/`Inf`), menormalisasi `observed_at` ke UTC, dan memvalidasi `content_id` serta `platform` non-kosong.
3. **Penyimpanan Snapshot & Immutabilitas:** Setiap observasi performa disimpan sebagai snapshot tersendiri dengan ID unik (`perf_<content_id>_<platform>_<timestamp>_<uuid>`). Duplikasi ID ditolak secara default untuk mencegah penimpaan tidak sengaja.
4. **Koreksi Snapshot Atomik & Audit Sebelum/Sesudah:** Koreksi snapshot performa diwajibkan melalui `db.correct_performance_record` yang mengeksekusi pembaruan tabel `performance_records` dan penyisipan ke tabel `events` dalam satu transaksi SQLite atomik (`with conn:`). Audit event menyimpan seluruh representasi nilai `before` dan `after` (model `PerformanceSnapshotState` dan `PerformanceCorrectionPayload`). Jika pencatatan audit gagal, pembaruan snapshot secara otomatis di-rollback.
5. **Strategi Agregasi Non-Double-Counting:** Agregasi ringkasan performa mengambil **snapshot terbaru** untuk setiap kombinasi unik `(content_id, platform)` dalam jendela filter, diurutkan secara deterministik dengan `(observed_at ASC, id ASC)`. Sistem dilarang menjumlahkan seluruh snapshot dari konten yang sama.
6. **Preservasi Nilai Tidak Diketahui (`None`):** Nilai metrik yang tidak diukur/tidak diketahui tetap tersimpan dan ditampilkan sebagai `None` / `N/A`, tidak pernah disulap menjadi `0`. Total metrik berstatus `[PARSIAL]` jika sebagian konten tidak mencatat metrik tersebut.
7. **Rasio Konversi Berbasis Kohort:** CTR agregat dihitung hanya pada item dengan views dan clicks lengkap; Click-to-Order agregat dihitung hanya pada item dengan clicks dan orders lengkap. Jika penyebut nol atau kohort kosong, rasio menghasilkan `None` (`N/A`).
8. **Pemisahan Status Posting & Rekam Metrik:** Pencatatan performa tidak mengubah status draf menjadi `posted` secara sepihak untuk mencegah fabrikasi status publikasi.

## 5. Hal Terbuka & Belum Terverifikasi (`NOT_VERIFIED`)
1. Kredensial Shopee Affiliate Open API (`AppId` dan `Secret`) pengguna belum tersedia; seluruh data performa saat ini bersumber manual (`data_source="manual"`).
2. Mekanisme integrasi feed otomatis dari dashboard Shopee belum tersedia tanpa API resmi atau persetujuan pengguna.
3. Korelasi antara angle naskah promosi dan tingkat konversi masih membutuhkan data empiris yang lebih besar untuk menghasilkan kesimpulan statistik valid.

## 6. Tugas Berikutnya (Hanya Satu)
> **Membangun modul pemeringkatan dan rekomendasi angle naskah (`AngleRanker` / `CopywritingAdvisor`) berdasarkan perbandingan rasio konversi empiris (CTR dan Click-to-Order) dari metrik performa historis.**

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
