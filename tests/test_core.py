"""Unit tests for AI Affiliate Content Factory core foundation.

Covers M2 required test cases using Python standard library unittest.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path

from affiliate_factory.claim_checker import check_claims
from affiliate_factory.compliance import check_compliance
from affiliate_factory.db import Database
from affiliate_factory.intake import intake_product
from affiliate_factory.models import (
    Claim,
    ContentDraft,
    PerformanceRecord,
    Product,
)
from affiliate_factory.orchestrator import run_pipeline

CONFIG_PATH = Path("config") / "compliance_rules.json"


class TestAffiliateFactoryCore(unittest.TestCase):
    def setUp(self) -> None:
        # Use an in-memory database for clean, isolated tests
        self.db = Database(":memory:")

        # Reusable sample product
        self.sample_product = Product(
            id="prod_001",
            name="Earphone Bluetooth Nirkabel Bass",
            url="https://shopee.co.id/product-i.123456.7890",
            price=149000.0,
            price_observed_at=datetime.now(timezone.utc),
            source="manual",
            notes="Garansi resmi 1 tahun.",
        )

    # 1. draft tanpa disclosure -> compliance gagal
    def test_draft_without_disclosure_fails_compliance(self) -> None:
        draft = ContentDraft(
            id="draft_001",
            product_id=self.sample_product.id,
            angle="Problem-Agitation",
            hook="Telinga sakit pakai earphone kabel murahan?",
            script="Earphone ini sangat empuk di telinga dan bass mantap.",
            caption="Yuk cek earphone bluetooth ini di bio sekarang!",
            cta="Klik link di bio untuk diskon 50%",
            disclosure_text="",  # Empty disclosure
            status="draft",
            prompt_version="manual",
        )

        self.db.insert_product(self.sample_product)
        self.db.upsert_draft(draft)
        report = check_compliance(
            db=self.db,
            draft=draft,
            product=self.sample_product,
            config_path=CONFIG_PATH,
        )

        self.assertFalse(report.passed)
        rule_ids = [f.rule_id for f in report.findings]
        self.assertIn("RULE-DISCLOSURE-01", rule_ids)

    # 2. draft berisi "pasti sembuh" -> gagal dengan rule_id yang benar
    def test_draft_with_prohibited_claim_fails_with_correct_rule_id(self) -> None:
        draft = ContentDraft(
            id="draft_002",
            product_id=self.sample_product.id,
            angle="Health Claim",
            hook="Obat herbal alami paling dicari!",
            script="Penyakit kronis kamu pasti sembuh total tanpa dokter dalam 3 hari!",
            caption="Pesan sekarang #ShopeeAffiliate",
            cta="Klik link pembelian",
            disclosure_text="#ShopeeAffiliate Tautan berbayar",
            status="draft",
            prompt_version="manual",
        )

        self.db.insert_product(self.sample_product)
        self.db.upsert_draft(draft)
        report = check_compliance(
            db=self.db,
            draft=draft,
            product=self.sample_product,
            config_path=CONFIG_PATH,
        )

        self.assertFalse(report.passed)
        finding = next((f for f in report.findings if f.rule_id == "RULE-PROHIBITED-CLAIMS-01"), None)
        self.assertIsNotNone(finding)
        self.assertIn("pasti sembuh", finding.message)

    # 3. draft valid -> lolos
    def test_valid_draft_passes_compliance(self) -> None:
        draft = ContentDraft(
            id="draft_003",
            product_id=self.sample_product.id,
            angle="Ergonomics",
            hook="Masih betah pakai headset kabel kusut waktu kerja?",
            script="Earphone nirkabel ini punya bantalan empuk dan noise reduction jernih.",
            caption="Rekomendasi setup kerja minimalis. Cek tautan di profil. #ShopeeAffiliate #KontenAI",
            cta="Dapatkan promonya sebelum kupon habis di link bio.",
            disclosure_text="Konten kemitraan berbayar #ShopeeAffiliate #KontenAI",
            status="draft",
            prompt_version="v1.0",
        )

        self.db.insert_product(self.sample_product)
        self.db.upsert_draft(draft)
        report = check_compliance(
            db=self.db,
            draft=draft,
            product=self.sample_product,
            config_path=CONFIG_PATH,
        )

        self.assertTrue(report.passed)
        error_findings = [f for f in report.findings if f.severity == "ERROR"]
        self.assertEqual(len(error_findings), 0)

    # 4. klaim tanpa sumber -> UNVERIFIED
    def test_claim_without_source_is_unverified(self) -> None:
        claims = [
            Claim(
                id="claim_001",
                draft_id="draft_004",
                text="Baterai tahan 48 jam nonstop.",
                source_ref=None,  # No source provided
            ),
            Claim(
                id="claim_002",
                draft_id="draft_004",
                text="Sertifikasi IPX5 tahan cipratan air.",
                source_ref="https://brand-spec.com/datasheet.pdf",  # Sourced
            ),
        ]

        evaluated = check_claims(db=self.db, claims=claims)

        claim_1 = next(c for c in evaluated if c.id == "claim_001")
        claim_2 = next(c for c in evaluated if c.id == "claim_002")

        self.assertEqual(claim_1.verification_status, "UNVERIFIED")
        self.assertEqual(claim_2.verification_status, "SOURCED")

    # 5. input produk dengan URL sama dua kali -> kedua kali tidak menghasilkan duplikat
    def test_duplicate_product_url_does_not_duplicate(self) -> None:
        # First intake
        prod_1, created_1 = intake_product(self.db, self.sample_product)
        self.assertTrue(created_1)
        self.assertEqual(prod_1.id, "prod_001")

        # Second intake with same URL but different ID and updated notes
        duplicate_candidate = Product(
            id="prod_002_duplicate",
            name="Earphone Serupa Tapi URL Sama",
            url=self.sample_product.url,  # Exactly the same URL
            price=120000.0,
            price_observed_at=datetime.now(timezone.utc),
            source="manual",
            notes="Percobaan input duplikat.",
        )

        prod_2, created_2 = intake_product(self.db, duplicate_candidate)
        self.assertFalse(created_2)
        # Should return the existing product record
        self.assertEqual(prod_2.id, "prod_001")

        # Verify database table has exactly 1 row
        conn = self.db.get_connection()
        cursor = conn.execute("SELECT COUNT(*) as cnt FROM products")
        count = cursor.fetchone()["cnt"]
        self.assertEqual(count, 1)

    # 6. menjalankan orchestrator dua kali pada draft yang sama -> tidak menggandakan record/event berlebihan
    def test_orchestrator_run_twice_idempotence(self) -> None:
        draft = ContentDraft(
            id="draft_idem_001",
            product_id=self.sample_product.id,
            angle="Durability",
            hook="Tahan jatuh dan anti air!",
            script="Earphone ini kokoh dan bersuara jernih.",
            caption="Tautan produk di bio #ShopeeAffiliate",
            cta="Beli sekarang di link bio",
            disclosure_text="#ShopeeAffiliate #KontenAI",
            status="draft",
            prompt_version="v1.0",
        )

        # Run 1
        result_1 = run_pipeline(
            db=self.db,
            product=self.sample_product,
            draft=draft,
            config_path=CONFIG_PATH,
        )
        self.assertEqual(result_1.draft.status, "waiting_approval")

        # Run 2 on same draft
        result_2 = run_pipeline(
            db=self.db,
            product=self.sample_product,
            draft=draft,
            config_path=CONFIG_PATH,
        )
        self.assertEqual(result_2.draft.status, "waiting_approval")

        # Verify content_drafts table has exactly 1 row for this draft & prompt_version
        conn = self.db.get_connection()
        cursor = conn.execute(
            "SELECT COUNT(*) as cnt FROM content_drafts WHERE id = ? AND prompt_version = ?",
            (draft.id, draft.prompt_version),
        )
        draft_count = cursor.fetchone()["cnt"]
        self.assertEqual(draft_count, 1)

    # 7. nilai PerformanceRecord yang tidak diketahui tetap None, bukan 0
    def test_performance_record_unknown_fields_remain_none(self) -> None:
        # Create record with unknown metrics
        record = PerformanceRecord(
            content_id="draft_idem_001",
            platform="Shopee Video",
            data_source="manual",
            # views, clicks, orders, commission_idr are omitted (unknown)
        )

        self.assertIsNone(record.views)
        self.assertIsNone(record.clicks)
        self.assertIsNone(record.orders)
        self.assertIsNone(record.commission_idr)

        # Persist to database and retrieve
        self.db.save_performance_record("perf_rec_001", record)
        retrieved = self.db.get_performance_record("perf_rec_001")

        self.assertIsNotNone(retrieved)
        self.assertIsNone(retrieved.views)
        self.assertIsNone(retrieved.clicks)
        self.assertIsNone(retrieved.orders)
        self.assertIsNone(retrieved.commission_idr)
        self.assertEqual(retrieved.platform, "Shopee Video")


if __name__ == "__main__":
    unittest.main()

