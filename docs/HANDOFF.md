# DOKUMEN SERAH-TERIMA (HANDOFF)

Dokumen ini memuat status kerja terkini proyek **AI Affiliate Content Factory** untuk memastikan kontinuitas antarsesi asisten AI. Setiap sesi AI wajib memperbarui dokumen ini dan membuat commit Git sebelum mengakhiri sesi.

---

## 1. Tujuan Proyek
Membangun sistem semi-otomatis modular untuk memproduksi, mengaudit kepatuhan, dan melacak konversi konten afiliasi Shopee Indonesia berbasis Python deterministik, penyimpanan lokal SQLite, dan persetujuan manusia.

## 2. Fase Saat Ini
**Phase 2.2.1 Selesai Penuh** — Perbaikan integritas analitik dan penasihat naskah (`Analytics & Advisor Integrity Fix`) telah selesai dan terverifikasi penuh:
1. **Preservasi Semantik None vs Nol:** Metrik yang tidak tercatat bernilai `None` dan secara konsisten diformat sebagai `N/A` atau `[tidak diketahui]`, bukan `0.00%` atau `0 pesanan`. Nilai pesanan nol (`orders == 0`) yang benar-benar tercatat tetap dibedakan dari nilai yang tidak diketahui (`orders is None`).
2. **Kelayakan Pemeringkatan (Ranking Eligibility):** Angle yang tidak memiliki metrik valid untuk kriteria pengurutan yang dipilih (`--sort-by`) tidak diberi peringkat menyesatkan, melainkan dipisahkan ke `unranked_missing_metric_angles` dengan `rank=None` dan catatan kualitas data transparan.
3. **Pemisahan Kategori Angle:** Memisahkan secara tegas: (a) angle yang memenuhi syarat pemeringkatan (`ranked_angles`), (b) angle yang memiliki data tetapi metrik sort tidak tersedia (`unranked_missing_metric_angles`), dan (c) angle tanpa data performa sama sekali (`unranked_angles`).
4. **Integritas Bukti Advisor:** CopywritingAdvisor dilarang mengklaim angle sebagai pemenang konversi jika data pesanan/konversi belum tersedia, dan merekomendasikan eksplorasi pengumpulan data.
5. **Netralitas Template Advisor:** Seluruh asumsi komersial tanpa sumber (seperti "harga promo", "garansi resmi", "voucher toko", "keranjang kuning") telah dibersihkan dari template advisor, digantikan dengan draf hipotesis netral berstatus DRAFT di bawah kontrol Review Gate manusia.
6. **Validasi Parameter:** Parameter `--min-samples` divalidasi ketat (`> 0`); nilai nol atau negatif ditolak deterministik pada modul `AngleRanker` dan CLI.
Seluruh 94 unit test lolos pengujian tanpa error (`exit code 0`).

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
- `271007d`: Phase 2.2 — Angle Ranker & Copywriting Advisor: pemeringkatan angle deterministik berbobot, isolasi lintas platform, deduplikasi snapshot kumulatif, penanganan draf ambigu, pelabelan bukti sampel minimum, modul rekomendasi copywriting, dan subperintah CLI `performance angles` (86 unit test).
- `Phase 2.2.1 (Saat Ini)`: Analytics & Advisor Integrity Fix: preservasi semantik None vs 0, kelayakan pemeringkatan berbasis metrik valid sort_by, pemisahan unranked_missing_metric_angles, pembersihan asumsi komersial template advisor, validasi parameter min_samples (94 unit test).

## 4. Keputusan Terkunci
1. **Runtime:** Python 3.12 pada `.venv` lokal menggunakan `uv`.
2. **Kontrak Data:** Pydantic v2 dengan validasi skema ketat (`extra="forbid"`). Model data mencakup `AnglePerformanceMetrics`, `AngleRankItem`, `AngleRankReport`, `UnmappedContentItem`, `CopywritingRecommendation`, dan `CopywritingAdviceReport`.
3. **Penyimpanan Snapshot & Immutabilitas:** Setiap observasi performa disimpan sebagai snapshot tersendiri dengan ID unik. Duplikasi ID ditolak secara default. Koreksi dilakukan atomik via `db.correct_performance_record` dengan jejak audit sebelum/sesudah.
4. **Agregasi Non-Double-Counting:** Deduplikasi snapshot kumulatif dilakukan dengan mengambil snapshot terbaru per `(content_id, platform)`.
5. **Isolasi Identitas Draf & Angle:** Hanya draf dengan versi prompt tunggal yang dipetakan ke angle. Draf dengan versi ganda atau tidak ditemukan dieksklusikan dari pemeringkatan demi integritas data.
6. **Rasio Konversi Berbobot Berbasis Kohort:** CTR dan Click-to-Order dihitung dari total pembilang dibagi total penyebut pada kohort observasi lengkap, bukan rata-rata sederhana persentase.
7. **Pemisahan Platform Default:** Data performa lintas platform tidak digabungkan kecuali operator memberikan flag `--all-platforms` secara eksplisit dengan catatan peringatan.
8. **Transparansi Bukti & Pembatasan Klaim:** Angle dengan sampel kecil di bawah `min_samples` diberi label `BUKTI TERBATAS`. CopywritingAdvisor dilarang menjanjikan kenaikan konversi, dilarang menyatakan korelasi sebagai kausalitas, dan dilarang mengubah status draf secara sepihak.
9. **Semantik None vs Nol & Kelayakan Ranking:** `None` merepresentasikan metrik yang belum diukur/diketahui (`N/A`), tidak pernah difabrikasi menjadi 0. Angle tanpa metrik valid untuk `--sort-by` tidak diberi peringkat palsu, melainkan dipisahkan ke `unranked_missing_metric_angles` dengan `rank=None`.
10. **Netralitas Template Saran:** Seluruh saran copywriting bebas dari asumsi komersial tanpa sumber ("promo", "garansi", "voucher", "keranjang kuning") dan berstatus draf di bawah kontrol persetujuan manusia.

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
