# SYSTEM VERIFICATION LOG

Dokumen ini mencatat seluruh perintah pengujian, output aktual, bukti empiris di lingkungan lokal, dan status verifikasi komponen secara berkelanjutan.

---

## 1. Verifikasi Lingkungan Host & Git (Fase 0A & 0B)

| Tanggal | Target Pemeriksaan | Perintah / Uji | Hasil Aktual | Status |
| :--- | :--- | :--- | :--- | :--- |
| 2026-11-02 | Workspace Directory | `Get-ChildItem -Force -Recurse` | Direktori awal kosong | `VERIFIED` |
| 2026-11-02 | OS Version | Windows 11 x86_64 Environment | Running Windows PowerShell | `VERIFIED` |
| 2026-11-02 | Git Work Tree Status | `git rev-parse --is-inside-work-tree` | `fatal: not a git repository ...` (Exit Code 1) | `VERIFIED` (Awalnya bukan repo Git) |
| 2026-11-02 | Git Initialization | `git init` | Initialized empty Git repository | `VERIFIED TESTED` |
| 2026-11-02 | Git Ignore Setup | Pembuatan `.gitignore` | Mengabaikan `.env`, `.venv/`, `tmp/`, media, db; meng-commit `uv.lock` | `VERIFIED` |
| 2026-11-02 | Initial Rollback Commit | `git commit` | Commit `1463915` (Titik rollback aman) | `VERIFIED` |
| 2026-11-02 | Workspace Path Safety | Evaluasi string path | Path: `d:\Khadabra\Kerjaan gua\affiliate` (Mengandung spasi) | `VERIFIED` (Wajib Quoting/Pathlib) |
| 2026-11-02 | Python Host Version | `python --version` | `Python 3.15.0` (System Default) | `VERIFIED` |
| 2026-11-02 | Python Package Tool | `uv --version` | `uv 0.13.5 (46776a95d 2026-10-21)` | `VERIFIED` |
| 2026-11-02 | GPU & VRAM | `nvidia-smi` | RTX 4050 Laptop (6141 MiB VRAM), Driver `581.32`, CUDA `13.0` | `VERIFIED` |
| 2026-11-02 | FFmpeg Binary & License | `ffmpeg -L` | `GPL v3.0` (`--enable-gpl --enable-version3`) | `VERIFIED` |

---

## 2. Hasil Smoke Test Terisolasi (Fase 0B)

### A. Pembuatan Virtual Environment Python 3.12
- **Perintah:** `uv venv .venv --python 3.12`
- **Pemeriksaan Awal:** `Test-Path .venv` -> `False` (Aman, tidak menimpa venv yang sudah ada).
- **Exit Code:** `0`
- **Output:**
  ```text
  Using CPython 3.12.15
  Creating virtual environment at: .venv
  Activate with: .venv\Scripts\activate
  ```
- **Kesimpulan:** `VERIFIED`. Virtual environment `.venv` berhasil dibuat dengan Python 3.12.15 terisolasi.

### B. Instalasi dan Validasi Pydantic
- **Perintah Instalasi:** `uv pip install pydantic --python .venv\Scripts\python.exe`
- **Exit Code:** `0`
- **Paket Terpasang:**
  - `pydantic==2.14.2`
  - `pydantic-core==2.50.2`
  - `annotated-types==0.8.0`
  - `typing-extensions==4.16.0`
  - `typing-inspection==0.4.4`
- **Catatan Kegagalan Uji Pertama (SyntaxError):**
  - Perintah awal: `.venv\Scripts\python.exe -c "import pydantic; from pydantic import BaseModel; print('PYDANTIC_VERSION:', pydantic.__version__); class Product(BaseModel): id: int; name: str; price: float; p = Product(id=1, name='Test Produk', price=99000.0); print('MODEL_DUMP:', p.model_dump()); print('SUCCESS')"`
  - Exit Code: `1`
  - Penyebab: Parser Python melarang *compound statement* (`class`, `def`) digabungkan dengan titik koma (`;`) dalam satu baris ekspresi `-c`.
- **Perintah Pengujian Model Ulang (Berhasil):**
  ```powershell
  .venv\Scripts\python.exe -c "import pydantic; from pydantic import BaseModel`nclass Product(BaseModel):`n    id: int`n    name: str`n    price: float`np = Product(id=1, name='Test Produk', price=99000.0)`nprint('PYDANTIC_VERSION:', pydantic.__version__)`nprint('MODEL_DUMP:', p.model_dump())`nprint('TEST_RESULT: PASS')"
  ```
- **Exit Code:** `0`
- **Output:**
  ```text
  PYDANTIC_VERSION: 2.14.2
  MODEL_DUMP: {'id': 1, 'name': 'Test Produk', 'price': 99000.0}
  TEST_RESULT: PASS
  ```
- **Kesimpulan:** `VERIFIED`. Pydantic v2.14.2 terpasang dan sukses memvalidasi skema data runtime.

### C. Uji FFmpeg Video Encoding: `libx264` vs `h264_nvenc`
Uji rendering video sintetis berdurasi 5 detik dengan resolusi vertikal 1080x1920 (9:16) pada 30 fps ke direktori `tmp/`.

#### 1. Uji CPU Encoder (`libx264`):
- **Perintah:**
  ```powershell
  ffmpeg -y -f lavfi -i testsrc=size=1080x1920:rate=30 -t 5 -c:v libx264 -pix_fmt yuv420p tmp/test_libx264.mp4
  ```
- **Exit Code:** `0`
- **Waktu Eksekusi:** `1641 ms` (~1,64 detik) [Koreksi: 1641 milidetik, bukan 1.641 milidetik]
- **Verifikasi ffprobe:**
  ```json
  {
      "streams": [{
          "codec_name": "h264",
          "width": 1080,
          "height": 1920,
          "r_frame_rate": "30/1",
          "duration": "5.000000"
      }],
      "format": {
          "duration": "5.000000",
          "size": "103573"
      }
  }
  ```
- **Hasil:** `VERIFIED TESTED`. Encoding CPU (`libx264`) berjalan mulus dan menghasilkan file valid 103 KB.

#### 2. Uji GPU Hardware Encoder (`h264_nvenc`):
- **Perintah:**
  ```powershell
  ffmpeg -y -f lavfi -i testsrc=size=1080x1920:rate=30 -t 5 -c:v h264_nvenc -pix_fmt yuv420p tmp/test_nvenc.mp4
  ```
- **Exit Code:** `-40` (Function not implemented)
- **Waktu Eksekusi:** `70 ms` (Gagal instan)
- **Error Log Aktual:**
  ```text
  [h264_nvenc @ 00000264cd010a00] Driver does not support the required nvenc API version. Required: 13.1 Found: 13.0
  [h264_nvenc @ 00000264cd010a00] The minimum required Nvidia driver for nvenc is 610.00 or newer
  [vost#0:0/h264_nvenc @ 00000264cd0107c0] [enc:h264_nvenc @ 00000264ccff1900] Error while opening encoder...
  Task finished with error code: -40 (Function not implemented)
  Conversion failed!
  ```
- **Verifikasi File Hasil:** `tmp/test_nvenc.mp4` berukuran `0 byte`. `ffprobe` menghasilkan error `moov atom not found / Invalid data`.
- **Hasil:** `VERIFIED FAILED`. Klaim sebelumnya bahwa NVENC langsung berfungsi adalah **SALAH**. Build FFmpeg 9.0.2 membutuhkan driver NVIDIA 610.00+ (NVENC API 13.1), sedangkan driver sistem yang terpasang adalah 581.32 (NVENC API 13.0). Sesuai aturan, tidak ada modifikasi driver yang dilakukan. Encoder video yang terbukti bekerja adalah `libx264`.

---

## 3. Verifikasi Kebijakan & API Shopee Indonesia (Fase 0B, M0 & H0)

| Topik Pemeriksaan | Sumber Bukti | Temuan Aktual | Status | File Rujukan |
| :--- | :--- | :--- | :--- | :--- |
| **Endpoint Affiliate ID** | `affiliate.shopee.co.id` & `open.shopee.com` | `open-api.affiliate.shopee.co.id/graphql` tidak tertulis pada halaman publik tanpa login. Landing page adalah login form. | `NOT_VERIFIED` | [01_affiliate_api_endpoint.md](file:///d:/Khadabra/Kerjaan%20gua/affiliate/docs/sources/01_affiliate_api_endpoint.md) |
| **Metode Signature** | Shopee Docs & GraphQL schema | Pertentangan sumber: Seller v2 pakai HMAC-SHA256, komunitas affiliate pakai SHA-256 biasa. Metode tanda tangan hanya bisa dipastikan dengan kredensial nyata. | `NOT_VERIFIED` | [02_request_signature_method.md](file:///d:/Khadabra/Kerjaan%20gua/affiliate/docs/sources/02_request_signature_method.md) |
| **Batas Sub-IDs** | `affiliateshopee.com.br` | Kata `subids` tidak ditemukan pada HTML halaman tersebut. | `NOT_VERIFIED` | [03_subids_limit.md](file:///d:/Khadabra/Kerjaan%20gua/affiliate/docs/sources/03_subids_limit.md) |
| **HAKI & Content Theft** | Shopee Help Article 71218 | Kutipan: *"Hak cipta adalah hak hukum yang sah yang melindungi karya orisinal (misalnya musik, video)"*. Dilarang mengunggah konten yang melanggar HAKI. | `VERIFIED` | [04_ai_label_and_content_theft.md](file:///d:/Khadabra/Kerjaan%20gua/affiliate/docs/sources/04_ai_label_and_content_theft.md) |
| **Label Konten AI** | Shopee Help Article 203749 & 27618 | Kutipan 203749: *"Caption dibuat menggunakan AI. Pastikan Anda meninjau kembali isi caption sebelum dipublikasikan"*. Toggle Shopee Video pada 27618 berstatus dinamis. | `VERIFIED` (Definisi 203749) / `DOCUMENTATION_ONLY` (Toggle 27618) | [04_ai_label_and_content_theft.md](file:///d:/Khadabra/Kerjaan%20gua/affiliate/docs/sources/04_ai_label_and_content_theft.md) |
| **Disclosure Afiliasi Konsumen** | Shopee Help 71217, 71218, 73507 | Tidak ditemukan klausul harfiah pengungkapan hubungan afiliasi kepada audiens. | `NOT_FOUND setelah memeriksa: 71217, 71218, 73507` | [05_disclosure_and_automation_rules.md](file:///d:/Khadabra/Kerjaan%20gua/affiliate/docs/sources/05_disclosure_and_automation_rules.md) |
| **Larangan Scraping / Bot** | Shopee Help Article 71217 & 71218 | Kutipan 71217: *"menggunakan robot atau alat kueri otomatis lainnya, permintaan pencarian yang dihasilkan oleh komputer;"* & 71218: *"Jangan menggunakan skrip otomatis untuk mengumpulkan informasi dari Shopee"*. | `VERIFIED` | [05_disclosure_and_automation_rules.md](file:///d:/Khadabra/Kerjaan%20gua/affiliate/docs/sources/05_disclosure_and_automation_rules.md) |
| **Penggunaan Open API Resmi** | `open.shopee.com` | Penggunaan gateway resmi dengan kredensial sah diperbolehkan bagi mitra pengembang (berbeda secara hukum dan teknis dari scraping ilegal). | `DOCUMENTATION_ONLY` | [05_disclosure_and_automation_rules.md](file:///d:/Khadabra/Kerjaan%20gua/affiliate/docs/sources/05_disclosure_and_automation_rules.md) |

---

## 4. Hasil Pengujian Unit Test Fondasi (Fase M2)

- **Tanggal Eksekusi:** 2026-11-02
- **Lingkungan Pengujian:** `.venv\Scripts\python.exe` (Python 3.12.15) dengan standard library `unittest`
- **Perintah Eksekusi:**
  ```powershell
  $env:PYTHONPATH="src"; & ".\.venv\Scripts\python.exe" -m unittest discover -s tests -p "test_*.py" -v
  ```
- **Exit Code:** `0`
- **Output Terminal Mentah:**
  ```text
  test_claim_without_source_is_unverified (test_core.TestAffiliateFactoryCore.test_claim_without_source_is_unverified) ... ok
  test_draft_with_prohibited_claim_fails_with_correct_rule_id (test_core.TestAffiliateFactoryCore.test_draft_with_prohibited_claim_fails_with_correct_rule_id) ... ok
  test_draft_without_disclosure_fails_compliance (test_core.TestAffiliateFactoryCore.test_draft_without_disclosure_fails_compliance) ... ok
  test_duplicate_product_url_does_not_duplicate (test_core.TestAffiliateFactoryCore.test_duplicate_product_url_does_not_duplicate) ... ok
  test_orchestrator_run_twice_idempotence (test_core.TestAffiliateFactoryCore.test_orchestrator_run_twice_idempotence) ... ok
  test_performance_record_unknown_fields_remain_none (test_core.TestAffiliateFactoryCore.test_performance_record_unknown_fields_remain_none) ... ok
  test_valid_draft_passes_compliance (test_core.TestAffiliateFactoryCore.test_valid_draft_passes_compliance) ... ok

  ----------------------------------------------------------------------
  Ran 7 tests in 0.009s

  OK
  ```
- **Kesimpulan Evaluasi:**
  1. `test_draft_without_disclosure_fails_compliance`: Draft tanpa disclosure terdeteksi gagal dengan finding `RULE-DISCLOSURE-01` (`PASS`).
  2. `test_draft_with_prohibited_claim_fails_with_correct_rule_id`: Klaim "pasti sembuh" terdeteksi gagal dengan finding `RULE-PROHIBITED-CLAIMS-01` (`PASS`).
  3. `test_valid_draft_passes_compliance`: Draft valid dengan disclosure dan label AI lolos evaluasi (`PASS`).
  4. `test_claim_without_source_is_unverified`: Klaim tanpa `source_ref` ditandai `UNVERIFIED`; klaim dengan sumber ditandai `SOURCED` (`PASS`).
  5. `test_duplicate_product_url_does_not_duplicate`: Ingest produk dengan URL sama dua kali mengembalikan record yang ada tanpa menduplikasi baris di tabel `products` (`PASS`).
  6. `test_orchestrator_run_twice_idempotence`: Menjalankan pipeline dua kali pada draft yang sama menghasilkan tepat 1 baris draft dan status tetap tertahan di `waiting_approval` (`PASS`).
  7. `test_performance_record_unknown_fields_remain_none`: Metrik performa yang tidak diketahui tetap bernilai `None` di memori dan saat disimpan/diambil dari SQLite, tidak pernah berubah menjadi `0` (`PASS`).

---

## 5. Audit Kloning Referensi & Studi Kelayakan Animasi (Fase V0)

- **Tanggal Eksekusi:** 2026-11-02
- **Perintah Kloning (Read-Only):**
  ```powershell
  git clone https://github.com/humaedihume/kantor-agent tmp/reference/kantor-agent
  ```
- **Exit Code:** `0`
- **Tindakan Kepatuhan:**
  - File skrip `kantor.sh`, `serve-node.mjs`, atau skrip lainnya **TIDAK DIJALANKAN**.
  - Kode dianalisis secara *read-only* murni untuk mengekstrak skema JSON dan mekanisme pembacaan transkrip.
  - Laporan lengkap diterbitkan di [docs/VIZ_FEASIBILITY.md](file:///d:/Khadabra/Kerjaan%20gua/affiliate/docs/VIZ_FEASIBILITY.md).

---

## 6. Hasil Pengujian Suite Unit Test Lengkap Termasuk Context Pack (Fase H0)

- **Tanggal Eksekusi:** 2026-11-02
- **Lingkungan Pengujian:** `.venv\Scripts\python.exe` (Python 3.12.15) dengan standard library `unittest`
- **Perintah Eksekusi:**
  ```powershell
  $env:PYTHONPATH="src;."; & ".\.venv\Scripts\python.exe" -m unittest discover -s tests -p "test_*.py" -v
  ```
- **Exit Code:** `0`
- **Output Terminal Mentah:**
  ```text
  test_generate_context_pack (test_context_pack.TestContextPackGenerator.test_generate_context_pack) ... ok
  test_claim_without_source_is_unverified (test_core.TestAffiliateFactoryCore.test_claim_without_source_is_unverified) ... ok
  test_draft_with_prohibited_claim_fails_with_correct_rule_id (test_core.TestAffiliateFactoryCore.test_draft_with_prohibited_claim_fails_with_correct_rule_id) ... ok
  test_draft_without_disclosure_fails_compliance (test_core.TestAffiliateFactoryCore.test_draft_without_disclosure_fails_compliance) ... ok
  test_duplicate_product_url_does_not_duplicate (test_core.TestAffiliateFactoryCore.test_duplicate_product_url_does_not_duplicate) ... ok
  test_orchestrator_run_twice_idempotence (test_core.TestAffiliateFactoryCore.test_orchestrator_run_twice_idempotence) ... ok
  test_performance_record_unknown_fields_remain_none (test_core.TestAffiliateFactoryCore.test_performance_record_unknown_fields_remain_none) ... ok
  test_valid_draft_passes_compliance (test_core.TestAffiliateFactoryCore.test_valid_draft_passes_compliance) ... ok

  ----------------------------------------------------------------------
  Ran 8 tests in 0.058s

  OK
  ```
- **Kesimpulan:** Seluruh 8 test case berhasil diverifikasi lolos (`OK`). `test_generate_context_pack` memvalidasi bahwa `tools/make_context_pack.py` menghasilkan berkas konsolidasi `output/context_pack.md` yang memuat seluruh judul bagian dengan format tepat.

---

## 7. Verifikasi Fitur Phase 1 MVP (CLI, Prompting, Import Draft, dan Invariant Klaim)

- **Tanggal Eksekusi:** 2026-11-02
- **Lingkungan Pengujian:** `.venv\Scripts\python.exe` (Python 3.12.15) dengan standard library `unittest`
- **Perintah Eksekusi:**
  ```powershell
  $env:PYTHONPATH="src;."; & ".\.venv\Scripts\python.exe" -m unittest discover -s tests -p "test_*.py" -v
  ```
- **Exit Code:** `0`
- **Output Terminal Mentah:**
  ```text
  test_generate_context_pack (test_context_pack.TestContextPackGenerator.test_generate_context_pack) ... ok
  test_claim_without_source_is_unverified (test_core.TestAffiliateFactoryCore.test_claim_without_source_is_unverified) ... ok
  test_draft_with_prohibited_claim_fails_with_correct_rule_id (test_core.TestAffiliateFactoryCore.test_draft_with_prohibited_claim_fails_with_correct_rule_id) ... ok
  test_draft_without_disclosure_fails_compliance (test_core.TestAffiliateFactoryCore.test_draft_without_disclosure_fails_compliance) ... ok
  test_duplicate_product_url_does_not_duplicate (test_core.TestAffiliateFactoryCore.test_duplicate_product_url_does_not_duplicate) ... ok
  test_orchestrator_run_twice_idempotence (test_core.TestAffiliateFactoryCore.test_orchestrator_run_twice_idempotence) ... ok
  test_performance_record_unknown_fields_remain_none (test_core.TestAffiliateFactoryCore.test_performance_record_unknown_fields_remain_none) ... ok
  test_valid_draft_passes_compliance (test_core.TestAffiliateFactoryCore.test_valid_draft_passes_compliance) ... ok
  test_cli_intake_duplicate_urls_handled_safely (test_phase1_mvp.TestPhase1MVP.test_cli_intake_duplicate_urls_handled_safely) ... ok
  test_cli_intake_invalid_json_and_validation_error (test_phase1_mvp.TestPhase1MVP.test_cli_intake_invalid_json_and_validation_error) ... ok
  test_cli_intake_single_and_array_json (test_phase1_mvp.TestPhase1MVP.test_cli_intake_single_and_array_json) ... ok
  test_cli_subcommands_smoke (test_phase1_mvp.TestPhase1MVP.test_cli_subcommands_smoke) ... ok
  test_parse_and_validate_ai_draft_success (test_phase1_mvp.TestPhase1MVP.test_parse_and_validate_ai_draft_success) ... ok
  test_parse_malformed_ai_output_fails_gracefully (test_phase1_mvp.TestPhase1MVP.test_parse_malformed_ai_output_fails_gracefully) ... ok
  test_pipeline_integration_with_imported_draft (test_phase1_mvp.TestPhase1MVP.test_pipeline_integration_with_imported_draft) ... ok
  test_product_invalid_url_scheme_rejected (test_phase1_mvp.TestPhase1MVP.test_product_invalid_url_scheme_rejected) ... ok
  test_product_negative_price_rejected (test_phase1_mvp.TestPhase1MVP.test_product_negative_price_rejected) ... ok
  test_prompt_generation_deterministic_and_no_fabrication (test_phase1_mvp.TestPhase1MVP.test_prompt_generation_deterministic_and_no_fabrication) ... ok
  test_unverified_claim_cannot_silently_become_verified (test_phase1_mvp.TestPhase1MVP.test_unverified_claim_cannot_silently_become_verified) ... ok

  ----------------------------------------------------------------------
  Ran 19 tests in 0.424s

  OK
  ```
- **Kesimpulan Evaluasi:**
  1. `test_product_negative_price_rejected`: Model `Product` menolak harga negatif (`price < 0`) via validator (`PASS`).
  2. `test_product_invalid_url_scheme_rejected`: Model `Product` menolak skema non-HTTP/HTTPS (`PASS`).
  3. `test_cli_intake_single_and_array_json`: CLI `intake` berhasil memproses berkas JSON objek tunggal maupun array ke SQLite (`PASS`).
  4. `test_cli_intake_duplicate_urls_handled_safely`: CLI `intake` mendeteksi URL duplikat dan melewatinya tanpa menduplikasi baris database (`PASS`).
  5. `test_cli_intake_invalid_json_and_validation_error`: Menangani berkas korup atau skema salah dengan pesan diagnostik yang jelas dan exit code 1 (`PASS`).
  6. `test_prompt_generation_deterministic_and_no_fabrication`: Template prompt menghasilkan teks deterministik, menyertakan seluruh atribut produk terverifikasi, dan memuat larangan keras pengadaan klaim fiktif (`PASS`).
  7. `test_parse_and_validate_ai_draft_success`: Mem-parsing JSON output AI (termasuk yang dibungkus markdown codeblock) ke dalam model `ContentDraft` dan `list[Claim]` (`PASS`).
  8. `test_parse_malformed_ai_output_fails_gracefully`: Output AI yang tidak terstruktur atau cacat skema memicu `ValueError` dengan keterangan jelas (`PASS`).
  9. `test_unverified_claim_cannot_silently_become_verified`: Klaim berstatus `UNVERIFIED` tidak dapat berubah status hanya karena `source_ref` tidak kosong (`PASS`).
  10. `test_pipeline_integration_with_imported_draft`: Draf yang diimpor dialirkan ke `run_pipeline`, berhasil dievaluasi kepatuhannya, dan berhenti pada status `waiting_approval` (`PASS`).
  11. `test_cli_subcommands_smoke`: Smoke test terhadap seluruh subperintah CLI (`intake`, `prompt`, `import-draft`, `inspect`) berjalan sukses (`PASS`).

---

## 8. Verifikasi Human Review Gate, Migrasi Skema SQLite `compliance_reports`, dan Atomic Content Pack Export

- **Tanggal Eksekusi:** 2026-11-02
- **Lingkungan Pengujian:** `.venv\Scripts\python.exe` (Python 3.12.15) dengan standard library `unittest`
- **Perintah Eksekusi:**
  ```powershell
  $env:PYTHONPATH="src;."; & ".\.venv\Scripts\python.exe" -m unittest discover -s tests -p "test_*.py" -v
  ```
- **Exit Code:** `0`
- **Output Terminal:**
  ```text
  Ran 35 tests in 1.189s

  OK
  ```
- **Rincian Pengujian Baru (16 Test Cases pada `tests/test_review_and_export.py`):**
  1. `test_approve_valid_waiting_draft`: Persetujuan draf yang valid pada status `waiting_approval` dengan seluruh klaim berstatus `VERIFIED` berhasil mengubah status ke `approved` dan mencatat event `human_approve` (`PASS`).
  2. `test_approve_idempotent`: Menyetujui ulang draf yang sudah berstatus `approved` mengembalikan status sukses secara idempoten tanpa error (`PASS`).
  3. `test_reject_eligible_draft_and_record_reason`: Penolakan draf pada status `waiting_approval` mencatat alasan penolakan dan event `human_reject` serta bersifat idempoten (`PASS`).
  4. `test_reject_empty_reason_blocked`: Penolakan dengan alasan kosong atau spasi ditolak dengan `ReviewError` (`PASS`).
  5. `test_prevent_approval_with_unresolved_claims`: Draf dengan klaim berstatus `UNVERIFIED` atau `SOURCED` (belum diverifikasi manusia) diblokir dari persetujuan (`PASS`).
  6. `test_prevent_approval_with_rejected_claims`: Draf yang memiliki klaim yang telah ditolak (`REJECTED`) diblokir dari persetujuan (`PASS`).
  7. `test_prevent_approval_with_blocking_compliance_findings`: Draf dengan laporan kepatuhan yang gagal (`passed == False`) diblokir dari persetujuan (`PASS`).
  8. `test_prevent_invalid_state_transitions`: Menolak transisi ilegal (misal menyetujui draf yang ditolak, menolak draf yang sudah disetujui, atau menyetujui draf berstatus `draft`) (`PASS`).
  9. `test_review_claim_individually`: Penelaahan klaim individual oleh manusia berhasil mengubah status menjadi `VERIFIED` dan mencatat event `review_claim` dengan catatan penelaah (`PASS`).
  10. `test_prevent_export_of_unapproved_drafts`: Permintaan ekspor draf pada status `waiting_approval`, `rejected`, atau `draft` ditolak oleh gerbang ekspor (`ExportGateError`) (`PASS`).
  11. `test_export_approved_draft_and_validate_all_files`: Ekspor draf `approved` menghasilkan seluruh 6 berkas (`script.md`, `caption.txt`, `hashtags.txt`, `product_info.json`, `review_checklist.md`, `manifest.json`) dengan checksum SHA-256 terverifikasi (`PASS`).
  12. `test_reject_path_traversal_in_draft_id`: Upaya path traversal pada draft ID (`..`, separator path, karakter ilegal) ditolak oleh fungsi sanitasi (`PASS`).
  13. `test_handle_output_collisions_safely`: Direktori ekspor yang sudah ada menolak penimpaan tanpa bendera `--overwrite`, dan berhasil menimpa jika bendera `--overwrite` diberikan (`PASS`).
  14. `test_failed_export_leaves_no_misleading_pack_or_event`: Kegagalan penulisan saat staging tidak meninggalkan berkas paket parsial dan tidak mencatat event sukses ekspor (`PASS`).
  15. `test_database_migration_compliance_reports`: Database legacy dengan primary key tunggal `draft_id` termigrasi secara transparan menjadi komposit `(draft_id, prompt_version)` tanpa kehilangan data legacy dan mendukung multiversi (`PASS`).
  16. `test_cli_review_and_export_smoke`: Smoke test terhadap seluruh subperintah CLI `review show`, `review claim`, `review approve`, `review reject`, dan `export` berjalan dengan exit code 0 (`PASS`).


---

## 9. Verifikasi Phase 1.1: Isolasi Klaim per Versi Draf, Invariant Review Gate, dan Eksportir

- **Tanggal Eksekusi:** 2026-11-02
- **Lingkungan Pengujian:** `.venv\Scripts\python.exe` (Python 3.12.15) dengan standard library `unittest`
- **Perintah Eksekusi:**
  ```powershell
  $env:PYTHONPATH="src;."; & ".\.venv\Scripts\python.exe" -m unittest discover -s tests -p "test_*.py" -v
  ```
- **Exit Code:** `0`
- **Output Terminal:**
  ```text
  Ran 44 tests in 1.948s

  OK
  ```
- **Rincian Pengujian Baru (9 Test Cases pada `tests/test_phase1_1_isolation.py`):**
  1. `test_claims_isolated_across_prompt_versions_for_same_draft_id`: Draf dengan ID sama yang memiliki versi prompt v1.0 dan v2.0 memiliki klaim terisolasi. Klaim `UNVERIFIED` pada v1.0 tidak memblokir persetujuan v2.0, dan v1.0 tetap diblokir persetujuannya (`PASS`).
  2. `test_export_of_v2_never_includes_v1_claims`: Ekspor paket konten versi v2.0 hanya memuat klaim versi v2.0 pada berkas `review_checklist.md` dan tidak membocorkan klaim versi v1.0 (`PASS`).
  3. `test_cannot_modify_claims_of_approved_draft`: Modifikasi atau penelaahan ulang klaim pada draf yang telah berstatus `approved` diblokir dengan `ReviewError` (`PASS`).
  4. `test_cannot_review_claims_of_rejected_draft`: Penelaahan klaim pada draf yang berstatus `rejected` diblokir dengan `ReviewError` (status terminal mewajibkan revisi versi prompt baru) (`PASS`).
  5. `test_expected_prompt_version_mismatch_raises_error`: Penelaahan klaim dengan parameter versi prompt yang tidak cocok dengan versi klaim memicu `ReviewError` (`PASS`).
  6. `test_fail_closed_sourced_claim_without_human_verification_blocks_approval`: Klaim berstatus `SOURCED` (memiliki tautan rujukan sumber) tetap memblokir persetujuan draf hingga ditelaah dan diverifikasi eksplisit oleh manusia (`PASS`).
  7. `test_safe_overwrite_preserves_original_on_failure`: Penimpaan paket konten yang gagal di tengah proses secara otomatis memulihkan direktori asli dari cadangan sehingga berkas valid sebelumnya tidak hilang atau rusak (`PASS`).
  8. `test_symlink_target_rejection`: Upaya ekspor ke direktori target yang merupakan symlink langsung ditolak (`ValueError`) (`PASS`).
  9. `test_database_migration_claims_prompt_version`: Tabel `claims` legacy tanpa kolom `prompt_version` termigrasi secara otomatis ke skema baru; draf versi tunggal diasosiasikan secara pasti, sementara draf multiversi atau yatim dibiarkan `NULL` tanpa fabrikasi data (`PASS`).
