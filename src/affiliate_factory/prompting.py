"""Deterministic Prompt Generation and AI Output Parser.

Constructs structured copywriting prompts from verified Product models without fabricating
specifications, reviews, prices, or experiences. Parses and validates external AI output
into ContentDraft and Claim entities.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

from affiliate_factory.models import Claim, ContentDraft, Product


class AIClaimPayload(BaseModel):
    """Payload schema for claims extracted from AI output."""
    model_config = ConfigDict(extra="ignore")

    text: str
    source_ref: str | None = None
    verification_status: Literal["UNVERIFIED", "SOURCED", "REJECTED"] = "UNVERIFIED"


class AIDraftPayload(BaseModel):
    """Payload schema expected from structured AI copywriting output."""
    model_config = ConfigDict(extra="ignore")

    angle: str = "Problem-Benefit"
    hook: str
    problem_benefit: str
    script: str | None = None
    cta: str
    caption: str
    hashtags: list[str] = Field(default_factory=list)
    disclosure_text: str = "#ShopeeAffiliate #KontenAI"
    claims: list[AIClaimPayload] = Field(default_factory=list)


def build_copywriting_prompt(
    product: Product,
    angle: str = "Problem-Benefit",
    prompt_version: str = "v1.0",
) -> str:
    """Generate a deterministic prompt instructing an AI to produce structured affiliate copy.

    Strictly forbids fabrication of product details, prices, discounts, or reviews.
    """
    price_str = f"Rp {product.price:,.0f}" if product.price is not None else "TIDAK DIKETAHUI"
    price_date_str = (
        product.price_observed_at.strftime("%Y-%m-%d %H:%M UTC")
        if product.price_observed_at
        else "TIDAK DIKETAHUI"
    )
    notes_str = product.notes.strip() if product.notes else "(Tidak ada catatan khusus)"

    prompt = f"""Kamu adalah asisten copywriter profesional untuk afiliasi Shopee Indonesia.
Tugasmu adalah menyusun draf naskah video pendek (15 detik) dan caption promosi afiliasi berbasis data produk terverifikasi di bawah ini.

============================================================
DATA PRODUK TERVERIFIKASI (JANGAN MENAMBAH FAKTA DI LUAR INI):
============================================================
- ID Produk: {product.id}
- Nama Produk: {product.name}
- URL Pembelian: {product.url}
- Harga Observasi: {price_str}
- Tanggal Cek Harga: {price_date_str}
- Catatan / Fitur Terbukti: {notes_str}
- Sudut Pandang (Angle): {angle}
- Versi Prompt: {prompt_version}

============================================================
ATURAN KERAS (HARD INVARIANTS):
============================================================
1. DILARANG MENGARANG (ZERO FABRICATION):
   - Jangan mengarang klaim garansi, spesifikasi teknis, atau fitur yang tidak tertulis di atas.
   - Jangan membuat ulasan pengguna palsu, testimonial palsu, atau hasil uji performa fiktif.
   - Jangan menjanjikan diskon, promo gratis ongkir, atau harga yang tidak ada di data resmi.
   - Setiap fakta produk yang tidak diketahui WAJIB diabaikan atau ditandai sebagai UNVERIFIED.
2. LARANGAN KLAIM MUTLAK & MEDIS:
   - Dilarang menggunakan klaim berlebihan seperti: 'pasti sembuh', '100% ampuh', 'dijamin sembuh', 'tanpa efek samping', 'dijamin kaya'.
3. KEWAJIBAN DISCLOSURE & LABEL AI:
   - Wajib menyertakan disclosure afiliasi yang jelas (misal: '#ShopeeAffiliate' atau 'afiliasi').
   - Wajib menyertakan label konten AI (misal: '#KontenAI').

============================================================
STRUKTUR NASKAH YANG DIMINTA:
============================================================
1. Hook (0-3 detik): Kalimat pembuka menarik perhatian sesuai masalah target audiens.
2. Problem / Benefit (3-12 detik): Penjelasan manfaat relevan HANYA berdasarkan data terverifikasi.
3. Call to Action / CTA (12-15 detik): Ajakan jelas untuk melihat produk di tautan bio / keranjang kuning.
4. Caption & Hashtags: Teks caption pendukung beserta hashtag wajib (#ShopeeAffiliate, #KontenAI).
5. Klaim: Daftar klaim spesifik yang muncul dalam naskah beserta referensi sumbernya. Jika tidak ada sumber tertulis, tandai verification_status sebagai 'UNVERIFIED'.

============================================================
FORMAT OUTPUT WAJIB (HANYA BERIKAN JSON VALID):
============================================================
Keluarkan HANYA JSON valid tanpa teks pengantar atau penutup dengan struktur persis seperti ini:
{{
  "angle": "{angle}",
  "hook": "<kalimat hook 0-3 detik>",
  "problem_benefit": "<naskah manfaat 3-12 detik>",
  "cta": "<kalimat ajakan klik tautan 12-15 detik>",
  "caption": "<teks caption media sosial>",
  "hashtags": ["#ShopeeAffiliate", "#KontenAI"],
  "disclosure_text": "#ShopeeAffiliate #KontenAI",
  "claims": [
    {{
      "text": "<klaim fakta spesifik>",
      "source_ref": "<URL atau catatan sumber, atau null jika tidak ada sumber>",
      "verification_status": "UNVERIFIED"
    }}
  ]
}}
"""
    return prompt.strip()


def parse_and_validate_ai_draft(
    raw_output: str,
    product_id: str,
    draft_id: str | None = None,
    prompt_version: str = "v1.0",
) -> tuple[ContentDraft, list[Claim]]:
    """Parse raw text from AI (or manual paste), validate JSON, and convert to models.

    Ensures that UNVERIFIED claims cannot silently become verified merely because
    source_ref is non-empty. SOURCED only means a source reference was provided,
    not that factual truth has been independently proven.

    Returns:
        tuple[ContentDraft, list[Claim]]
    Raises:
        ValueError: If JSON is invalid or missing required schema fields.
    """
    clean_text = raw_output.strip()

    # Extract JSON inside markdown code blocks if present
    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_text)
    if json_match:
        clean_text = json_match.group(1).strip()

    try:
        parsed_dict = json.loads(clean_text)
    except Exception as e:
        raise ValueError(f"Gagal mem-parsing JSON dari output AI: {e}") from e

    if not isinstance(parsed_dict, dict):
        raise ValueError("Output AI harus berupa objek JSON (dict).")

    try:
        payload = AIDraftPayload.model_validate(parsed_dict)
    except Exception as e:
        raise ValueError(f"Validasi skema draf AI gagal: {e}") from e

    # Build script from hook + problem_benefit + cta if script is not explicitly provided
    if payload.script and payload.script.strip():
        final_script = payload.script.strip()
    else:
        final_script = f"{payload.hook.strip()} {payload.problem_benefit.strip()} {payload.cta.strip()}"

    effective_draft_id = draft_id or f"draft_{uuid.uuid4().hex[:8]}"

    draft = ContentDraft(
        id=effective_draft_id,
        product_id=product_id,
        angle=payload.angle,
        hook=payload.hook.strip(),
        script=final_script,
        caption=payload.caption.strip(),
        cta=payload.cta.strip(),
        disclosure_text=payload.disclosure_text.strip(),
        status="draft",
        prompt_version=prompt_version,
    )

    claims: list[Claim] = []
    for idx, c in enumerate(payload.claims, start=1):
        # Strict rule: An UNVERIFIED claim CANNOT silently become verified
        # merely because source_ref is non-empty.
        raw_status = c.verification_status
        has_source = bool(c.source_ref and c.source_ref.strip())

        if raw_status == "REJECTED":
            status = "REJECTED"
        elif not has_source or raw_status == "UNVERIFIED":
            # If no source or explicitly marked UNVERIFIED, must stay UNVERIFIED
            status = "UNVERIFIED"
        else:
            # Sourced: reference is provided, awaiting human verification
            status = "SOURCED"

        claims.append(
            Claim(
                id=f"claim_{effective_draft_id}_{idx}",
                draft_id=effective_draft_id,
                text=c.text.strip(),
                source_ref=c.source_ref.strip() if c.source_ref else None,
                verification_status=status,
            )
        )

    return draft, claims
