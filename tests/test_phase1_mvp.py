"""Unit and regression tests for Phase 1 MVP features.

Covers:
- Non-negative price and URL scheme validation on Product model
- CLI intake (single object, array, invalid JSON, duplicate handling)
- Deterministic prompt generation without fact fabrication
- Parsing and validation of AI output (clean JSON, markdown wrapped, malformed)
- Claim verification invariants (UNVERIFIED cannot silently become verified)
- Pipeline integration halting at waiting_approval
- CLI inspection command
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from pydantic import ValidationError

from affiliate_factory.cli import main
from affiliate_factory.db import Database
from affiliate_factory.models import Claim, ContentDraft, Product
from affiliate_factory.orchestrator import run_pipeline
from affiliate_factory.prompting import (
    build_copywriting_prompt,
    parse_and_validate_ai_draft,
)


class TestPhase1MVP(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_phase1.db"
        self.db = Database(self.db_path)

        self.sample_product = Product(
            id="prod_mvp_01",
            name="Tripod HP Bluetooth Universal",
            url="https://shopee.co.id/tripod-bluetooth-universal",
            price=75000.0,
            price_observed_at=datetime.now(timezone.utc),
            source="manual",
            notes="Tinggi maks 1.5m, remote bluetooth include, garansi 6 bulan.",
        )
        self.db.insert_product(self.sample_product)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # 1. Product price validation: non-negative check
    def test_product_negative_price_rejected(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            Product(
                id="prod_neg",
                name="Produk Negatif",
                url="https://shopee.co.id/prod-neg",
                price=-15000.0,
            )
        self.assertIn("Price must be non-negative", str(ctx.exception))

    # 2. Product URL validation: starts with http:// or https://
    def test_product_invalid_url_scheme_rejected(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            Product(
                id="prod_bad_url",
                name="Produk URL Salah",
                url="ftp://shopee.co.id/bad-scheme",
                price=50000.0,
            )
        self.assertIn("Product URL must start with http:// or https://", str(ctx.exception))

        with self.assertRaises(ValidationError):
            Product(
                id="prod_bad_url_2",
                name="Produk URL Polos",
                url="shopee.co.id/no-scheme",
                price=50000.0,
            )

    # 3. CLI Intake: valid single and array JSON
    def test_cli_intake_single_and_array_json(self) -> None:
        # Create single product file
        single_file = Path(self.temp_dir.name) / "single_product.json"
        with open(single_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "id": "prod_single_01",
                    "name": "Lampu Meja LED Fleksibel",
                    "url": "https://shopee.co.id/lampu-meja-led",
                    "price": 45000.0,
                    "notes": "3 tingkat kecerahan, baterai cas USB",
                },
                f,
            )

        code_single = main(["intake", "--file", str(single_file), "--db", str(self.db_path)])
        self.assertEqual(code_single, 0)
        retrieved_single = self.db.get_product("prod_single_01")
        self.assertIsNotNone(retrieved_single)
        self.assertEqual(retrieved_single.name, "Lampu Meja LED Fleksibel")

        # Create array product file
        array_file = Path(self.temp_dir.name) / "array_products.json"
        with open(array_file, "w", encoding="utf-8") as f:
            json.dump(
                [
                    {
                        "id": "prod_arr_01",
                        "name": "Kabel Data Type-C Fast Charging",
                        "url": "https://shopee.co.id/kabel-type-c",
                        "price": 25000.0,
                    },
                    {
                        "id": "prod_arr_02",
                        "name": "Mouse Wireless Silent Click",
                        "url": "https://shopee.co.id/mouse-wireless",
                        "price": 60000.0,
                    },
                ],
                f,
            )

        code_arr = main(["intake", "--file", str(array_file), "--db", str(self.db_path)])
        self.assertEqual(code_arr, 0)
        self.assertIsNotNone(self.db.get_product("prod_arr_01"))
        self.assertIsNotNone(self.db.get_product("prod_arr_02"))

    # 4. CLI Intake: duplicate URL handling without duplicating products
    def test_cli_intake_duplicate_urls_handled_safely(self) -> None:
        dup_file = Path(self.temp_dir.name) / "duplicate_url.json"
        with open(dup_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "id": "prod_different_id_same_url",
                    "name": "Nama Berbeda Tapi URL Duplikat",
                    "url": self.sample_product.url,  # Duplicate of prod_mvp_01
                    "price": 99000.0,
                },
                f,
            )

        code_dup = main(["intake", "--file", str(dup_file), "--db", str(self.db_path)])
        self.assertEqual(code_dup, 0)

        # Database should still have prod_mvp_01 and NOT prod_different_id_same_url
        self.assertIsNone(self.db.get_product("prod_different_id_same_url"))
        original = self.db.get_product_by_url(self.sample_product.url)
        self.assertEqual(original.id, "prod_mvp_01")

    # 5. CLI Intake: invalid JSON and validation errors handled cleanly
    def test_cli_intake_invalid_json_and_validation_error(self) -> None:
        # Non-existent file
        code_missing = main(["intake", "--file", "non_existent_file.json", "--db", str(self.db_path)])
        self.assertEqual(code_missing, 1)

        # Corrupted JSON
        corrupt_file = Path(self.temp_dir.name) / "corrupt.json"
        with open(corrupt_file, "w", encoding="utf-8") as f:
            f.write("{ invalid json")
        code_corrupt = main(["intake", "--file", str(corrupt_file), "--db", str(self.db_path)])
        self.assertEqual(code_corrupt, 1)

        # Valid JSON but schema violation (negative price)
        bad_schema_file = Path(self.temp_dir.name) / "bad_schema.json"
        with open(bad_schema_file, "w", encoding="utf-8") as f:
            json.dump({"id": "bad", "name": "Bad", "url": "https://shopee.co.id/bad", "price": -50.0}, f)
        code_bad_schema = main(["intake", "--file", str(bad_schema_file), "--db", str(self.db_path)])
        self.assertEqual(code_bad_schema, 1)

    # 6. Prompt Generation: deterministic, includes product details, forbids fabricating facts
    def test_prompt_generation_deterministic_and_no_fabrication(self) -> None:
        prompt_1 = build_copywriting_prompt(self.sample_product, angle="Problem-Benefit", prompt_version="v1.0")
        prompt_2 = build_copywriting_prompt(self.sample_product, angle="Problem-Benefit", prompt_version="v1.0")

        # Deterministic
        self.assertEqual(prompt_1, prompt_2)

        # Must include verified product info
        self.assertIn("prod_mvp_01", prompt_1)
        self.assertIn("Tripod HP Bluetooth Universal", prompt_1)
        self.assertIn("75,000", prompt_1)
        self.assertIn("https://shopee.co.id/tripod-bluetooth-universal", prompt_1)
        self.assertIn("Tinggi maks 1.5m", prompt_1)

        # Must include anti-fabrication rules and required sections
        self.assertIn("DILARANG MENGARANG (ZERO FABRICATION)", prompt_1)
        self.assertIn("LARANGAN KLAIM MUTLAK & MEDIS", prompt_1)
        self.assertIn("#ShopeeAffiliate", prompt_1)
        self.assertIn("#KontenAI", prompt_1)
        self.assertIn("Hook (0-3 detik)", prompt_1)
        self.assertIn("Problem / Benefit (3-12 detik)", prompt_1)
        self.assertIn("Call to Action / CTA (12-15 detik)", prompt_1)

    # 7. AI Output Parsing: parses clean JSON and markdown-wrapped JSON
    def test_parse_and_validate_ai_draft_success(self) -> None:
        raw_ai_json = """```json
{
  "angle": "Problem-Benefit",
  "hook": "Capek bikin video goyang melulu waktu bikin konten?",
  "problem_benefit": "Tripod universal 1.5 meter ini kokoh dan sudah ada remote bluetooth praktis.",
  "cta": "Yuk dapatkan produk aslinya sekarang di link profil!",
  "caption": "Bikin konten stabil makin gampang. Link beli di bio. #ShopeeAffiliate #KontenAI",
  "hashtags": ["#ShopeeAffiliate", "#KontenAI", "#TripodHP"],
  "disclosure_text": "#ShopeeAffiliate #KontenAI Konten promosi kemitraan",
  "claims": [
    {
      "text": "Tinggi maksimal 1.5 meter",
      "source_ref": "https://shopee.co.id/tripod-bluetooth-universal",
      "verification_status": "SOURCED"
    },
    {
      "text": "Termasuk remote bluetooth dalam paket",
      "source_ref": "https://shopee.co.id/tripod-bluetooth-universal",
      "verification_status": "SOURCED"
    }
  ]
}
```"""
        draft, claims = parse_and_validate_ai_draft(
            raw_output=raw_ai_json,
            product_id=self.sample_product.id,
            draft_id="draft_test_parse_01",
            prompt_version="v1.0",
        )

        self.assertEqual(draft.id, "draft_test_parse_01")
        self.assertEqual(draft.product_id, self.sample_product.id)
        self.assertEqual(draft.hook, "Capek bikin video goyang melulu waktu bikin konten?")
        self.assertIn("Tripod universal 1.5 meter", draft.script)
        self.assertEqual(draft.disclosure_text, "#ShopeeAffiliate #KontenAI Konten promosi kemitraan")
        self.assertEqual(len(claims), 2)
        self.assertEqual(claims[0].verification_status, "SOURCED")
        self.assertEqual(claims[1].verification_status, "SOURCED")

    # 8. Malformed AI Output fails validation gracefully
    def test_parse_malformed_ai_output_fails_gracefully(self) -> None:
        # Invalid JSON
        with self.assertRaises(ValueError) as ctx:
            parse_and_validate_ai_draft("Bukan JSON sama sekali", product_id="prod_01")
        self.assertIn("Gagal mem-parsing JSON", str(ctx.exception))

        # Missing required field (e.g. hook missing)
        missing_hook_json = json.dumps({
            "angle": "Problem-Benefit",
            "problem_benefit": "Konten tanpa hook",
            "cta": "Klik bio",
            "caption": "Caption",
            "disclosure_text": "#ShopeeAffiliate #KontenAI",
        })
        with self.assertRaises(ValueError) as ctx:
            parse_and_validate_ai_draft(missing_hook_json, product_id="prod_01")
        self.assertIn("Validasi skema draf AI gagal", str(ctx.exception))

    # 9. Claim Invariants: UNVERIFIED cannot silently become verified merely because source_ref is nonempty
    def test_unverified_claim_cannot_silently_become_verified(self) -> None:
        raw_json = json.dumps({
            "angle": "Unverified Test",
            "hook": "Hook pengujian klaim",
            "problem_benefit": "Benefit",
            "cta": "CTA",
            "caption": "Caption",
            "disclosure_text": "#ShopeeAffiliate #KontenAI",
            "claims": [
                {
                    "text": "Klaim tanpa sumber sama sekali",
                    "source_ref": None,
                    "verification_status": "UNVERIFIED",
                },
                {
                    "text": "Klaim dengan URL sembarang tapi berstatus UNVERIFIED",
                    "source_ref": "https://random-blog.com/post",
                    "verification_status": "UNVERIFIED",  # Explicitly UNVERIFIED
                },
                {
                    "text": "Klaim dengan sumber kosong string spasi",
                    "source_ref": "   ",
                    "verification_status": "SOURCED",  # Claims SOURCED but empty source
                },
            ],
        })

        draft, claims = parse_and_validate_ai_draft(raw_json, product_id=self.sample_product.id)

        self.assertEqual(claims[0].verification_status, "UNVERIFIED")
        # Even with source_ref present, an UNVERIFIED claim remains UNVERIFIED
        self.assertEqual(claims[1].verification_status, "UNVERIFIED")
        # Whitespace-only source_ref must remain UNVERIFIED
        self.assertEqual(claims[2].verification_status, "UNVERIFIED")

    # 10. Pipeline Integration: imported draft goes through run_pipeline and halts at waiting_approval
    def test_pipeline_integration_with_imported_draft(self) -> None:
        valid_json = json.dumps({
            "angle": "Ergonomics",
            "hook": "Mau video stabil tanpa getaran tangan?",
            "problem_benefit": "Tripod ini punya tinggi hingga 1.5m dan koneksi bluetooth responsif.",
            "cta": "Cek harga terbarunya di bio sekarang!",
            "caption": "Tripod andalan konten kreator. Link di bio. #ShopeeAffiliate #KontenAI",
            "hashtags": ["#ShopeeAffiliate", "#KontenAI"],
            "disclosure_text": "#ShopeeAffiliate #KontenAI Promosi Kemitraan",
            "claims": [
                {
                    "text": "Tinggi maksimal 1.5 meter",
                    "source_ref": self.sample_product.url,
                    "verification_status": "SOURCED",
                }
            ],
        })

        draft, claims = parse_and_validate_ai_draft(
            valid_json,
            product_id=self.sample_product.id,
            draft_id="draft_pipeline_test",
        )

        res = run_pipeline(db=self.db, product=self.sample_product, draft=draft, claims=claims)

        # Halts at waiting_approval
        self.assertEqual(res.draft.status, "waiting_approval")
        self.assertTrue(res.compliance_report.passed)
        self.assertEqual(len(res.claims), 1)

        # Database state verification
        saved_draft = self.db.get_draft(draft.id, draft.prompt_version)
        self.assertIsNotNone(saved_draft)
        self.assertEqual(saved_draft.status, "waiting_approval")

        saved_comp = self.db.get_compliance_report(draft.id)
        self.assertIsNotNone(saved_comp)
        self.assertTrue(saved_comp.passed)

        saved_claims = self.db.get_claims_for_draft(draft.id)
        self.assertEqual(len(saved_claims), 1)
        self.assertEqual(saved_claims[0].verification_status, "SOURCED")

    # 11. CLI Subcommands Smoke Tests (prompt, import-draft, inspect)
    def test_cli_subcommands_smoke(self) -> None:
        # Prompt subcommand
        code_prompt = main(["prompt", "--product-id", self.sample_product.id, "--db", str(self.db_path)])
        self.assertEqual(code_prompt, 0)

        # Import-draft subcommand
        draft_file = Path(self.temp_dir.name) / "draft_to_import.json"
        with open(draft_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "angle": "Quick Review",
                    "hook": "Tripod murah tapi kokoh banget?",
                    "problem_benefit": "Tripod bluetooth ini praktis dibawa kemana-mana.",
                    "cta": "Link pembelian resmi ada di bio!",
                    "caption": "Rekomendasi tripod hemat. #ShopeeAffiliate #KontenAI",
                    "hashtags": ["#ShopeeAffiliate", "#KontenAI"],
                    "disclosure_text": "#ShopeeAffiliate #KontenAI",
                    "claims": [
                        {
                            "text": "Garansi 6 bulan resmi",
                            "source_ref": self.sample_product.url,
                            "verification_status": "SOURCED",
                        }
                    ],
                },
                f,
            )

        code_import = main([
            "import-draft",
            "--file",
            str(draft_file),
            "--product-id",
            self.sample_product.id,
            "--draft-id",
            "draft_cli_smoke_01",
            "--db",
            str(self.db_path),
        ])
        self.assertEqual(code_import, 0)

        # Inspect subcommand
        code_inspect = main([
            "inspect",
            "--draft-id",
            "draft_cli_smoke_01",
            "--db",
            str(self.db_path),
        ])
        self.assertEqual(code_inspect, 0)


if __name__ == "__main__":
    unittest.main()
