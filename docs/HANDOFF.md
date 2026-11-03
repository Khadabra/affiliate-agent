# DOKUMEN SERAH-TERIMA (HANDOFF)

Dokumen ini memuat status kerja terkini proyek **AI Affiliate Content Factory** untuk memastikan kontinuitas antarsesi asisten AI. Setiap sesi AI wajib memperbarui dokumen ini dan membuat commit Git sebelum mengakhiri sesi.

---

## 1. Tujuan Proyek
Membangun sistem semi-otomatis modular untuk memproduksi, mengaudit kepatuhan, dan melacak konversi konten afiliasi Shopee Indonesia berbasis Python deterministik, penyimpanan lokal SQLite, dan persetujuan manusia.

## 2. Fase Saat Ini
**Phase 3.3 Selesai Implementasi & Verifikasi** — Specialist agents deterministic/manual-first telah dibangun di atas fondasi Phase 3.1–3.2:
1. **Specialists:** Research, Content Writer, Fact Checker, Compliance, Human Approval Gate, Export, dan Analytics tersedia sebagai `BaseAgent` terdaftar.
2. **Default workflow:** Research → Content Writer → Fact Checker → Compliance → Human Approval → Export; Analytics tetap terpisah.
3. **Evidence safety:** Research mempertahankan provenance; Writer hanya memakai fakta supported; Fact Checker tidak menandai klaim sebagai verified otomatis; Compliance menggunakan engine fail-closed existing.
4. **Human approval:** Workflow berhenti pada approval pause; resume membutuhkan keputusan eksplisit; Export memanggil existing human claim review dan `approve_draft` sebelum exporter.
5. **Preflight:** Symlink guard lulus inspeksi code tetapi 4 test filesystem tetap environmental skip `WinError 1314`; in-memory sink failure kini recoverable tanpa duplicate task.
6. **Hasil:** 8 test specialist, 57 impacted test, dan full suite 138 test exit code 0; 4 test symlink tetap di-skip.

Phase 3.2 sebelumnya telah menyelesaikan Workflow Orchestrator multi-agent:
1. **Workflow definitions:** `WorkflowDefinition` memvalidasi step, dependency graph, agent ID/capability, input/output mapping, retry, dan version.
2. **Coordination:** `WorkflowExecutor` menjalankan task sekuensial sesuai dependency, meneruskan output tervalidasi, memblokir downstream saat gagal, dan melindungi duplicate execution.
3. **Retry & recovery:** hanya error type yang dikonfigurasi yang diulang; validation error tidak diulang; execution non-terminal dapat di-recover dengan deterministic task IDs.
4. **Human approval:** step approval mem-pause workflow; hanya keputusan eksplisit `APPROVE` yang melanjutkan dan `REJECT` yang menghentikan; tidak ada automatic approval.
5. **Persistence & events:** state workflow/step dan event SQLite default ditulis atomik per operasi; in-memory sink tetap didukung dengan guarantee terpisah yang terdokumentasi.
6. **Hasil:** 8 test Phase 3.2, 21 test Phase 3.1+3.2, dan full suite 129 test sebelum Phase 3.3 exit code 0; 4 test symlink lama tetap di-skip karena `WinError 1314`.

Phase 3.1 sebelumnya telah menyelesaikan fondasi Modular Agent Architecture:
1. **Kontrak & eksekusi:** `AgentTask`, `AgentResult`, `AgentEvent`, metadata, `BaseAgent`, registry, execution context, dan sequential agent orchestrator tersedia dengan validasi Pydantic.
2. **Lifecycle & observability:** transisi `idle → queued → running → completed|failed` divalidasi; event lifecycle terurut, berkorelasi, dan dapat dipersistenkan.
3. **Provider boundary:** provider abstraction siap untuk implementasi lokal/eksternal; provider tidak tersedia, timeout, dan error ditangani typed; tidak ada paid API baru.
4. **Persistence:** tabel aditif `agent_tasks` dan `agent_events` memakai SQLite existing dengan FK aktif; tidak ada database produksi yang digunakan.

Phase 2.2.3 sebelumnya telah menyelesaikan verifikasi end-to-end workflow utama:
1. **Workflow sukses:** Intake → Prompt → Import Draft → Claim Review → Compliance → Human Approval → Export → Performance Recording → Analytics berhasil dijalankan pada database dan filesystem temporary.
2. **Failure paths:** Compliance violation, unsupported claim, export sebelum approval, rejected export, invalid product, dan invalid draft ditolak tanpa partial record yang merusak.
3. **Repeatability & analytics:** Intake/import berulang tidak menggandakan identitas; snapshot terbaru tidak double-counted; platform dipisahkan; correction dan ranking dapat ditelusuri.
4. **Hasil:** 3 integration test dan full suite 108 test exit code 0; 4 test symlink filesystem di-skip karena Windows mengembalikan `WinError 1314`.

Phase 2.2.2 sebelumnya telah menerapkan perbaikan keamanan dan integritas data:
1. **Compliance fail-closed:** Konfigurasi compliance yang hilang, malformed, unreadable, atau berskema tidak valid menghasilkan report gagal dan memblokir pipeline sebelum approval.
2. **Validasi URL:** Product URL dibatasi ke HTTP/HTTPS dengan hostname valid; whitespace/control character, credential, host malformed, dan port invalid ditolak.
3. **SQLite foreign keys:** `PRAGMA foreign_keys = ON` diterapkan pada setiap koneksi file dan memory tanpa mengubah schema.
4. **Proteksi symlink exporter:** Target mentah diperiksa sebelum canonical resolution dan containment validation tetap dipertahankan.
Seluruh 105 unit test selesai dengan exit code 0; 4 test symlink filesystem di-skip karena Windows mengembalikan `WinError 1314` saat pembuatan symlink.

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
- `Phase 2.2.1`: Analytics & Advisor Integrity Fix: preservasi semantik None vs 0, kelayakan pemeringkatan berbasis metrik valid sort_by, pemisahan unranked_missing_metric_angles, pembersihan asumsi komersial template advisor, validasi parameter min_samples (94 unit test).
- `Phase 2.2.2 (Implementasi Lokal)`: Security & Data Integrity Hardening: compliance fail-closed, validasi URL berbasis parsing, SQLite foreign key enforcement per koneksi, dan pemeriksaan symlink exporter sebelum resolve (105 unit test, 4 skip symlink karena privilege Windows).
- `Phase 2.2.3 (Verifikasi Workflow)`: Integration test CLI end-to-end untuk alur intake sampai analytics, failure paths, repeatability, platform separation, dan correction (108 unit test, 4 skip symlink karena privilege Windows).
- `Phase 3.1 (Agent Foundation)`: Kontrak Pydantic, base agent, registry, execution context, provider abstraction, sequential agent orchestrator, lifecycle events, dan persistence SQLite aditif (120 test, 4 skip symlink karena privilege Windows).
- `Phase 3.2 (Workflow Orchestrator)`: Workflow definitions, dependency-aware sequential executor, mappings, retry/recovery, human approval pause/resume, workflow events, dan persistence transaksi SQLite (129 test, 4 skip symlink karena privilege Windows).
- `Phase 3.3 (Specialist Agents)`: Research, Content Writer, Fact Checker, Compliance, Human Approval Gate, Export, Analytics, default content workflow, in-memory recovery hardening, dan pre-flight symlink verification (138 test, 4 skip symlink karena privilege Windows).

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
> **Phase 3.4: evaluasi kontrak specialist-agent terhadap kebutuhan Dashboard/Agent Office read model tanpa menambahkan UI atau API eksternal.**

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
