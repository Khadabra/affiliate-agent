# REPOSITORY REGISTRY: EVALUASI & AUDIT DEPENDENSI

Dokumen ini memuat seluruh inventaris repositori dan pustaka yang dievaluasi untuk **AI Affiliate Content Factory**.

> **Taksonomi Status:**
> - **Status Audit:** `AUDITED` (telah diperiksa kode/metadata), `AUDITING` (sedang dianalisis), `UNREVIEWED` (belum diperiksa), `NOT_VERIFIED` (belum ada bukti).
> - **Status Persetujuan Pengguna:** `PROPOSED` (diajukan, menunggu persetujuan), `NOT_SELECTED` (tidak dipilih/ditolak), `DEFERRED` (ditunda ke fase lanjutan), `REFERENCE_ONLY` (hanya referensi desain/konsep, tidak dipasang).
> - **Status Implementasi:** `INSTALLED_AND_TESTED` (terpasang & lolos uji lokal), `NOT_INSTALLED` (belum terpasang di venv), `N/A` (tidak relevan dipasang).
> - **Bukti Windows:** `TESTED` (sudah diuji langsung via terminal Windows), `METADATA_ONLY` (hanya verifikasi dokumentasi/PyPI), `NOT_TESTED` (belum diuji di lingkungan Windows lokal).

---

## 1. Inventaris & Matriks Status Repositori

| No | Repositori / Komponen | Peran / Kategori | Status Audit | Status Persetujuan | Status Implementasi | Bukti Windows | Lisensi Proyek |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `ComposioHQ/awesome-claude-skills` | Prompting & Skill Catalog | `AUDITED` | `REFERENCE_ONLY` | `N/A` | `METADATA_ONLY` | Open Source / Curated |
| 2 | `humaedihume/kantor-agent` | UI Visual Monitoring (Pixel Art) | `AUDITED` | `REFERENCE_ONLY` | `N/A` | `METADATA_ONLY` | Open Source (Community) |
| 3 | `langchain-ai/langgraph` | Workflow State Orchestrator | `AUDITING` | `DEFERRED` (MVP) / `PROPOSED` | `NOT_INSTALLED` | `METADATA_ONLY` | MIT |
| 4 | `FFmpeg/FFmpeg` | Media Processing & Transcoding | `AUDITED` | `PROPOSED` | `INSTALLED_AND_TESTED` (`libx264`) | `TESTED` | GPL v3.0 (Build Gyan.dev) |
| 5 | `SYSTRAN/faster-whisper` | Local Speech-to-Text | `AUDITED` | `DEFERRED` | `NOT_INSTALLED` | `METADATA_ONLY` | MIT |
| 6 | `rany2/edge-tts` | Indonesian Voiceover Synthesis | `AUDITED` | `DEFERRED` (MVP) / `PROPOSED` | `NOT_INSTALLED` | `NOT_TESTED` | LGPL v3.0 |
| 7 | `unclecode/crawl4ai` | Web Crawler & Scraping | `AUDITED` | `DEFERRED` | `NOT_INSTALLED` | `METADATA_ONLY` | Apache-2.0 |
| 8 | `comfyanonymous/ComfyUI` | AI Image/Visual Generation | `AUDITED` | `DEFERRED` | `NOT_INSTALLED` | `METADATA_ONLY` | GPL v3.0 |
| 9 | `pydantic/pydantic` | Data Validation & Contracts | `AUDITED` | `PROPOSED` | `INSTALLED_AND_TESTED` (v2.14.2) | `TESTED` | MIT |

### Alternatif Tercatat (Non-Primary)

| Komponen Alternatif | Kategori | Status Audit | Status Persetujuan | Alasan Utama |
| :--- | :--- | :--- | :--- | :--- |
| `crewAIInc/crewAI` | Orchestration | `AUDITED` | `NOT_SELECTED` | Abstraksi berlebihan, duplikasi peran dengan pipeline terstruktur, risiko loop token tak terkontrol. |
| `google/adk-python` | Google AI Workflow | `UNREVIEWED` | `REFERENCE_ONLY` | Disimpan sebagai referensi jika ada kebutuhan integrasi cloud ekosistem Google. |
| `agno-agi/agno` | Agent Framework | `UNREVIEWED` | `NOT_SELECTED` | Duplikasi framework agen; tidak diperlukan untuk deterministic workflow. |
| `n8n-io/n8n` | Workflow Automation | `AUDITED` | `REFERENCE_ONLY` | Membutuhkan runtime Node.js/Docker terpisah; menambah beban operasional lokal. |
| `MoviePy` | Video Editing Wrapper | `AUDITED` | `NOT_SELECTED` | Wrapper Python lambat dan rawan memory leak di Windows; digantikan FFmpeg CLI native. |

---

## 2. Audit Detail Repositori Utama

### A. ComposioHQ/awesome-claude-skills
- **URL:** https://github.com/ComposioHQ/awesome-claude-skills
- **Pemeriksaan:** 2026-11-02 via dokumentasi repository.
- **Fungsi Diinginkan:** Referensi perancangan prompt copywriting, hook formulasi, dan TDD skill.
- **Status Audit / Persetujuan:** `AUDITED` / `REFERENCE_ONLY`.
- **Bukti & Temuan Windows:** `METADATA_ONLY`.
  - Format skill Claude menggunakan struktur frontmatter dan instruksi yang diasumsikan berjalan pada Claude Code CLI atau Composio tools.
  - Kompatibilitas format skill Claude dengan Antigravity berstatus **`ASSUMPTION`** sampai diuji untuk skill spesifik tertentu. Antigravity memiliki spesifikasi penemuan skill sendiri di `.agents/skills/<name>/SKILL.md`.
- **Rekomendasi:** Tidak mengkloning atau memasang repo ini. Gunakan hanya sebagai inspirasi konten prompt teks copywriting yang diadaptasi manual.

---

### B. humaedihume/kantor-agent
- **URL:** https://github.com/humaedihume/kantor-agent
- **Pemeriksaan:** 2026-11-02 via web repository metadata.
- **Fungsi Diinginkan:** Inspirasi tampilan dashboard visual pemantauan status agen bergaya pixel art.
- **Status Audit / Persetujuan:** `AUDITED` / `REFERENCE_ONLY`.
- **Bukti & Temuan Windows:** `METADATA_ONLY`.
  - Repo ini adalah plugin khusus untuk **Claude Code** yang membaca log sesi Claude Code (`~/.cache/kantor-agent/`).
  - Repo ini tidak memiliki mekanisme bawaan untuk memantau runtime Antigravity maupun aplikasi Python kustom.
- **Rekomendasi:** Murni referensi UI/UX. Dashboard monitoring aplikasi kita akan membaca event nyata dari database SQLite lokal.

---

### C. langchain-ai/langgraph
- **URL:** https://github.com/langchain-ai/langgraph
- **Pemeriksaan:** 2026-11-02 via PyPI & GitHub metadata.
- **Fungsi Diinginkan:** Orkestrasi alur kerja berbasis graf, state machine, branching, retry, dan checkpointing ke SQLite.
- **Status Audit / Persetujuan:** `AUDITING` / `DEFERRED` untuk MVP awal (Diusulkan untuk dievaluasi pada fase lanjutan jika state machine Python sederhana tidak mencukupi).
- **Bukti & Temuan Windows:** `METADATA_ONLY`.
  - Membutuhkan Python >=3.10. Dependensi: `langchain-core`, `langgraph-checkpoint`, `pydantic`.
- **Rekomendasi:** Untuk MVP Phase 1 yang disederhanakan (draft teks manual & approval), alur dapat dijalankan via fungsi Python sekuensial deterministik tanpa overhead dependensi `langchain-core`.

---

### D. FFmpeg / FFmpeg (Gyan.dev Build)
- **URL:** https://github.com/FFmpeg/FFmpeg | https://www.gyan.dev/ffmpeg/builds/
- **Pemeriksaan:** 2026-11-02 via terminal Windows (`ffmpeg -version`, `ffmpeg -L`, smoke test render).
- **Fungsi Diinginkan:** Pemotongan video, penggabungan audio, hardcode subtitle, dan ekspor format 9:16 (1080x1920).
- **Status Audit / Persetujuan / Implementasi:** `AUDITED` / `PROPOSED` / `INSTALLED_AND_TESTED`.
- **Bukti Windows:** `TESTED`.
  - **Lisensi Build Terpasang:** GPL v3.0 (karena build Gyan.dev mengaktifkan `--enable-gpl --enable-version3` dengan pustaka seperti x264/x265).
  - **Uji `libx264` (CPU Encoding):** `PASS`. Berhasil merender video sintetis 5 detik 1080x1920 dalam 1,64 detik (`exit code 0`). File MP4 terverifikasi via `ffprobe`.
  - **Uji `h264_nvenc` (GPU Encoding):** `FAILED`. Gagal dengan error `exit code -40 (Function not implemented)`. Driver NVIDIA yang terpasang pada host adalah `581.32` (NVENC API 13.0), sedangkan FFmpeg 9.0.2 memerlukan driver `610.00` atau lebih baru (NVENC API 13.1).
  - **Kesimpulan:** FFmpeg siap digunakan dengan encoder stabil `libx264`. NVENC tidak dapat digunakan tanpa pembaruan driver GPU (dan sesuai aturan, tidak ada pembaruan driver dilakukan).

---

### E. SYSTRAN/faster-whisper
- **URL:** https://github.com/SYSTRAN/faster-whisper
- **Pemeriksaan:** 2026-11-02 via PyPI metadata.
- **Fungsi Diinginkan:** Transkripsi audio lokal ke teks dan generasi subtitle (SRT/VTT).
- **Status Audit / Persetujuan:** `AUDITED` / `DEFERRED`.
- **Bukti Windows:** `METADATA_ONLY`.
  - Lisensi: MIT. Dependensi: `ctranslate2`, `tokenizers`, `onnxruntime`, `av`.
  - Membutuhkan Python >=3.9. Prebuilt wheel CTranslate2 sering memiliki jeda rilis untuk versi Python sangat baru.
- **Rekomendasi:** Ditunda ke fase lanjutan. Pada MVP, naskah teks diproduksi duluan oleh sistem, sehingga subtitle dihasilkan langsung dari teks naskah tanpa perlu transkripsi balik audio.

---

### F. rany2/edge-tts
- **URL:** https://github.com/rany2/edge-tts
- **Pemeriksaan:** 2026-11-02 via PyPI metadata.
- **Fungsi Diinginkan:** Sintesis suara (TTS) bahasa Indonesia (`id-ID-ArdiNeural`, `id-ID-GadisNeural`) tanpa biaya API.
- **Status Audit / Persetujuan:** `AUDITED` / `DEFERRED` (Ditunda pada revisi MVP Phase 1).
- **Bukti Windows:** `NOT_TESTED`.
  - Lisensi: LGPL v3.0. Menggunakan endpoint websocket Microsoft Edge Read Aloud yang bersifat tidak resmi (tanpa jaminan SLA).
- **Rekomendasi:** Ditunda sampai MVP draft teks dan evaluasi manual berjalan stabil.

---

### G. unclecode/crawl4ai
- **URL:** https://github.com/unclecode/crawl4ai
- **Pemeriksaan:** 2026-11-02 via PyPI metadata & web audit.
- **Fungsi Diinginkan:** Pengambilan informasi produk publik secara otomatis.
- **Status Audit / Persetujuan:** `AUDITED` / `DEFERRED`.
- **Bukti Windows:** `METADATA_ONLY`.
  - Lisensi: Apache-2.0. Membutuhkan Playwright dan browser binaries.
  - Risiko Kritis: Shopee menerapkan sistem proteksi bot (Akamai/CAPTCHA). Scraping HTML langsung berisiko banned IP dan pelanggaran ToS.
- **Rekomendasi:** Ditunda. Input produk pada MVP wajib menggunakan kurasi manual terstruktur atau Shopee Affiliate Open API resmi.

---

### H. comfyanonymous/ComfyUI
- **URL:** https://github.com/comfyanonymous/ComfyUI
- **Pemeriksaan:** 2026-11-02 via GitHub metadata.
- **Fungsi Diinginkan:** Generasi visual produk dengan model difusi lokal.
- **Status Audit / Persetujuan:** `AUDITED` / `DEFERRED`.
- **Bukti Windows:** `METADATA_ONLY`.
  - Lisensi: GPL v3.0. Membutuhkan PyTorch dengan CUDA dan checkpoint model besar (4GB - 16GB).
  - Batasan VRAM: GPU host adalah RTX 4050 6GB. Menjalankan difusi SDXL/Flux lokal sangat rentan Out-Of-Memory.
- **Rekomendasi:** Ditunda ke fase riset lanjutan.

---

### I. pydantic/pydantic
- **URL:** https://github.com/pydantic/pydantic
- **Pemeriksaan:** 2026-11-02 via PyPI & smoke test lokal di `.venv`.
- **Fungsi Diinginkan:** Validasi kontrak data antar-tahap (Input Produk, Naskah, Hasil Evaluasi).
- **Status Audit / Persetujuan / Implementasi:** `AUDITED` / `PROPOSED` / `INSTALLED_AND_TESTED`.
- **Bukti Windows:** `TESTED`.
  - Lisensi: MIT.
  - Berhasil dipasang di `.venv` (Python 3.12.15): `pydantic==2.14.2`, `pydantic-core==2.50.2`.
  - Smoke test model tervalidasi dengan `exit code 0` dan output tervalidasi.
- **Rekomendasi:** Disetujui secara teknis untuk diajukan sebagai basis kontrak data proyek.
