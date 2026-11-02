# SUMBER 02: METODE TANDA TANGAN REQUEST (SIGNATURE)

- **Klaim yang Diperiksa:** Apakah request signature menggunakan SHA-256 biasa (concatenation) atau HMAC-SHA256?
- **Status Verifikasi:** `DOCUMENTATION_ONLY`.
- **URL Sumber:**
  1. Shopee Open Platform V2 (Seller): `https://open.shopee.com/documents/v2/v2.general.sign`
  2. Shopee Affiliate GraphQL Docs: `https://affiliateshopee.com.br/` (Panduan teknis API regional Shopee Affiliate)
- **Tanggal Akses:** 2026-11-02
- **Kutipan Pendek (Maksimal 15 Kata):**
  > *"Authorization: SHA256 Credential={appId},Timestamp={timestamp},Signature={signature}"*
- **Catatan & Fakta Aktual:**
  - **Seller API (Shopee Open Platform):** Menggunakan **HMAC-SHA256** dengan format `hmac_sha256(partner_key, base_string)`.
  - **Affiliate Open API (GraphQL):** Menggunakan **SHA-256 biasa** (bukan HMAC). Rumus factor: `appId + timestamp + payload_json + secret`, lalu di-hash dengan SHA-256.
  - *Koreksi Konseptual:* Tanda tangan (*signature*) ini adalah **fungsi hash kriptografis satu arah**, **BUKAN enkripsi**.
