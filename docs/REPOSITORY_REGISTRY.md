# REPOSITORY REGISTRY: EVALUASI & AUDIT DEPENDENSI

Dokumen ini memuat seluruh inventaris repositori dan pustaka yang dievaluasi untuk **AI Affiliate Content Factory**.

> **Taksonomi Status:**
> - **Status Audit:** `AUDITED` (telah diperiksa kode/metadata), `AUDITING` (sedang dianalisis), `UNREVIEWED` (belum diperiksa), `NOT_VERIFIED` (belum ada bukti).
> - **Status Persetujuan Pengguna:** `PROPOSED` (diajukan, menunggu persetujuan), `APPROVED_BY_USER` (disetujui pengguna untuk fase aktif), `NOT_SELECTED` (tidak dipilih/ditolak), `DEFERRED` (ditunda ke fase lanjutan), `REFERENCE_ONLY` (hanya referensi desain/konsep, tidak dipasang).
> - **Status Implementasi:** `INSTALLED_AND_TESTED` (terpasang & lolos uji lokal), `NOT_INSTALLED` (belum terpasang di venv), `N/A` (tidak relevan dipasang).
> - **Bukti Windows:** `TESTED` (sudah diuji langsung via terminal Windows), `METADATA_ONLY` (hanya verifikasi dokumentasi/PyPI), `NOT_TESTED` (belum diuji di lingkungan Windows lokal).

---

## 1. Inventaris & Matriks Status Repositori

| No | Repositori / Komponen | Peran / Kategori | Status Audit | Status Persetujuan | Status Implementasi | Bukti Windows | Lisensi Proyek |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `ComposioHQ/awesome-claude-skills` | Prompting & Skill Catalog | `AUDITED` | `REFERENCE_ONLY` | `N/A` | `METADATA_ONLY` | Open Source / Curated |
| 2 | `mdskills.ai` | Skills Catalog Reference | `AUDITED` | `REFERENCE_ONLY` | `N/A` | `METADATA_ONLY` | Curated Skills |
| 3 | `humaedihume/kantor-agent` | UI Visual Monitoring (Pixel Art) | `AUDITED` | `REFERENCE_ONLY` | `N/A` (Cloned Read-Only) | `TESTED` (Code Inspected) | MIT |
| 4 | `langchain-ai/langgraph` | Workflow State Orchestrator | `AUDITING` | `DEFERRED` | `NOT_INSTALLED` | `METADATA_ONLY` | MIT |
| 5 | `graphify` | Codebase Knowledge Graph | `UNREVIEWED` | `DEFERRED` | `NOT_INSTALLED` | `NOT_TESTED` | Open Source |
| 6 | `FFmpeg/FFmpeg` | Media Processing & Transcoding | `AUDITED` | `DEFERRED` (Slot Disediakan) | `INSTALLED_AND_TESTED` (`libx264`) | `TESTED` | GPL v3.0 (Build Gyan.dev) |
| 7 | `SYSTRAN/faster-whisper` | Local Speech-to-Text | `AUDITED` | `DEFERRED` | `NOT_INSTALLED` | `METADATA_ONLY` | MIT |
| 8 | `rany2/edge-tts` | Indonesian Voiceover Synthesis | `AUDITED` | `DEFERRED` | `NOT_INSTALLED` | `NOT_TESTED` | LGPL v3.0 |
| 9 | `unclecode/crawl4ai` | Web Crawler & Scraping | `AUDITED` | `DEFERRED` | `NOT_INSTALLED` | `METADATA_ONLY` | Apache-2.0 |
| 10 | `comfyanonymous/ComfyUI` | AI Image/Visual Generation | `AUDITED` | `DEFERRED` | `NOT_INSTALLED` | `METADATA_ONLY` | GPL v3.0 |
| 11 | `pydantic/pydantic` | Data Validation & Contracts | `AUDITED` | `APPROVED_BY_USER` (M1) | `INSTALLED_AND_TESTED` (v2.14.2) | `TESTED` | MIT |

### Alternatif Tercatat (Non-Primary)

| Komponen Alternatif | Kategori | Status Audit | Status Persetujuan | Alasan Utama |
| :--- | :--- | :--- | :--- | :--- |
| `crewAIInc/crewAI` | Orchestration | `AUDITED` | `NOT_SELECTED` | Abstraksi berlebihan, duplikasi peran dengan pipeline terstruktur, risiko loop token tak terkontrol. |
| `google/adk-python` | Google AI Workflow | `UNREVIEWED` | `REFERENCE_ONLY` | Disimpan sebagai referensi jika ada kebutuhan integrasi cloud ekosistem Google. |
| `agno-agi/agno` | Agent Framework | `UNREVIEWED` | `NOT_SELECTED` | Duplikasi framework agen; tidak diperlukan untuk deterministic workflow. |
| `n8n-io/n8n` | Workflow Automation | `AUDITED` | `REFERENCE_ONLY` | Membutuhkan runtime Node.js/Docker terpisah; menambah beban operasional lokal. |
| `MoviePy` | Video Editing Wrapper | `AUDITED` | `NOT_SELECTED` | Wrapper Python lambat dan rawan memory leak di Windows; digantikan FFmpeg CLI native. |

---

## 2. Audit Detail Repositori & Protokol Intake

### A. ComposioHQ/awesome-claude-skills & mdskills.ai
- **Peran:** Referensi pembuatan prompt copywriting, struktur hook, dan TDD skill.
- **Status:** `REFERENCE_ONLY`.
- **Daftar Periksa Intake Skill Baru (Wajib Diikuti Sebelum Mengadopsi Skill):**
  1. Baca seluruh isi file `SKILL.md` dan setiap skrip yang disertakan.
  2. Tolak keras skrip yang berisi perintah berbahaya seperti `curl | sh` atau pemanggilan akses jaringan/telemetri yang tidak dijelaskan tujuannya.
  3. Uji coba satu skill pada branch Git terpisah terlebih dahulu untuk memverifikasi perilakunya.
  4. Catat nama skill, tanggal adopsi, dan lisensinya di dokumen ini.

---

### B. humaedihume/kantor-agent
- **URL:** https://github.com/humaedihume/kantor-agent
- **Status:** `REFERENCE_ONLY` (Telah di-clone secara *read-only* ke `tmp/reference/kantor-agent`).
- **Temuan Kode Sumber:**
  - `skills/kantor-agent/runtime/lib/node/office.mjs` mengekspos endpoint `/kerja/api/state` berbasis data transkrip Claude Code (`~/.claude/projects/`).
  - Tidak kompatibel langsung dengan Antigravity IDE atau aplikasi Python tanpa adapter data.
  - Detail studi kelayakan lengkap didokumentasikan di `docs/VIZ_FEASIBILITY.md`.
- **Rekomendasi:** Tunda visualisasi 3D ke fase lanjutan; fokuskan saat ini pada modul deterministik M1 & M2.

---

### C. langchain-ai/langgraph & Graphify
- **Status:** `DEFERRED`.
- **Kriteria Evaluasi Ulang:**
  - *LangGraph:* Hanya dipertimbangkan jika di masa depan muncul kebutuhan percabangan alur kerja dinamis, persistence multi-step kompleks, atau resumption yang tidak tertangani oleh state machine sekuensial sederhana.
  - *Graphify:* Hanya dipertimbangkan jika basis kode proyek telah berkembang melebihi ~50 file atau asisten AI sering gagal menemukan konteks kode yang relevan.

---

### D. Modul Media Video & Audio (FFmpeg, faster-whisper, edge-tts, crawl4ai, ComfyUI)
- **Status:** `DEFERRED` (Slot Folder Disediakan).
- **Implementasi Slot:** Slot kontrak kosong telah disediakan di `src/affiliate_factory/video/stub.py` (`VideoRenderRequest`, `VideoRenderResult`). Tidak ada modul rendering atau sintesis audio yang diimplementasikan pada fase ini.
- **Baseline Encoder:** Jika fase video diaktifkan di masa depan, baseline encoder adalah `libx264` (CPU) karena `h264_nvenc` membutuhkan driver NVIDIA 610.00+.

---

### E. pydantic/pydantic
- **Status:** `APPROVED_BY_USER` (M1) / `INSTALLED_AND_TESTED`.
- **Bukti Windows:** `TESTED`.
  - Pydantic v2.14.2 terpasang di `.venv` (Python 3.12.15).
  - Digunakan sebagai fondasi kontrak data seluruh entitas sistem di `src/affiliate_factory/models.py`.
