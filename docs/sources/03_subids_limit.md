# SUMBER 03: BATASAN SUBIDS PADA GENERATESHORTLINK

- **Klaim yang Diperiksa:** Apakah parameter `subIds` pada mutasi `generateShortLink` memiliki batas maksimal 5 nilai tracking?
- **Status Verifikasi:** `NOT_VERIFIED`
- **URL Sumber yang Diperiksa:** `https://affiliateshopee.com.br/`
- **Metode Pengambilan:** HTTP GET via Python `urllib.request` pada 2026-11-02 (Status respons: 200, panjang HTML: 36.494 byte).
- **Temuan Aktual di Halaman:**
  - Pencarian string `subids` pada HTML halaman tersebut menghasilkan `False` (0 kecocokan).
  - Kutipan batas 5 sub-ID tidak tertulis secara harfiah pada halaman publik tersebut. Informasi mengenai batasan 5 elemen pada array `subIds: [String]` bersumber dari cuplikan diskusi teknis eksternal, bukan dari teks eksplisit yang dapat dibaca pada halaman resmi yang dibuka.
