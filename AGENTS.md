# AI Affiliate Content Factory — Workspace Operating Rules

> **Scope:** File ini berlaku otomatis untuk seluruh agen, subagen, dan percakapan di dalam workspace `d:\Khadabra\Kerjaan gua\affiliate`.

---

## 1. Aturan Mutlak Tata Kelola

1. **Empirical Verification First:**
   - Dilarang membuat kesimpulan atau klaim sebelum memeriksa file, direktori, dan konfigurasi aktual di Windows PowerShell.
   - Klasifikasikan setiap temuan sebagai `VERIFIED`, `ASSUMPTION`, `PROPOSAL`, atau `NOT VERIFIED`.

2. **No Unapproved Modifications:**
   - Dilarang menginstal dependensi (pip/uv), mengkloning git repo, menghapus file, atau membuat akun/API berbayar tanpa persetujuan eksplisit user.
   - Fase 0A adalah murni fase inspeksi, audit, dan tata kelola.

3. **Human-in-the-Loop Publication Gate:**
   - Tidak ada publikasi, posting, atau aksi eksternal yang dapat dieksekusi tanpa persetujuan eksplisit manusia (`APPROVE`).

4. **Platform & Legal Safety:**
   - Dilarang keras mengakali bot detection, CAPTCHA, atau mem-bypass login Shopee/e-commerce.
   - Gunakan input terkurasi manual atau Shopee Open Platform API resmi.

5. **Security & Zero-Leakage:**
   - Dilarang menyimpan API key atau kredensial di dalam source code, dokumen markdown publik, atau log. Gunakan local `.env`.

6. **Hardware Awareness (Windows 11 / RTX 4050 6GB):**
   - Waspadai batas memori VRAM GPU (6GB). Hindari menjalankan model difusi berat atau proses berat tanpa pertimbangan VRAM.
   - Gunakan runtime Python 3.12 via `uv` untuk memastikan kompatibilitas wheel library AI.

