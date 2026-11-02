# DOKUMEN SERAH-TERIMA (HANDOFF)

Dokumen ini memuat status kerja terkini proyek **AI Affiliate Content Factory** untuk memastikan kontinuitas antarsesi asisten AI. Setiap sesi AI wajib memperbarui dokumen ini dan membuat commit Git sebelum mengakhiri sesi.

---

## 1. Tujuan Proyek
Membangun sistem semi-otomatis modular untuk memproduksi, mengaudit kepatuhan, dan melacak konversi konten afiliasi Shopee Indonesia berbasis Python deterministik, penyimpanan lokal SQLite, dan persetujuan manusia.

## 2. Fase Saat Ini
**Phase 2.2 Selesai Penuh** — Modul pemeringkatan angle performa (`AngleRanker`) dan penasihat naskah (`CopywritingAdvisor`) telah diimplementasikan penuh:
1. **Deduplikasi Snapshot Kumulatif:** Snapshot performa berulang pada konten yang sama hanya mengambil snapshot terbaru di jendela analisis; tidak dihitung ganda sebagai konten independen baru.
2. **Integritas Pemetaan Draf:** Konten hanya dipetakan jika draf memiliki versi prompt tunggal yang tidak ambigu. Record tanpa draf atau dengan versi prompt ganda (>1 versi) dieksklusikan dari ranking dan dicatat sebagai unmapped.
3. **Pemisahan Lintas Platform:** Secara default, komparasi performa antarplatform dipisahkan tegas untuk mencegah percampuran karakteristik audiens.
4. **Metrik Terbobot & Tanpa Ranking Palsu:** CTR dan Click-to-Order dihitung secara agregat berbobot dari kohort valid. Angle tanpa data performa diberikan `rank=None` dan status `TIDAK ADA DATA`.
5. **Pelabelan Bukti & Penasihat Naskah:** Setiap angle diberi label bukti (`BUKTI CUKUP` vs `BUKTI TERBATAS`) berdasarkan batas sampel minimum yang dapat dikonfigurasi. Advisor memberikan rekomendasi praktis, mendeteksi funnel gap (CTR tinggi, CR rendah), dan menyarankan eksplorasi tanpa mengklaim pemenang palsu.
Seluruh 86 unit test lolos pengujian tanpa error (`exit code 0`).

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
- `93dbdec`: Phase 2.1.1 — Performance Correction Auditability: koreksi snapshot atomik transaksional dengan audit payload sebelum/sesudah lengkap, proteksi rollback saat audit gagal, dan penelusuran sekuensial (71 unit test).
- `Phase 2.2 (Saat Ini)`: Angle Ranker & Copywriting Advisor: pemeringkatan angle deterministik berbobot, isolasi lintas platform, deduplikasi snapshot kumulatif, penanganan draf ambigu, pelabelan bukti sampel minimum, modul rekomendasi copywriting, dan subperintah CLI `performance angles` (86 unit test).

## 4. Keputusan Terkunci
1. **Runtime:** Python 3.12 pada `.venv` lokal menggunakan `uv`.
2. **Kontrak Data:** Pydantic v2 dengan validasi skema ketat (`extra="forbid"`). Model data baru mencakup `AnglePerformanceMetrics`, `AngleRankItem`, `AngleRankReport`, `UnmappedContentItem`, `CopywritingRecommendation`, dan `CopywritingAdviceReport`.
3. **Penyimpanan Snapshot & Immutabilitas:** Setiap observasi performa disimpan sebagai snapshot tersendiri dengan ID unik. Duplikasi ID ditolak secara default. Koreksi dilakukan atomik via `db.correct_performance_record` dengan jejak audit sebelum/sesudah.
4. **Agregasi Non-Double-Counting:** Deduplikasi snapshot kumulatif dilakukan dengan mengambil snapshot terbaru per `(content_id, platform)`.
5. **Isolasi Identitas Draf & Angle:** Hanya draf dengan versi prompt tunggal yang dipetakan ke angle. Draf dengan versi ganda atau tidak ditemukan dieksklusikan dari pemeringkatan demi integritas data.
6. **Rasio Konversi Berbobot Berbasis Kohort:** CTR dan Click-to-Order dihitung dari total pembilang dibagi total penyebut pada kohort observasi lengkap, bukan rata-rata sederhana persentase.
7. **Pemisahan Platform Default:** Data performa lintas platform tidak digabungkan kecuali operator memberikan flag `--all-platforms` secara eksplisit dengan catatan peringatan.
8. **Transparansi Bukti & Pembatasan Klaim:** Angle dengan sampel kecil di bawah `min_samples` diberi label `BUKTI TERBATAS`. CopywritingAdvisor dilarang menjanjikan kenaikan konversi, dilarang menyatakan korelasi sebagai kausalitas, dan dilarang mengubah status draf secara sepihak.

## 5. Hal Terbuka & Belum Terverifikasi (`NOT_VERIFIED`)
1. Kredensial Shopee Affiliate Open API (`AppId` dan `Secret`) pengguna belum tersedia; seluruh data performa saat ini bersumber manual (`data_source="manual"`).
2. Mekanisme integrasi feed otomatis dari dashboard Shopee belum tersedia tanpa API resmi atau persetujuan pengguna.
3. Korelasi antara angle naskah promosi dan tingkat konversi masih membutuhkan data empiris yang lebih besar untuk menghasilkan kesimpulan statistik valid.

## 6. Tugas Berikutnya (Hanya Satu)
> **Membangun modul generator variasi prompt dan naskah draf otomatis (`PromptVariantGenerator`) berdasarkan rekomendasi `CopywritingAdvisor`, dengan integrasi ke template prompt terstruktur dan alur penelaahan Review Gate.**

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
