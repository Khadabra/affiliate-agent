# SUMBER 04: HAK CIPTA / CONTENT THEFT DAN LABEL KONTEN AI

Dokumen ini memisahkan dua klaim independen terkait kepatuhan materi promosi di platform Shopee Indonesia.

---

## Klaim (i): Larangan Pelanggaran Hak Cipta & Pencurian Konten (Content Theft)

- **Klaim yang Diperiksa:** Apakah Shopee melarang pengunggahan karya berhak cipta orang lain tanpa izin dan melindungi karya orisinal?
- **Status Verifikasi:** `VERIFIED`
- **URL Sumber:** [Panduan Komunitas Shopee Video (Artikel 71218)](https://help.shopee.co.id/portal/article/71218-Panduan-Komunitas-Shopee-Video)
- **Tanggal Akses:** 2026-11-02
- **Metode Pengambilan:** HTTP GET via Python `urllib.request` (Pemeriksaan SSR Content).
- **Kutipan Persis Asli (Bahasa Asli Halaman):**
  > *"Hak cipta adalah hak hukum yang sah yang melindungi karya orisinal (misalnya musik, video)"*
- **Kutipan Tambahan Persis Asli:**
  > *"Konten yang melanggar atau menyalahi hak cipta, merek dagang, atau hak kekayaan intelektual orang lain"*
- **Catatan:** Pelanggaran atas hak cipta musik atau re-upload video tanpa izin mengakibatkan penindakan berupa pembisuan (*mute*) atau penghapusan video.

---

## Klaim (ii): Aturan Terkait Konten Dihasilkan AI di Shopee

- **Klaim yang Diperiksa:** Bagaimana aturan resmi Shopee mengenai konten yang dihasilkan atau dibantu oleh kecerdasan buatan (AI)?
- **Status Verifikasi:** `VERIFIED` (Untuk fitur Affiliate AI-Generated Content) / `DOCUMENTATION_ONLY` (Untuk toggle wajib di Shopee Video)
- **URL Sumber yang Diperiksa:**
  1. [[Shopee Affiliate Program] Apa itu fitur AI-Generated Content (Artikel 203749)](https://help.shopee.co.id/portal/4/article/203749-[Shopee-Affiliate-Program]-Apa-itu-fitur-AI-Generated-Content)
  2. [Seller Education Hub - Kebijakan AI Shopee Video (Artikel 27618)](https://seller.shopee.co.id/edu/article/27618)
  3. [Panduan Komunitas Shopee Video (Artikel 71218)](https://help.shopee.co.id/portal/article/71218-Panduan-Komunitas-Shopee-Video)
- **Tanggal Akses:** 2026-11-02
- **Metode Pengambilan:** HTTP GET via Python `urllib.request`.
- **Kutipan Persis Asli (Dari Artikel 203749):**
  > *"Caption dibuat menggunakan AI. Pastikan Anda meninjau kembali isi caption sebelum dipublikasikan"*
- **Kutipan Tambahan Persis Asli (Definisi AI-Generated Content di Shopee Affiliate):**
  > *"AI-Generated Content adalah fitur yang membantu Affiliate membuat materi promosi secara otomatis menggunakan AI."*
- **Temuan Pada Artikel 71218:** Kata "AI" atau toggle khusus "Konten dihasilkan AI" berstatus `NOT_FOUND` pada teks artikel 71218. Kebijakan toggle label AI pada unggahan Shopee Video terdokumentasi pada portal edukasi seller (Artikel 27618) yang menggunakan rendering aplikasi web sisi klien.
