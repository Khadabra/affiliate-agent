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


---

## 10. Verifikasi Phase 2: Performance Tracking & Conversion Analytics

- **Tanggal Eksekusi:** 2026-11-02
- **Lingkungan Pengujian:** `.venv\Scripts\python.exe` (Python 3.12.15) dengan standard library `unittest`
- **Perintah Eksekusi:**
  ```powershell
  $env:PYTHONPATH="src;."; & ".\.venv\Scripts\python.exe" -m unittest discover -s tests -p "test_*.py" -v
  ```
- **Exit Code:** `0`
- **Output Terminal:**
  ```text
  Ran 55 tests in 2.166s

  OK
  ```
- **Rincian Pengujian Baru (11 Test Cases pada `tests/test_performance.py`):**
  1. `test_record_and_retrieve_single_snapshot`: Pencatatan dan pembacaan kembali satu snapshot metrik performa (`PerformanceRecord`) dengan seluruh atribut (`views`, `clicks`, `orders`, `commission_idr`, `platform`, `observed_at`, `data_source`) tersimpan persis di SQLite (`PASS`).
  2. `test_multiple_snapshots_retained_chronologically_no_overwrite`: Penyimpanan snapshot berulang pada konten yang sama tidak menimpa riwayat terdahulu; seluruh snapshot dipertahankan secara kronologis (`PASS`).
  3. `test_unknown_fields_remain_none_never_defaulted_to_zero`: Bidang metrik yang tidak diketahui/tidak diukur tetap bernilai `None` dan tidak disulap menjadi 0 (`PASS`).
  4. `test_negative_metrics_rejected`: Nilai negatif untuk tayangan, klik, pesanan, atau komisi ditolak langsung oleh validator model (`PASS`).
  5. `test_conversion_rates_zero_and_none_denominators`: Perhitungan rasio konversi (CTR, Click-to-Order) aman dari pembagian nol (menghasilkan `None`, bukan 0.0 atau crash), dan mempertahankan nilai 0.0 jika pembilang nol namun penyebut valid (`PASS`).
  6. `test_discrepancy_warnings_generated`: Logika bisnis mendeteksi anomali (misal: klik > tayangan atau pesanan > klik) dan menghasilkan peringatan diagnostik tanpa menolak data nyata secara kaku (`PASS`).
  7. `test_summary_never_double_counts_cumulative_snapshots`: Agregasi ringkasan performa secara ketat mengambil snapshot terbaru untuk setiap `(content_id, platform)` dan menjumlahkan snapshot terbaru tersebut, mencegah penghitungan ganda atas metrik kumulatif (`PASS`).
  8. `test_filter_by_content_platform_and_date_range`: Kueri database mendukung filter berdasarkan `content_id`, `platform`, serta rentang waktu observasi (`start_date` dan `end_date`) (`PASS`).
  9. `test_duplicate_record_id_handling`: Penanganan tabrakan ID snapshot dilakukan secara eksplisit via `ON CONFLICT(id) DO UPDATE` (`PASS`).
  10. `test_cli_performance_record_show_summary_smoke`: Pengujian smoke test seluruh subperintah CLI (`performance record`, `performance show`, `performance summary`) berjalan sukses dengan pencatatan audit log (`PASS`).
  11. `test_cli_rejects_invalid_inputs_with_nonzero_exit_code`: CLI menolak nilai negatif, format timestamp tidak valid, dan rentang tanggal salah dengan pesan diagnostik yang jelas dan exit code 1 (`PASS`).

---

## 11. Verifikasi Phase 2.1: Data Integrity & Analytics Hardening

- **Tanggal Eksekusi:** 2026-11-02
- **Lingkungan Pengujian:** `.venv\Scripts\python.exe` (Python 3.12.15) dengan standard library `unittest`
- **Perintah Eksekusi:**
  ```powershell
  $env:PYTHONPATH="src;."; & ".\.venv\Scripts\python.exe" -m unittest discover -s tests -p "test_*.py" -v
  ```
- **Exit Code:** `0`
- **Output Terminal:**
  ```text
  Ran 65 tests in 3.309s

  OK
  ```
- **Rincian Pengujian & Perbaikan Hardening (10 Test Cases Baru & Pembaruan pada `tests/test_performance.py`):**
  1. `test_duplicate_record_id_handling`: Penolakan tegas atas penimpaan tidak sengaja pada snapshot historis via `ValueError` ketika `allow_overwrite=False`. Snapshot hanya dapat diperbarui jika `allow_overwrite=True` diberikan secara eksplisit (`PASS`).
  2. `test_non_finite_commission_rejected`: Validator `PerformanceRecord` menolak nilai non-finite untuk komisi (`NaN`, `+Inf`, `-Inf`) via `math.isnan` dan `math.isinf` (`PASS`).
  3. `test_timezone_normalization`: Validator `observed_at` menormalisasi seluruh timestamp (naive maupun aware seperti UTC+7) menjadi UTC eksplisit (`timezone.utc`) (`PASS`).
  4. `test_identical_timestamps_deterministic_tiebreak`: Snapshot dengan waktu observasi identik diurutkan secara deterministik dengan tie-breaker ID (`observed_at ASC, id ASC`), menjamin konsistensi pemilihan snapshot terbaru pada ringkasan (`PASS`).
  5. `test_cohort_conversion_rates_partial_unknown`: Rasio konversi agregat (CTR, Click-to-Order, CPO, CPC) dihitung secara ketat hanya pada kohort konten yang memiliki data pembilang dan penyebut lengkap, mencegah distorsi dari data metrik parsial (`PASS`).
  6. `test_all_metrics_unknown`: Penanganan kasus di mana seluruh metrik bernilai `None` tetap menghasilkan total `None` dan rasio `None` tanpa disulap menjadi 0 (`PASS`).
  7. `test_recorded_true_zeros`: Nilai 0 yang benar-benar tercatat (bukan `None`) dipertahankan secara akurat pada akumulasi total dan perhitungan rasio (`PASS`).
  8. `test_summary_date_filtering_excludes_out_of_range`: Kueri rentang tanggal mengabaikan snapshot di luar batas jendela observasi secara presisi dengan normalisasi string ISO UTC (`PASS`).
  9. `test_summary_period_delta`: Perhitungan delta pertumbuhan metrik (tayangan, klik, pesanan, komisi) antar-snapshot dalam jendela filter observasi berjalan akurat (`PASS`).
  10. `test_cli_performance_correct_smoke`: Pengujian smoke test subperintah CLI baru `performance correct` untuk pembaruan snapshot eksplisit dengan pencatatan audit log `action="correct_snapshot"` (`PASS`).
  11. `test_cli_duplicate_record_id_fails_without_audit_event`: Kegagalan pencatatan snapshot via CLI akibat duplikasi ID mengembalikan exit code 1 dan tidak memicu pembuatan audit event sukses palsu (`PASS`).
---

## 12. Verifikasi Phase 2.1.1: Performance Correction Auditability

- **Tanggal Eksekusi:** 2026-11-02
- **Lingkungan Pengujian:** `.venv\Scripts\python.exe` (Python 3.12.15) dengan standard library `unittest`
- **Perintah Eksekusi:**
  ```powershell
  $env:PYTHONPATH="src;."; & ".\.venv\Scripts\python.exe" -m unittest discover -s tests -p "test_*.py" -v
  ```
- **Exit Code:** `0`
- **Output Terminal:**
  ```text
  Ran 71 tests in 2.571s

  OK
  ```
- **Rincian Pengujian & Perbaikan Auditability (6 Test Cases Baru pada `tests/test_performance.py`):**
  1. `test_correction_saves_complete_before_and_after_states`: Koreksi snapshot performa secara transaksional menyimpan representasi lengkap seluruh nilai sebelum (`before`) dan sesudah (`after`) beserta alasan dan identitas snapshot pada payload event audit `note` (`PASS`).
  2. `test_audit_failure_rolls_back_snapshot_correction`: Jika pencatatan event audit gagal (disimulasikan dengan operational error pada SQLite), seluruh transaksi dibatalkan (`ROLLBACK`). Snapshot di database tetap pada kondisi sebelum koreksi dan tidak ditinggalkan tanpa jejak audit (`PASS`).
  3. `test_missing_snapshot_id_rejected_without_event`: Snapshot ID yang tidak ditemukan ditolak tegas (`ValueError`) dan tidak memicu pembuatan event audit sukses palsu (`PASS`).
  4. `test_invalid_correction_input_rejected_without_data_change`: Input koreksi yang tidak valid (misal nilai tayangan negatif) ditolak pada validasi model tanpa mengubah data snapshot dan tanpa menulis event audit (`PASS`).
  5. `test_sequential_repeated_corrections_auditable`: Koreksi berulang pada snapshot yang sama dapat ditelusuri secara berurutan (*sequential lineage*) melalui riwayat event audit `correct_snapshot` (`PASS`).
  6. `test_correction_and_audit_consistent_across_db_reopen`: Konsistensi data snapshot dan event audit terverifikasi tetap utuh setelah koneksi database ditutup dan dibuka kembali dari berkas SQLite (`PASS`).
---

## 13. Verifikasi Phase 2.2: Angle Ranker & Copywriting Advisor

- **Tanggal Eksekusi:** 2026-11-02
- **Lingkungan Pengujian:** `.venv\Scripts\python.exe` (Python 3.12.15) dengan standard library `unittest`
- **Perintah Eksekusi:**
  ```powershell
  $env:PYTHONPATH="src;."; & ".\.venv\Scripts\python.exe" -m unittest discover -s tests -p "test_*.py" -v
  ```
- **Exit Code:** `0`
- **Output Terminal:**
  ```text
  Ran 86 tests in 2.866s

  OK
  ```
- **Rincian Pengujian Baru (15 Test Cases pada `tests/test_angle_ranker.py`):**
  1. `test_aggregate_ctr_weighted_sum_clicks_and_views`: Perhitungan CTR agregat berbobot dari total clicks dan total views pada cohort yang valid (`(150 / 3000) * 100 = 5.0%`) (`PASS`).
  2. `test_aggregate_click_to_order_weighted_sum_orders_and_clicks`: Perhitungan Click-to-Order berbobot dari total orders dan total clicks pada cohort yang valid (`(15 / 150) * 100 = 10.0%`) (`PASS`).
  3. `test_none_metrics_preserved_never_defaulted_to_zero`: Preservasi nilai `None` pada metrik yang tidak diukur tanpa disulap menjadi 0 (`PASS`).
  4. `test_zero_denominator_yields_na_ratio`: Penyebut nol menghasilkan nilai rasio `None` (`N/A`) tanpa ZeroDivisionError atau persentase palsu (`PASS`).
  5. `test_cumulative_snapshots_not_counted_as_multiple_independent_contents`: Deduplikasi snapshot kumulatif hanya mengambil snapshot terbaru per konten independen; tidak terjadi penjumlahan ganda (`PASS`).
  6. `test_angle_without_performance_does_not_get_fake_rank`: Angle di repositori draf yang belum memiliki catatan performa dipisahkan dengan `rank=None` dan status `TIDAK ADA DATA`, mencegah ranking palsu (`PASS`).
  7. `test_unfound_draft_excluded_from_ranking`: Record performa dengan draft ID yang tidak ditemukan dikategorikan sebagai unmapped dan dieksklusikan dari ranking angle (`PASS`).
  8. `test_ambiguous_prompt_versions_excluded_from_ranking`: Draft ID yang memiliki versi prompt ganda (>1 versi) ditandai ambigu dan dieksklusikan dari ranking angle (`PASS`).
  9. `test_cross_platform_data_separated_by_default`: Data lintas platform ditolak bercampur secara default (`ValueError`) kecuali `allow_cross_platform=True` diaktifkan secara eksplisit (`PASS`).
  10. `test_platform_filter_works_correctly`: Parameter filter platform (`--platform`) mengisolasi evaluasi hanya pada platform target (`PASS`).
  11. `test_small_sample_labeled_limited_evidence`: Angle dengan sampel konten di bawah batas minimum (`< min_samples`) secara tegas diberi label `BUKTI TERBATAS` (`PASS`).
  12. `test_deterministic_ranking_for_identical_inputs`: Pemeringkatan bersifat 100% deterministik untuk dataset input yang sama (`PASS`).
  13. `test_copywriting_advisor_aligns_with_metrics`: Rekomendasi CopywritingAdvisor menyertakan observasi data yang persis merujuk metrik empiris sumber tanpa fabrikasi (`PASS`).
  14. `test_insufficient_data_recommends_exploration_not_winner`: Ketika seluruh data bersampel kecil, advisor merekomendasikan eksplorasi sampel tambahan dan menolak mengklaim angle pemenang (`PASS`).
  15. `test_cli_performance_angles_smoke`: Smoke test subperintah CLI `performance angles` berjalan sempurna dengan exit code 0 (`PASS`).

---

## 14. Phase 2.2.1 — Analytics & Advisor Integrity Fix (2026-11-02)

### Konteks & Audit Celah
Audit terhadap implementasi Phase 2.2 mengidentifikasi beberapa area integritas analitik dan penasihat naskah yang diperbaiki:
1. **Semantik None vs Nol:**
   - Sebelumnya, jika `click_to_order is None` atau `total_orders is None`, observasi advisor dan formatting tertentu berisiko menampilkan `0.00%` atau `0 pesanan`.
   - Diperbaiki: `None` secara tegas merepresentasikan metrik yang belum diukur/tidak diketahui (`N/A`). Nilai `orders == 0` yang benar-benar tercatat tetap dibedakan dari `orders is None`.
2. **Kelayakan Pemeringkatan (Ranking Eligibility):**
   - Sebelumnya, angle yang tidak memiliki nilai valid untuk metrik yang dipilih pada `--sort-by` tetap memperoleh peringkat (misal rank #1 untuk click_to_order meskipun `click_to_order is None`).
   - Diperbaiki: Angle yang memiliki data performa tetapi tidak memiliki metrik valid untuk kriteria pengurutan dipisahkan ke `unranked_missing_metric_angles` dengan `rank = None` dan catatan kualitas transparan.
   - Angle tanpa data performa sama sekali tetap berada di `unranked_angles` (`confidence_label="TIDAK ADA DATA"`).
3. **Integritas Bukti Advisor:**
   - CopywritingAdvisor dilarang mempromosikan angle sebagai pemenang konversi jika data konversi (`click_to_order` / `orders`) belum tersedia, meskipun jumlah konten memenuhi `min_samples`.
   - Rekomendasi eksplorasi data diaktifkan secara transparan bila data konversi belum lengkap.
4. **Pembersihan Asumsi Komersial:**
   - Menghapus asumsi klaim komersial yang belum terverifikasi dari template saran advisor (seperti "harga promo", "garansi resmi", "voucher toko", "keranjang kuning profil", "bio").
   - Saran disesuaikan menjadi draf hipotesis netral yang dapat diuji dan tetap berstatus DRAFT di bawah kontrol Review Gate manusia.
5. **Validasi Parameter:**
   - Parameter `min_samples <= 0` divalidasi dan ditolak secara deterministik pada modul `AngleRanker` dan CLI dengan pesan kesalahan ramah pengguna.

### Hasil Eksekusi Unit Test Komprehensif
- **Perintah Pengujian:**
  ```powershell
  $env:PYTHONPATH="src;."
  & ".\.venv\Scripts\python.exe" -m unittest discover -s tests -p "test_*.py" -v
  ```
- **Exit Code:** `0`
- **Output Terminal:**
  ```text
  Ran 94 tests in 4.953s

  OK
  ```
- **Rincian Pengujian Baru (8 Test Cases Tambahan pada `tests/test_angle_ranker.py`):**
  16. `test_click_to_order_none_not_displayed_as_zero_percent`: Memastikan `click_to_order=None` tidak pernah diformat atau ditampilkan sebagai `0.00%` (`PASS`).
  17. `test_orders_none_not_displayed_as_zero_orders`: Memastikan `orders=None` tidak pernah dinyatakan sebagai `0 pesanan` (`PASS`).
  18. `test_recorded_zero_orders_distinguished_from_none`: Memastikan kondisi `orders == 0` yang tercatat secara nyata dibedakan tegas dari `orders is None` (`PASS`).
  19. `test_angle_without_relevant_metric_for_sort_by_not_misleadingly_ranked`: Memastikan angle tanpa metrik relevan untuk kriteria pengurutan dipisahkan ke `unranked_missing_metric_angles` dengan `rank=None` (`PASS`).
  20. `test_ranking_correct_for_all_sort_by_options`: Memastikan pemeringkatan deterministik berjalan tepat untuk seluruh opsi sort (`click_to_order`, `ctr`, `views`, `orders`, `commission`) (`PASS`).
  21. `test_sufficient_content_samples_without_conversion_data_does_not_trigger_winner`: Memastikan sampel konten yang cukup tanpa data konversi tidak memicu klaim pemenang konversi (`PASS`).
  22. `test_advisor_suggestions_contain_no_unverified_commercial_assumptions`: Memastikan saran advisor bebas dari asumsi komersial tanpa sumber ("promo", "garansi", "voucher", "diskon", "keranjang kuning") (`PASS`).
23. `test_min_samples_zero_and_negative_rejected`: Memastikan nilai `--min-samples` nol dan negatif ditolak dengan pesan kesalahan (`PASS`).

---

## 15. Phase 2.2.2 — Security & Data Integrity Hardening (2026-11-03)

### Perubahan Terverifikasi Secara Statis
1. **Compliance fail-closed:** konfigurasi hilang, malformed, unreadable, atau berskema tidak valid menghasilkan `ComplianceReport(passed=False)` dengan finding `RULE-COMPLIANCE-CONFIG-01` ber-severity `ERROR`; pipeline berakhir `rejected` dan tidak dapat mencapai approval.
2. **Product URL validation:** hanya scheme HTTP/HTTPS dengan hostname valid yang diterima; whitespace/control character, credential, host malformed, dan port invalid ditolak tanpa network access.
3. **SQLite foreign keys:** `PRAGMA foreign_keys = ON` diaktifkan pada setiap koneksi file dan `:memory:`. Schema tidak diperluas.
4. **Exporter symlink protection:** target mentah diperiksa dengan `is_symlink()` sebelum `resolve()`, lalu containment tetap diverifikasi dengan `relative_to()`.

### Pemeriksaan Database Existing
- Default database `data/affiliate_factory.db` tidak ada.
- Direktori `data/` tidak ada.
- Tidak ada data existing yang dimigrasikan, dihapus, atau diubah.

### Targeted Regression Tests
- **Perintah harness:** `PYTHONPATH='src;.' ./.venv/Scripts/python.exe -m unittest -v tests.test_phase2_2_2_security tests.test_phase1_1_isolation tests.test_review_and_export`
- **Exit Code:** `0`
- **Hasil:** `Ran 36 tests in 1.762s`; `OK (skipped=4)`.
- **Skip:** empat test filesystem symlink tidak dapat membuat symlink pada Windows karena `WinError 1314` (privilege/Developer Mode); test tidak diganti mock.

### Full Test Suite
- **Perintah harness:** `PYTHONPATH='src;.' ./.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_*.py' -v`
- **Exit Code:** `0`
- **Hasil:** `Ran 105 tests in 4.119s`; `OK (skipped=4)`.
- **Catatan:** empat skip symlink sama dengan targeted run; seluruh test lain lulus.

---

## 16. Phase 2.2.3 — End-to-End Workflow Verification (2026-11-03)

### Cakupan Integration Test
- `tests/test_phase2_2_3_workflow.py` menjalankan CLI nyata dengan SQLite temporary dan filesystem temporary.
- Skenario sukses mencakup intake, prompt, import draft, claim review, compliance, human approval, export enam file, performance recording, correction, analytics, platform separation, ranking, dan repeatability.
- Skenario gagal mencakup compliance violation, approval/export bypass, unsupported claim, invalid product, invalid draft, serta pencegahan partial record.
- Tidak ada mock API eksternal atau klaim bahwa integrasi Shopee/AI eksternal berjalan.

### Hasil Integration Test
- **Perintah harness:** `PYTHONPATH='src;.' ./.venv/Scripts/python.exe -m unittest -v tests.test_phase2_2_3_workflow`
- **Exit Code:** `0`
- **Hasil:** `Ran 3 tests in 0.574s`; `OK`.

### Hasil Suite Terdampak
- **Exit Code:** `0`
- **Hasil:** `Ran 107 tests`; `OK (skipped=4)`.

### Full Test Suite
- **Perintah harness:** `PYTHONPATH='src;.' ./.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_*.py' -v`
- **Exit Code:** `0`
- **Hasil:** `Ran 108 tests in 5.000s`; `OK (skipped=4)`.
- **Skip:** empat test symlink filesystem tetap tidak dapat membuat symlink pada Windows karena `WinError 1314`; tidak diganti mock.
- **Database produksi:** tidak digunakan atau diubah. Seluruh integration test memakai database temporary.

---

## 17. Phase 3.1 — Agent Foundation (2026-11-03)

### Implementasi
- Menambahkan kontrak Pydantic untuk metadata agent, `AgentTask`, `AgentResult`, `AgentEvent`, status lifecycle, dan structured error.
- Menambahkan `BaseAgent`, `AgentRegistry`, `ExecutionContext`, event sinks in-process/SQLite, `AgentOrchestrator`, serta provider abstraction yang membungkus `LLMAdapter` tanpa mengklaim integrasi AI eksternal.
- Menambahkan tabel SQLite aditif `agent_tasks` dan `agent_events`; event memiliki FK ke task dan urutan insertion eksplisit.
- `src/affiliate_factory/orchestrator.py` tidak diganti dan workflow CLI existing tetap digunakan.

### Test Phase 3.1
- **Perintah harness:** `PYTHONPATH='src;.' ./.venv/Scripts/python.exe -m unittest -v tests.test_phase3_1_agents`
- **Exit Code:** `0`
- **Hasil:** `Ran 12 tests in 0.660s`; `OK`.
- **Cakupan:** registry, duplicate/unknown lookup, input/output validation, lifecycle transitions, success/failure execution, invalid output, event ordering/correlation, provider unavailable/timeout/error, context isolation, FK persistence, dan repeated task IDs.

### Suite Terdampak
- **Perintah harness:** `PYTHONPATH='src;.' ./.venv/Scripts/python.exe -m unittest -v tests.test_phase3_1_agents tests.test_core tests.test_phase1_mvp`
- **Exit Code:** `0`
- **Hasil:** `Ran 29 tests in 1.209s`; `OK`.

### Full Test Suite
- **Perintah harness:** `PYTHONPATH='src;.' ./.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_*.py' -v`
- **Exit Code:** `0`
- **Hasil:** `Ran 120 tests in 6.697s`; `OK (skipped=4)`.
- **Passed:** 116; **Failed:** 0; **Skipped:** 4.
- **Skip:** empat test symlink existing tetap `WinError 1314` karena privilege symlink Windows tidak tersedia.
- **Database produksi:** tidak digunakan atau diubah; seluruh test agent memakai SQLite temporary atau `:memory:`.

---

## 18. Phase 3.2 — Workflow Orchestrator & Multi-Agent Coordination (2026-11-03)

### Implementasi
- Menambahkan `WorkflowDefinition`, `WorkflowStep`, execution request/result, step result, lifecycle status, approval decision, dan structured workflow events.
- Menambahkan `WorkflowExecutor` sekuensial dengan dependency ordering, agent ID/capability resolution, input/output mapping, retry deterministik, duplicate execution protection, failure propagation, dan recovery.
- Menambahkan pause/resume human approval eksplisit; `APPROVE` melanjutkan, `REJECT` menghasilkan `rejected`; tidak ada automatic approval.
- Menambahkan persistence SQLite aditif untuk workflow executions, step state, dan workflow events dengan FK, explicit transactions, workflow definition snapshot, dan stale transition protection.
- Memperkuat Phase 3.1 task/event persistence agar default SQLite sink menyimpan task state dan lifecycle event dalam transaksi yang sama.

### Test Phase 3.2
- **Perintah harness:** `PYTHONPATH='src;.' ./.venv/Scripts/python.exe -m unittest -v tests.test_phase3_2_workflow`
- **Exit Code:** `0`
- **Hasil:** `Ran 8 tests`; `OK`.
- **Cakupan:** workflow definition/graph, capability resolution, sequential mapping, dependency blocking, unknown agent, retry transient, no retry validation, duplicate execution, human approval pause/resume/reject, durable events, persistence failure recovery, correlation IDs.

### Phase 3.1 + Phase 3.2 Targeted Suite
- **Perintah harness:** `PYTHONPATH='src;.' ./.venv/Scripts/python.exe -m unittest -v tests.test_phase3_1_agents tests.test_phase3_2_workflow`
- **Exit Code:** `0`
- **Hasil:** `Ran 21 tests in 2.128s`; `OK`.
- **Tambahan regression:** task creation rollback saat first event gagal dan workflow state/event recovery.

### Full Test Suite
- **Perintah harness:** `PYTHONPATH='src;.' ./.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_*.py' -v`
- **Exit Code:** `0`
- **Hasil:** `Ran 129 tests in 7.540s`; `OK (skipped=4)`.
- **Passed:** 125; **Failed:** 0; **Skipped:** 4.
- **Skip:** empat test symlink existing tetap `WinError 1314` karena privilege symlink Windows tidak tersedia.
- **Database produksi:** tidak digunakan atau diubah; workflow tests memakai SQLite temporary dan `:memory:`.

---

## 19. Phase 3.3 — Specialist Agents & Pre-flight Security Verification (2026-11-03)

### Pre-flight A1 — Windows Symlink Security
- **Inspeksi implementasi:** exporter memeriksa `raw_target_dir.is_symlink()` sebelum `resolve()` dan tetap melakukan containment validation.
- **Perintah targeted:** `PYTHONPATH='src;.' ./.venv/Scripts/python.exe -m unittest -v tests.test_phase1_1_isolation.TestPhase11Isolation.test_symlink_target_rejection tests.test_phase1_1_isolation.TestPhase11Isolation.test_symlink_target_to_outside_base_is_rejected tests.test_phase1_1_isolation.TestPhase11Isolation.test_broken_symlink_target_is_rejected tests.test_phase1_1_isolation.TestPhase11Isolation.test_parent_directory_symlink_is_resolved_before_target_check`
- **Exit Code:** `0`
- **Hasil:** `Ran 4 tests`; `OK (skipped=4)`.
- **Error aktual:** seluruh pembuatan symlink gagal dengan `WinError 1314: A required privilege is not held by the client`.
- **Pemeriksaan tambahan:** `fsutil behavior query SymlinkEvaluation` menunjukkan local-to-local symlink evaluation `ENABLED`.
- **Klasifikasi:** `ENVIRONMENTAL LIMITATION`; tidak ditemukan defect pada guard exporter; test tidak diganti mock.

### Pre-flight A2 — In-memory Event Sink Recovery
- **Perubahan aman:** failure pada injected in-memory event sink dipropagasikan sebagai `WorkflowPersistenceError`; state non-terminal tetap dapat dipulihkan.
- **Regression test:** `test_in_memory_event_sink_failure_preserves_non_terminal_recovery_without_duplicate_task`.
- **Guarantee:** SQLite state/event atomic per operasi; cross-storage atomicity tidak diklaim; recovery memakai persisted task result/ID untuk mencegah duplikasi.

### Specialist Tests
- **Perintah targeted:** `PYTHONPATH='src;.' ./.venv/Scripts/python.exe -m unittest -v tests.test_phase3_3_specialists`
- **Exit Code:** `0`
- **Hasil:** `Ran 8 tests in 1.019s`; `OK`.
- **Cakupan:** contracts, registry/capabilities, provenance, unsupported/missing claims, content writer research usage, fact classifications, compliance fail-closed, analytics missing metrics, full approval/export workflow, and manual/provider boundary.

### Impacted Regression Suite
- **Perintah harness:** `PYTHONPATH='src;.' ./.venv/Scripts/python.exe -m unittest -v tests.test_phase3_3_specialists tests.test_phase3_2_workflow tests.test_phase3_1_agents tests.test_phase2_2_2_security tests.test_phase2_2_3_workflow tests.test_review_and_export`
- **Exit Code:** `0`
- **Hasil:** `Ran 57 tests in 3.899s`; `OK`.

### Full Test Suite
- **Perintah harness:** `PYTHONPATH='src;.' ./.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_*.py' -v`
- **Exit Code:** `0`
- **Hasil:** `Ran 138 tests in 8.315s`; `OK (skipped=4)`.
- **Passed:** 134; **Failed:** 0; **Skipped:** 4.
- **Skip:** empat symlink filesystem tests karena `WinError 1314`.
- **Database produksi:** tidak digunakan atau diubah; specialist tests menggunakan SQLite temporary atau `:memory:`.


---

## 20. Phase A1 — Core Reliability: Combined Database Integrity & Workflow Reliability (2026-11-04)

### Implementasi & Perubahan
1. **Workstream 1 — Database Integrity & Concurrency Hardening:**
   - Enforce domain-correct composite Foreign Key constraints pada `claims` dan `compliance_reports` referencing `content_drafts(id, prompt_version) ON DELETE CASCADE`.
   - Implementasi deteksi dan preservasi orphan otomatis pada saat migrasi skema:
     - `compliance_reports` legacy atau berstatus orphan dideteksi dan dipreservasi dengan fallback stub draft dan product di `content_drafts` sehingga nol data hilang dan foreign key valid.
     - `claims` legacy yang tidak memiliki `prompt_version` diasosiasikan jika terdapat tepat 1 versi pada `content_drafts`. Jika 0 atau >1 versi, dibiarkan `NULL` (tidak difabrikasi). Orphan claim dengan `prompt_version` non-null dipreservasi dengan stub draft.
     - Menyediakan method inspeksi orphan: `Database.find_orphaned_compliance_reports()` dan `Database.find_orphaned_claims()`.
   - Penambahan index penunjang performa query:
     - `idx_events_run_id` pada `events (run_id)`
     - `idx_events_ref` pada `events (ref_id, module, action)`
     - `idx_content_drafts_product` pada `content_drafts (product_id)`
   - Konfirmasi percepatan query via `EXPLAIN QUERY PLAN` pada seluruh index baru.
   - Penguatan concurrency SQLite: journal mode `WAL`, `PRAGMA foreign_keys = ON`, dan `PRAGMA busy_timeout = 5000` aktif pada setiap koneksi.

2. **Workstream 2 — Agent & Workflow Reliability:**
   - Audit side-effect isolation pada seluruh 7 specialist agents: batasan persistensi terisolasi, retry deterministik dengan ID unik per attempt, dan tidak ada bypass review gate.
   - **Mandatory Export Idempotency:**
     - `export_content_pack()` diperbarui untuk memeriksa manifest dan hash SHA-256 berkas konten inti (`script.md`, `caption.txt`, `hashtags.txt`, `product_info.json`) saat direktori target sudah ada dan `overwrite=False`.
     - Ekspor ulang dengan konten identik tervalidasi sukses secara idempoten (membersihkan staging dan mengembalikan path tanpa error).
     - Ekspor dengan konten yang bertentangan atau berbeda memicu `ExportCollisionError` secara fail-closed.
     - Pembersihan direktori `.staging_*` yang terinterupsi secara otomatis.

### Hasil Pengujian Targeted Phase A1
- **Perintah harness:** `$env:PYTHONPATH="src;."; & ".\.venv\Scripts\python.exe" -m unittest -v tests/test_phase_a1_database.py`
- **Exit Code:** `0`
- **Hasil:** `Ran 10 tests in 0.814s`; `OK`.
- **Cakupan Pengujian:**
  1. `test_fk_valid_draft_reference_succeeds`: Valid reference ke `content_drafts(id, prompt_version)` berhasil disimpan (`PASS`).
  2. `test_fk_invalid_compliance_report_reference_rejected`: Reference compliance report ke draft yang tidak ada ditolak tegas oleh SQLite (`IntegrityError: FOREIGN KEY constraint failed`) (`PASS`).
  3. `test_fk_invalid_claim_reference_rejected`: Reference claim dengan explicit prompt_version ke draft yang tidak ada ditolak tegas (`IntegrityError: FOREIGN KEY constraint failed`) (`PASS`).
  4. `test_fk_cascade_deletion_on_draft_delete`: Menghapus draf induk otomatis menghapus report dan claim anak secara kaskade via `ON DELETE CASCADE` (`PASS`).
  5. `test_migration_idempotency`: Pemanggilan `init_schema()` berulang-ulang bersifat idempoten tanpa duplikasi data atau modifikasi skema yang merusak (`PASS`).
  6. `test_orphan_compliance_report_preservation_during_migration`: Report orphan legacy berhasil dipreservasi dengan stub draft dan product fallback, 0 pelanggaran FK (`PASS`).
  7. `test_orphan_inspection_helper_methods`: Helper `find_orphaned_compliance_reports` dan `find_orphaned_claims` mendeteksi anomali orphan dengan akurat (`PASS`).
  8. `test_query_plan_indexes_verified`: Percepatan query terbukti via `EXPLAIN QUERY PLAN` menggunakan `idx_events_run_id`, `idx_events_ref`, dan `idx_content_drafts_product` (`PASS`).
  9. `test_wal_mode_and_pragmas`: Verifikasi journal mode `wal`, busy timeout 5000 ms, dan foreign key active (`PASS`).
  10. `test_concurrent_read_write_under_wal`: 4 writer thread dan 4 reader thread berjalan simultan tanpa error kunci database (`PASS`).

### Full Test Suite
- **Perintah harness:** `$env:PYTHONPATH="src;."; & ".\.venv\Scripts\python.exe" -m unittest discover -s tests -p 'test_*.py' -v`
- **Exit Code:** `0`
- **Hasil:** `Ran 161 tests in 8.788s`; `OK (skipped=4)`.
- **Passed:** 157; **Failed:** 0; **Skipped:** 4.
- **Skip:** 4 test symlink filesystem existing tetap `WinError 1314` (privilege lingkungan Windows); tidak diganti mock.
- **Database produksi:** tidak digunakan atau diubah; seluruh pengujian memakai SQLite temporary dan `:memory:`.

---

## 21. Phase A2.1 & A2.1.1 — Core Data Layer & Corrective Patch (2026-11-05)

### Implementasi & Perbaikan (A2.1 & A2.1.1)
1. **TransactionScope & Connection Ownership (`src/affiliate_factory/db.py`):**
   - Transaksi terkelola (`self._owned = True`) menggunakan `BEGIN IMMEDIATE`, melakukan `commit()`, dan jika `commit()` gagal, menjalankan `rollback()` tanpa menutupi exception asli.
   - Koneksi caller-owned (`conn` disediakan oleh pemanggil) diverifikasi harus memiliki transaksi aktif (`conn.in_transaction == True`). TransactionScope TIDAK commit, TIDAK rollback, dan TIDAK menutup koneksi caller.
   - Dukungan koneksi `:memory:` ter-cache: saat commit gagal, status transaksi di-reset sehingga koneksi tetap dapat digunakan untuk transaksi berikutnya.
2. **Persistent Job Queue & Lease Fencing (`jobs`, `job_runs`, `approval_records`):**
   - Skema tabel `jobs`, `job_runs`, dan `approval_records` dengan foreign keys dan index penunjang `idx_jobs_status_priority_created` dan `idx_jobs_lease_expires`.
   - Lifecycle job: `submit_job`, `claim_next_job`, `heartbeat_job`, `complete_job`, `fail_job`.
   - Fencing ketat: `heartbeat_job`, `complete_job`, dan `fail_job` memvalidasi kelima predikat:
     `job_id = ? AND worker_id = ? AND lease_token = ? AND status = 'running' AND lease_expires_at > ?`.
     Worker lambat / zombie dengan lease kedaluwarsa ditolak tegas dan tidak dapat memodifikasi status job atau job_runs.
3. **Database Migration Integrity & Foreign Key Check:**
   - `Database.init_schema()` menjalankan `PRAGMA foreign_key_check` setelah migrasi dan pembuatan tabel.
   - Jika ditemukan pelanggaran foreign key, proses dibatalkan dengan `RuntimeError` deskriptif yang mencantumkan tabel dan rowid pelanggar.
4. **Safe Database Backup (`create_safe_database_backup`):**
   - Backup online via SQLite `backup` API aman pada mode WAL tanpa mengunci pembaca/penulis.
   - Validasi `PRAGMA integrity_check == 'ok'` pada berkas staging sebelum rename/swap atomik ke target.
   - Kegagalan backup membersihkan berkas sementara tanpa merusak berkas backup valid yang sudah ada.

### Hasil Pengujian Targeted Phase A2.1 / A2.1.1
- **Perintah targeted:** `$env:PYTHONPATH="src"; .\.venv\Scripts\python.exe -m unittest tests.test_phase_a2_db_transactions`
- **Exit Code:** `0`
- **Hasil:** `Ran 28 tests in 2.133s`; `OK`.
- **Cakupan Pengujian:**
  1. `TestTransactionScope` (10 tes):
     - Self-managed transaction commit & rollback on exception (`PASS`).
     - Nested self-managed transaction blocks commit atomically on outermost scope (`PASS`).
     - Caller-owned transaction preservation: caller commits, caller rolls back, inner exception does not abort caller transaction (`PASS`).
     - Rejection when caller connection is not in transaction (`PASS`).
     - `:memory:` commit failure recovery and reuse (`PASS`).
  2. `TestPersistentJobQueue` (14 tes):
     - Job submission (queued status, payload, priority) & idempotency key deduplication (`PASS`).
     - Claiming priority order & FIFO tie-breaking (`PASS`).
     - Supported job types filtering (`PASS`).
     - Lease duration, worker assignment, and job_run attempt tracking (`PASS`).
     - Heartbeat extension, invalid worker/token rejection, and expired lease rejection (`PASS`).
     - Completion recording result_payload and lease expiry fencing (`PASS`).
     - Fail job recording error_message and lease expiry fencing (`PASS`).
     - Stale worker rejection after reclaim by second worker (`PASS`).
     - Cancellation requested flag preservation (`PASS`).
  3. `TestWindowsMultiprocessingConcurrency` (1 tes):
     - Dua proses Windows terpisah (`multiprocessing.Process` spawn mode) bersaing mengklaim 1 job: tepat 1 pemenang dan 1 pecundang tanpa double-claim (`PASS`).
  4. `TestSafeDatabaseBackup` (3 tes):
     - Safe online backup pada active WAL mode dengan `PRAGMA integrity_check` lulus (`PASS`).
     - Module-level backup helper (`PASS`).
     - Backup failure tidak merusak backup valid yang sudah ada dan membersihkan staging temp files (`PASS`).

### Full Test Suite Regression
- **Perintah harness:** `$env:PYTHONPATH="src"; .\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"`
- **Exit Code:** `0`
- **Hasil:** `Ran 189 tests in 11.806s`; `OK (skipped=4)`.
- **Passed:** 185; **Failed:** 0; **Skipped:** 4 (symlink filesystem tests skip karena `WinError 1314` privilege Windows).
- **Integritas Git:** HEAD tetap `6cdf8fa48394a93b374586675beb7bcfaff2186e`. Tidak ada commit, push, atau staging.
