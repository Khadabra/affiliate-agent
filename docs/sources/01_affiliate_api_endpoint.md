# SUMBER 01: ENDPOINT SHOPEE AFFILIATE OPEN API INDONESIA

- **Klaim yang Diperiksa:** Apakah endpoint `https://open-api.affiliate.shopee.co.id/graphql` tertulis di dokumentasi resmi publik Shopee Indonesia?
- **Status Verifikasi:** `NOT_VERIFIED`
- **URL Sumber yang Diperiksa:**
  1. `https://affiliate.shopee.co.id/` (Portal Utama Shopee Affiliate Indonesia)
  2. `https://open.shopee.com` (Dokumentasi Resmi Shopee Open Platform)
- **Metode Pengambilan:** HTTP GET via Python `urllib.request` dengan header User-Agent pada 2026-11-02.
- **Temuan Aktual di Halaman:**
  - Halaman `https://affiliate.shopee.co.id/` adalah aplikasi web berbasis React (SPA) yang menampilkan formulir login akun Shopee. Kata `open-api` atau endpoint GraphQL **TIDAK DITEMUKAN** pada HTML publik halaman tersebut.
  - Halaman `https://open.shopee.com` hanya memuat dokumentasi Shopee Open Platform untuk Seller/Brand (AMS).
  - Klaim endpoint `open-api.affiliate.shopee.co.id/graphql` hanya ditemukan pada situs pihak ketiga / forum komunitas, bukan dokumentasi publik Shopee resmi tanpa login.
