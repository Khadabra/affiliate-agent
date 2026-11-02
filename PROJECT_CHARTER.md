# PROJECT CHARTER: AI AFFILIATE CONTENT FACTORY

| Metadata | Value |
| :--- | :--- |
| **Project Name** | AI Affiliate Content Factory |
| **Initial Platform Target** | Shopee Affiliate Indonesia (Status: `NOT VERIFIED` / Candidate under verification) |
| **System Lead** | Senior AI Systems Architect, Python Engineer & Auditor |
| **Runtime Environment** | Windows 11 (x86_64), RTX 4050 6GB Laptop GPU, Local-First Architecture |
| **Current Governance Phase** | Phase 0A — Project Governance & Repository Registry |
| **Status** | PROPOSAL (Awaiting User Formal Approval) |

---

## 1. Project Background & Vision

Sistem ini dirancang untuk membangun pabrik konten afiliasi (*AI Affiliate Content Factory*) otomatis dan semi-otomatis yang dikendalikan oleh pemilik akun sendiri. Sistem ini bertujuan untuk menghasilkan konten promosi (naskah video, audio voiceover, visualisasi, dan video pendek siap upload) berbasis data produk afiliasi yang terukur, berkonversi tinggi, dan hemat biaya.

**Prinsip Inti:**
> Sistem ini dibangun untuk **kegunaan nyata (real utility)** — memproduksi, menguji, dan melacak performa konten affiliate sebenarnya — bukan sekadar demo agen AI atau dashboard visual yang tampak canggih tanpa hasil fungsional.

---

## 2. Core Constraints & Ground Rules

1. **Strict Human-in-the-Loop (HITL) Gate:**
   - Tidak ada konten yang dipublikasikan atau diunggah ke platform publik tanpa persetujuan manusia secara eksplisit di dashboard/terminal.
   - Status: `VERIFIED` (Aturan mutlak).
2. **Platform Terms of Service & Anti-Scraping Compliance:**
   - Dilarang membypass login, CAPTCHA, Cloudflare/Akamai, atau bot-mitigation Shopee.
   - Data produk wajib bersumber dari **API resmi (Shopee Open Platform / Affiliate Open API)** atau **input terkurasi manual/file import (CSV/JSON/URL resmi)**.
   - Status: `VERIFIED` (Aturan mutlak pencegah suspend akun/IP block).
3. **Hardware & Cost Efficiency:**
   - Target runtime lokal: Windows 11 dengan NVIDIA GeForce RTX 4050 Laptop GPU (VRAM 6GB terverifikasi).
   - Menghindari pemborosan token LLM dengan kontrak data ketat (Pydantic), specialized prompt, caching, dan local processing (FFmpeg, local/lightweight TTS).
   - Menolak tumpang tindih framework (misal: dilarang menjalankan CrewAI + LangGraph bersamaan).
4. **Security & Credential Zero-Leakage:**
   - Dilarang keras menyimpan API keys, token, atau kredensial afiliasi di source code, repository git, log output, atau screenshot.
   - Seluruh secret dikelola via local environment variables (`.env` yang di-ignore oleh Git) atau OS credential manager.

---

## 3. Classification Taxonomy

Setiap klaim, komponen, dan asumsi dalam proyek ini wajib diklasifikasikan dengan label berikut:

- `VERIFIED`: Telah diuji dan dibuktikan secara empiris di lingkungan lokal aktual (misal: perintah terminal berhasil, file ada di disk).
- `ASSUMPTION`: Hipotesis atau ekspektasi yang belum diuji di lingkungan lokal.
- `PROPOSAL`: Rencana desain atau rekomendasi yang menunggu persetujuan arsitektur.
- `NOT VERIFIED`: Pernyataan atau status pihak ketiga yang belum divalidasi kebenarannya.

---

## 4. Definition of Success (Kriteria Keberhasilan)

### MVP Success Criteria (Phase 1):
1. **Pipeline Scripting & Contract:** Berhasil menerima 1 URL/ID produk terkurasi dan menghasilkan 3 variasi naskah video TikTok/Reels/Shorts berbahasa Indonesia berbasis persona affiliate dalam format JSON tervalidasi Pydantic.
2. **Audio & Media Assembly:** Berhasil mengonversi naskah ke voiceover jernih (Edge TTS / Whisper) dan merender 1 video vertikal 1080x1920 (9:16) berdurasi 15-30 detik menggunakan FFmpeg lokal dalam waktu < 60 detik.
3. **Approval Gate:** Workflow berhenti pada status `WAITING_APPROVAL` dan mencatat draft serta asset ke SQLite lokal. Manusia dapat melakukan approve/reject melalui antarmuka minimal.
4. **Reproducibility:** Seluruh pipeline dapat dijalankan di Windows via single virtual environment (`uv` / Python 3.12) tanpa error missing DLL atau CUDA OOM.

---

## 5. Scope Boundaries

| In Scope (Fase Awal - MVP) | Out of Scope (Ditunda ke Fase Lanjutan) |
| :--- | :--- |
| Naskah produk terstruktur (copywriting, hook, CTA) | Auto-posting/auto-upload tanpa review manusia |
| Audio generation via zero-cost / local TTS | Generasi video AI difusi berat (Sora / Wan / ComfyUI FLUX lokal) |
| Stitching aset video produk + voiceover via FFmpeg | Multiple concurrent heavy models yang melebihi VRAM 6GB |
| Penyimpanan state dan antrean di SQLite lokal | Scraping agresif / headless browser bypass CAPTCHA |
| Human approval UI / CLI gate | Multi-tenant SaaS / cloud multi-user |

