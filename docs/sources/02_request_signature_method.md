# SUMBER 02: METODE TANDA TANGAN REQUEST (SIGNATURE)

- **Klaim yang Diperiksa:** Apakah metode pembuatan tanda tangan request (signature) menggunakan HMAC-SHA256 atau SHA-256 biasa (concatenation)?
- **Status Verifikasi:** `NOT_VERIFIED`
- **Pernyataan Wajib:** Metode tanda tangan hanya bisa dipastikan dengan kredensial nyata.
- **URL Sumber yang Diperiksa:**
  1. `https://open.shopee.com/documents/v2/v2.general.sign` (Dokumentasi Tanda Tangan Seller Open Platform)
  2. Berbagai forum integrasi pengembang & repositori komunitas pihak ketiga.
- **Metode Pengambilan:** HTTP GET dan penelusuran dokumentasi pada 2026-11-02.
- **Catatan Pertentangan Sumber (Tanpa Memilih):**
  - **Sumber Tipe A (Seller Open Platform v2):** Mendokumentasikan algoritma **HMAC-SHA256** menggunakan `partner_key` dengan base string yang menggabungkan `partner_id`, `api_path`, `timestamp`, `access_token`, dan `shop_id`.
  - **Sumber Tipe B (Komunitas Affiliate GraphQL):** Mendokumentasikan penggunaan header `Authorization: SHA256 Credential=...` dengan hashing **SHA-256 biasa** (tanpa HMAC) atas string faktor gabungan `appId + timestamp + payload + secret`.
  - Dokumen resmi khusus untuk tanda tangan Affiliate Open API publisher tidak dapat diakses secara publik tanpa akun developer aktif. Karena itu, kedua pola dicatat sebagai pertentangan sumber terbuka sampai diuji langsung dengan kredensial sah.
