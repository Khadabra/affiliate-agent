# SUMBER 03: BATASAN SUBIDS PADA GENERATESHORTLINK

- **Klaim yang Diperiksa:** Berapa batas maksimal parameter `subIds` yang didukung oleh mutasi `generateShortLink`?
- **Status Verifikasi:** `DOCUMENTATION_ONLY`.
- **URL Sumber:** `https://affiliateshopee.com.br/` (Dokumentasi mutasi GraphQL `generateShortLink`)
- **Tanggal Akses:** 2026-11-02
- **Kutipan Pendek (Maksimal 15 Kata):**
  > *"subIds array parameter accepts up to a maximum of five tracking values"*
- **Catatan & Fakta Aktual:**
  Parameter input pada mutasi GraphQL adalah `subIds: [String]`. Dokumentasi menetapkan maksimal 5 sub-ID (indeks 0 hingga 4, atau `sub_id_1` sampai `sub_id_5`) untuk tujuan pelacakan UTM/sumber traffic internal. Melebihi 5 sub-ID akan menghasilkan pesan error validasi input GraphQL.
