# AGENT CONTRACTS & SPECIALIST SPECIFICATIONS

Dokumen ini mendefinisikan tanggung jawab, batas kewenangan (*authority limits*), skema input/output (kontrak data), dan aturan operasional (*handoff rules*) untuk setiap spesialis dalam sistem.

---

## Prinsip Desain Agen
1. **Tidak Ada Agen Berlebihan (Zero Bloat):** Agen hanya dibuat jika memiliki tanggung jawab fungsional yang berbeda secara nyata.
2. **Strict Typed Contracts:** Pertukaran data antar-spesialis wajib menggunakan schema Pydantic. Dilarang melempar string bebas tanpa struktur.
3. **Fail-Fast Boundary:** Jika output sebuah modul gagal divalidasi skemanya, eksekusi berhenti dan meminta retry/fallback sebelum mencapai tahap rendering media.

---

## 1. Product Research & Intake Specialist

- **Tanggung Jawab:**
  - Menerima dan memvalidasi informasi produk afiliasi (nama, kategori, harga, link komisi afiliasi, keunggulan/USP, dan daftar aset media).
  - Mengekstrak sudut pandang penjualan (*selling angle*) dan masalah target audiens (*pain points*).
- **Batas Kewenangan:**
  - Dilarang melakukan scraping headless browser ilegal terhadap platform e-commerce yang dilindungi bot mitigation.
  - Dilarang memodifikasi parameter link afiliasi di luar format URL yang sah.
- **Kontrak Data (Pydantic Schema Draft):**
  ```python
  class ProductItem(BaseModel):
      product_id: str
      title: str
      category: str
      price_idr: int
      affiliate_url: HttpUrl
      key_features: list[str]
      pain_points_solved: list[str]
      raw_media_paths: list[str]  # Path lokal gambar/video produk
  ```
- **Handoff:** Meneruskan objek `ProductItem` yang tervalidasi ke **Affiliate Copywriter Specialist**.

---

## 2. Affiliate Copywriter & Hook Specialist

- **Tanggung Jawab:**
  - Menghasilkan naskah video pendek vertikal (15-30 detik) berbahasa Indonesia percakapan yang natural dan berkonversi tinggi.
  - Mengembangkan 3 struktur variasi hook (misal: *Problem Hook*, *Curiosity Hook*, *Discount/Urgency Hook*).
  - Menyusun naskah dengan pembagian waktu yang jelas (Hook 0-3s, Problem/Solution 3-12s, Call to Action 12-15s).
- **Batas Kewenangan:**
  - Dilarang membuat klaim medis palsu atau janji diskon yang tidak ada di data produk.
  - Wajib menyertakan disclaimer atau etika affiliasi jika disyaratkan.
- **Kontrak Data (Pydantic Schema Draft):**
  ```python
  class ScriptScene(BaseModel):
      scene_number: int
      timestamp_start: float
      timestamp_end: float
      voice_text: str       # Naskah yang dibaca voiceover
      visual_instruction: str # Panduan teks overlay atau gambar produk yang tampil
      subtitle_text: str    # Teks caption singkat di layar

  class ContentDraft(BaseModel):
      draft_id: str
      product_id: str
      hook_style: str       # misal: "Problem-Agitation", "Direct Discount"
      total_duration_sec: int
      scenes: list[ScriptScene]
      full_voiceover_script: str
      suggested_caption: str
      hashtags: list[str]
  ```
- **Handoff:** Meneruskan `ContentDraft` ke **Audio & Voiceover Specialist**.

---

## 3. Audio & Voiceover Specialist

- **Tanggung Jawab:**
  - Mengonversi teks `full_voiceover_script` menjadi file audio MP3/WAV berkualitas tinggi dengan intonasi natural.
  - Mengukur durasi audio aktual dan mencatat marker timestamp untuk sinkronisasi video.
  - Melakukan normalisasi volume suara agar tidak pecah dan mudah didengar di smartphone.
- **Batas Kewenangan:**
  - Dilarang mengubah substansi kata naskah tanpa instruksi khusus.
  - Wajib melaporkan jika audio hasil sintesis terpotong atau durasi melebihi batas 30 detik.
- **Kontrak Data (Pydantic Schema Draft):**
  ```python
  class AudioResult(BaseModel):
      draft_id: str
      audio_file_path: str
      voice_id: str         # misal: "id-ID-ArdiNeural"
      duration_seconds: float
      sample_rate: int
      is_normalized: bool
  ```
- **Handoff:** Meneruskan `AudioResult` beserta `ContentDraft` ke **Video Assembly Specialist**.

---

## 4. Video Assembly & Media Specialist (FFmpeg Worker)

- **Tanggung Jawab:**
  - Merakit aset visual (gambar produk beresolusi tinggi / klip demonstrasi) dengan rasio vertikal 9:16 (1080x1920).
  - Menggabungkan audio voiceover dari `AudioResult`.
  - Menerapkan efek gerak halus (Ken Burns / Pan & Zoom) pada gambar diam agar video tetap dinamis.
  - Membakar (*burn-in*) teks hook dan subtitle secara akurat sesuai timestamp naskah.
  - Menggunakan akselerasi hardware NVIDIA NVENC (`h264_nvenc`) untuk efisiensi render.
- **Batas Kewenangan:**
  - Dilarang memotong atau mengaburkan logo merek produk tanpa izin.
  - Wajib menghasilkan video dengan format kontainer MP4 standar (H.264 / AAC) yang kompatibel dengan platform media sosial.
- **Kontrak Data (Pydantic Schema Draft):**
  ```python
  class VideoRenderResult(BaseModel):
      render_id: str
      draft_id: str
      output_video_path: str
      resolution: str       # "1080x1920"
      fps: int              # 30 atau 60
      file_size_bytes: int
      render_duration_sec: float
      status: str           # "SUCCESS" | "FAILED"
  ```
- **Handoff:** Meneruskan `VideoRenderResult` ke **Human Approver Gatekeeper**.

---

## 5. Human Approver Gatekeeper (Reviewer Specialist)

- **Tanggung Jawab:**
  - Menghentikan alur kerja otomatis (status: `WAITING_APPROVAL`).
  - Menyajikan video preview, naskah lengkap, link afiliasi yang ditargetkan, dan metadata ke antarmuka terminal / dashboard.
  - Menerima keputusan manusia:
    - `APPROVE`: Menandai konten siap dipublikasikan/diekspor ke folder output final.
    - `REQUEST_REVISION`: Mengirim kembali catatan perbaikan ke Copywriter atau Video Specialist.
    - `REJECT`: Mengarsipkan draft sebagai konten gagal dan menghentikan pipeline.
- **Batas Kewenangan:**
  - **Satu-satunya entitas yang memiliki otoritas memvalidasi konten untuk publikasi eksternal.**
  - Mesin atau agen otomatis tidak dapat membypass gerbang ini.
- **Kontrak Data (Pydantic Schema Draft):**
  ```python
  class ApprovalDecision(BaseModel):
      draft_id: str
      decision: Literal["APPROVE", "REVISE", "REJECT"]
      reviewer_notes: str | None = None
      timestamp: datetime
  ```

