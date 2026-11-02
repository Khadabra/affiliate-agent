# STUDI KELAYAKAN VISUALISASI ANIMASI KANTOR (V0)

Dokumen ini memuat analisis kelayakan teknis visualisasi aktivitas sistem berbasis kode sumber repositori referensi `https://github.com/humaedihume/kantor-agent` (diperiksa secara *read-only* dari klon lokal di `tmp/reference/kantor-agent`).

> **Status:** `PROPOSAL & FEASIBILITY STUDY ONLY` (Tidak ada kode visualisasi yang diimplementasikan atau dieksekusi pada fase ini).

---

## 1. Skema JSON State yang Diharapkan Front-End (`/kerja/api/state`)

Berdasarkan audit kode sumber pada `skills/kantor-agent/runtime/lib/node/office.mjs` dan `runtime/public/assets/kantor.js`, front-end 3D (Three.js) mengonsumsi payload JSON dengan struktur berikut:

```json
{
  "app": "kantor-agent",
  "version": "1.0.0",
  "now": "2026-11-02T10:00:00.000Z",
  "project": "Nama Proyek",
  "names": "Joko|Budi|Sari|Agus|Rina",
  "transcripts": true,
  "ketua": {
    "key": "ketua",
    "name": "Joko",
    "label": "Joko",
    "state": "bekerja",
    "action": "Menulis naskah produk",
    "updated": "2026-11-02T09:59:00.000Z"
  },
  "team": [
    {
      "key": "t0",
      "name": "Budi",
      "label": "Budi",
      "state": "santai",
      "action": "Menunggu tugas",
      "updated": null
    }
  ],
  "freelancers": [],
  "feed": [
    {
      "t": "2026-11-02T10:00:00.000Z",
      "ms": 1730541600000,
      "who": { "name": "Joko", "label": "Joko", "color": "#ff5500" },
      "kind": "tool",
      "text": "Evaluasi kepatuhan naskah",
      "tool": "compliance"
    }
  ],
  "runs": [],
  "stats": {
    "active": 1,
    "freelancers": 0,
    "total": 5,
    "recent_starts": [],
    "sessions_active": 1
  },
  "spare_desks": 4,
  "public_url": null
}
```

Front-end `kantor.js` menggunakan Three.js untuk memetakan setiap entitas (`ketua`, `team[i]`, `freelancers[j]`) ke model 3D/voxel karakter di atas meja kantor virtual, dengan animasi berjalan, duduk, mengetik saat `state == "bekerja"`, atau bersantai saat `state == "santai"`.

---

## 2. Analisis Kompatibilitas Transkrip Antigravity vs Claude Code

- **Hasil Audit Sumber `transcripts.mjs`:**  
  `kantor-agent` mencari direktori transkrip spesifik Claude Code:
  `~/.claude/projects/<project-slug>/` berisi file `<session_id>.jsonl` dan folder `<session_id>/subagents/agent-<id>.jsonl` beserta metadata `.meta.json`.
- **Mekanisme Transkrip Antigravity:**  
  Antigravity IDE menyimpan transkrip sesi internal di direktori instalasi aplikasi (`%APPDATA%\brain\<conversation-id>\.system_generated\logs\transcript.jsonl`), dengan skema objek JSONL yang sangat berbeda (`step_index`, `source`, `type`, `status`, `content`, `tool_calls`).
- **Kesimpulan Status:** `INCOMPATIBLE / NOT_VERIFIED`.  
  `kantor-agent` **TIDAK DAPAT** membaca transkrip Antigravity secara langsung tanpa modifikasi kode pengurai.
- **Konteks Aplikasi Kita:**  
  Aplikasi kita (AI Affiliate Content Factory) berjalan secara mandiri dari terminal/backend Python dan telah memiliki tabel log audit sendiri di SQLite (`events`), yang mencatat setiap aksi modul secara terstruktur (`intake`, `compliance`, `claim_checker`, `orchestrator`, `waiting_approval`).

---

## 3. Opsi Pengembangan & Analisis Trade-off

| Opsi | Pendekatan Teknis | Keuntungan | Kerugian & Risiko | Estimasi Kompleksitas |
| :--- | :--- | :--- | :--- | :--- |
| **Opsi A: Adaptasi Front-end 3D ke Tabel `events` Kita** | Membaca event dari SQLite lokal aplikasi kita, mengekspos endpoint `/kerja/api/state` via FastAPI/HTTP server ringan, dan menggunakan aset visual Three.js `kantor-agent` (mematuhi lisensi MIT & menyertakan `THIRD_PARTY_NOTICES`). | 1. Visualisasi mencerminkan aktivitas bisnis afiliasi nyata kita.<br>2. Tidak bergantung pada Claude Code atau WSL.<br>3. Ringan dan terintegrasi dengan database lokal. | 1. Memerlukan penulisan endpoint state converter di backend.<br>2. Membutuhkan Three.js client di browser. | **Sedang (Medium)** |
| **Opsi B: Menjalankan Claude Code di WSL Khusus Visualisasi** | Memasang Claude Code CLI di dalam WSL2 Windows, menjalankan `kantor.sh`, dan menyimulasikan proyek lewat Claude Code. | Mendapatkan visualisasi bawaan tanpa mengubah kode `kantor-agent`. | 1. Sangat berat: memerlukan setup WSL, Node.js, Claude Code CLI, dan autentikasi terpisah.<br>2. Tidak memvisualisasikan pipeline Python kita, hanya memvisualisasikan sesi Claude Code.<br>3. Redundansi tinggi. | **Sangat Tinggi (High Friction)** |
| **Opsi C: Tunda Visualisasi 3D (DEFERRED)** | Menunda integrasi visual 3D; memfokuskan energi pada stabilitas pipeline teks, kepatuhan promosi, dan persetujuan naskah manual di Phase 1. | 1. Zero overhead komputasi.<br>2. Fokus 100% pada utilitas nyata afiliasi.<br>3. Menghindari kerentanan keamanan port lokal. | Belum ada representasi grafis karakter kantor lucu di browser. | **Nol (Zero Overhead)** |

---

## 4. Evaluasi Risiko Keamanan & Operasional

1. **Risiko Server Lokal & Port Binding:**
   `kantor-agent` menjalankan server HTTP lokal (Node.js/PHP). Jika server ini di-bind ke `0.0.0.0` tanpa autentikasi, pihak lain dalam jaringan Wi-Fi lokal dapat membaca status pekerjaan dan riwayat naskah.
2. **Risiko Tunnel Publik:**
   Di dalam `office.mjs`, terdapat referensi `tunnel-url.txt` (misalnya via Cloudflare Tunnel atau Ngrok). Membuka tunnel publik tanpa mekanisme login/token membawa risiko kebocoran data draft afiliasi ke publik.
3. **Kepatuhan Lisensi (MIT):**
   Repositori `humaedihume/kantor-agent` berlisensi **MIT**. Jika aset front-end (Three.js dan logika visual kantor) diadaptasi di masa depan, kita wajib menyertakan salinan teks hak cipta asli dan file `THIRD_PARTY_NOTICES.md`.

---

## 5. Rekomendasi Arsitektural

> **Rekomendasi Utama: OPSI C (TUNDA / DEFERRED) untuk Phase 1.**

**Alasan:**
1. Prioritas proyek adalah menghasilkan konten afiliasi yang patuh, aman dari ban Shopee, dan menghasilkan konversi nyata.
2. Pipeline fondasi (M1 & M2) telah merekam seluruh aktivitas ke tabel SQLite `events`. Dengan demikian, data historis dan status tersimpan rapi.
3. Saat sistem inti telah stabil menghasilkan naskah dan diuji pengguna, kita dapat mengadopsi **Opsi A** (membuat adaptor JSON sederhana dari tabel `events` ke viewer visual) pada Phase 2 tanpa harus menjalankan WSL atau Claude Code.

