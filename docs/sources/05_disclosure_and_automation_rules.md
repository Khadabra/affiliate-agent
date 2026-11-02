# SUMBER 05: ATURAN DISCLOSURE AFILIASI, LARANGAN SCRAPING, DAN AKSES OPEN API RESMI

Dokumen ini memisahkan secara tegas tiga hal: aturan disclosure hubungan afiliasi, larangan scraping otomatis, dan penggunaan Open API resmi Shopee.

---

## 1. Aturan Pengungkapan Hubungan Afiliasi (Affiliate Disclosure)

- **Klaim yang Diperiksa:** Apakah terdapat pasal tertulis yang mewajibkan pengungkapan eksplisit hubungan afiliasi kepada konsumen (misal: penandaan wajib `#Afiliasi` / `#Sponsor`) dalam dokumen resmi Shopee?
- **Status Verifikasi:** `NOT_FOUND setelah memeriksa:`
  1. `https://help.shopee.co.id/portal/article/71217-Syarat-dan-Ketentuan-Program-Afiliasi-Shopee-untuk-Individu`
  2. `https://help.shopee.co.id/portal/article/71218-Panduan-Komunitas-Shopee-Video`
  3. `https://help.shopee.co.id/portal/4/article/73507` (Peraturan Komunitas Shopee)
- **Tanggal Akses:** 2026-11-02
- **Metode Pengambilan:** HTTP GET via Python `urllib.request` dan penelusuran kata kunci teks SSR (`disclosure`, `pengungkapan`, `hubungan afiliasi`, `sponsor`, `transparansi`).
- **Temuan Faktual:**
  - Kata `disclosure`, `hubungan afiliasi`, `sponsor`, dan `transparansi` menghasilkan **0 kecocokan** pada kedua dokumen (71217 dan 71218).
  - Kata `pengungkapan` muncul 12 kali pada Artikel 71217, namun seluruhnya merujuk secara ketat pada klausul kerahasiaan (*Pengungkapan Informasi Rahasia / Non-Disclosure Agreement* antar-pihak), **bukan** kewajiban disclosure promosi kepada audiens.
  - Kewajiban disclosure yang diadopsi sistem kami saat ini merupakan prinsip kepatuhan umum terhadap etika periklanan dan perlindungan konsumen, bukan pasal harfiah dalam dokumen Shopee yang diperiksa.

---

## 2. Larangan Scraping dan Skrip Pengumpul Informasi Otomatis

- **Klaim yang Diperiksa:** Apakah Shopee melarang penggunaan bot, spider, atau skrip otomatis pengumpul informasi tanpa izin?
- **Status Verifikasi:** `VERIFIED`
- **URL Sumber:**
  1. [Syarat dan Ketentuan Program Afiliasi Shopee untuk Individu (Artikel 71217)](https://help.shopee.co.id/portal/article/71217-Syarat-dan-Ketentuan-Program-Afiliasi-Shopee-untuk-Individu)
  2. [Panduan Komunitas Shopee Video (Artikel 71218)](https://help.shopee.co.id/portal/article/71218-Panduan-Komunitas-Shopee-Video)
- **Tanggal Akses:** 2026-11-02
- **Kutipan Persis Asli (Pasal Larangan Afiliasi 71217):**
  > *"menggunakan robot atau alat kueri otomatis lainnya, permintaan pencarian yang dihasilkan oleh komputer;"*
- **Kutipan Persis Asli (Panduan Komunitas 71218):**
  > *"Jangan menggunakan skrip otomatis untuk mengumpulkan informasi dari Shopee"*

---

## 3. Penggunaan Shopee Open API Resmi (Terpisah dari Scraping)

- **Klaim yang Diperiksa:** Bagaimana status hukum dan operasional penggunaan API resmi Shopee?
- **Status Verifikasi:** `DOCUMENTATION_ONLY`
- **URL Sumber:** `https://open.shopee.com`
- **Tanggal Akses:** 2026-11-02
- **Pembedaan Tegas:**
  - **Scraping / Bot (DILARANG):** Mengakses antarmuka HTML/web Shopee secara ilegal dengan skrip penjelajah (*spider/crawler*), membypass CAPTCHA, atau memanipulasi klik.
  - **Open API Resmi (DIIZINKAN):** Mengakses data produk dan kampanye melalui gateway resmi Shopee Open Platform menggunakan kredensial pengembang (`partner_id`, `appId`, tanda tangan kriptografis). Pemanfaatan jalur ini sah dan tunduk pada Syarat Layanan Pengembang Shopee.
