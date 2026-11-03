"""Unit and regression tests for Phase 1.1 Review Gate and Draft Version Isolation.

Verifies:
- Claims are strictly isolated by draft version:
  - Same draft ID with distinct prompt versions (v1.0 vs v2.0)
  - v1 unverified claims do not block v2 approval
  - v2 export contains ONLY v2 claims and never leaks v1 claims
- Review state invariants:
  - Claims of approved drafts cannot be modified
  - Claims of rejected drafts cannot be reviewed
  - expected_prompt_version mismatch raises ReviewError
  - Fail-closed: SOURCED claims require explicit human verification
- Exporter safety:
  - Symlink target rejection
  - Safe overwrite preserves original pack intact if replacement fails
  - Path traversal protection
- Database migration:
  - Legacy claims table without prompt_version migrated safely
  - Single-version draft claims associated unambiguously
  - Multi-version and orphan draft claims remain NULL (no fabrication)
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from affiliate_factory.db import Database
from affiliate_factory.exporter import (
    ExportCollisionError,
    ExportGateError,
    export_content_pack,
)
from affiliate_factory.models import (
    Claim,
    ComplianceReport,
    ContentDraft,
    Product,
)
from affiliate_factory.review import (
    ReviewError,
    approve_draft,
    reject_draft,
    review_claim,
)


class TestPhase11Isolation(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_phase1_1.db"
        self.db = Database(self.db_path)

        self.product = Product(
            id="prod_multi_01",
            name="Wireless Lavalier Microphone",
            url="https://shopee.co.id/wireless-lavalier-mic",
            price=125000.0,
            price_observed_at=datetime.now(timezone.utc),
            source="manual",
            notes="Noise reduction chip, 20m range.",
        )
        self.db.insert_product(self.product)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_claims_isolated_across_prompt_versions_for_same_draft_id(self) -> None:
        """v1 unverified claim must not block v2 approval when sharing same draft ID."""
        # 1. Create v1.0 draft (compliant, waiting_approval) with UNVERIFIED claim
        draft_v1 = ContentDraft(
            id="draft_multi_01",
            product_id=self.product.id,
            angle="Problem-Benefit",
            hook="Suara video kamu kresek-kresek?",
            script="Mic lavalier ini bikin suara jernih sampai jarak 50 meter.",
            caption="Mic wireless murah terbaik! #ShopeeAffiliate #KontenAI",
            cta="Cek keranjang kuning sekarang!",
            disclosure_text="#ShopeeAffiliate #KontenAI",
            status="waiting_approval",
            prompt_version="v1.0",
        )
        self.db.upsert_draft(draft_v1)
        self.db.save_compliance_report(
            ComplianceReport(draft_id="draft_multi_01", prompt_version="v1.0", passed=True)
        )
        claim_v1 = Claim(
            id="claim_multi_v1_1",
            draft_id="draft_multi_01",
            prompt_version="v1.0",
            text="Jarak transmisi 50 meter",
            source_ref=None,
            verification_status="UNVERIFIED",
        )
        self.db.save_claims([claim_v1])

        # 2. Create v2.0 draft (compliant, waiting_approval) with SOURCED claim
        draft_v2 = ContentDraft(
            id="draft_multi_01",
            product_id=self.product.id,
            angle="Problem-Benefit",
            hook="Suara video kamu kresek-kresek?",
            script="Mic lavalier ini punya chip peredam bising dengan jarak 20 meter.",
            caption="Mic wireless murah terbaik! #ShopeeAffiliate #KontenAI",
            cta="Cek keranjang kuning sekarang!",
            disclosure_text="#ShopeeAffiliate #KontenAI",
            status="waiting_approval",
            prompt_version="v2.0",
        )
        self.db.upsert_draft(draft_v2)
        self.db.save_compliance_report(
            ComplianceReport(draft_id="draft_multi_01", prompt_version="v2.0", passed=True)
        )
        claim_v2 = Claim(
            id="claim_multi_v2_1",
            draft_id="draft_multi_01",
            prompt_version="v2.0",
            text="Jarak transmisi 20 meter",
            source_ref="https://shopee.co.id/wireless-lavalier-mic",
            verification_status="SOURCED",
        )
        self.db.save_claims([claim_v2])

        # Human reviews ONLY the v2 claim
        review_claim(
            self.db,
            claim_id="claim_multi_v2_1",
            status="VERIFIED",
            reviewer_note="Verified on product specification sheet",
            expected_prompt_version="v2.0",
        )

        # Approving v2 must SUCCEED even though v1 has an UNVERIFIED claim
        approved_v2 = approve_draft(self.db, "draft_multi_01", prompt_version="v2.0")
        self.assertEqual(approved_v2.status, "approved")

        # Approving v1 must FAIL because v1 still contains the UNVERIFIED claim
        with self.assertRaises(ReviewError) as ctx:
            approve_draft(self.db, "draft_multi_01", prompt_version="v1.0")
        self.assertIn("UNVERIFIED", str(ctx.exception))
        self.assertIn("Jarak transmisi 50 meter", str(ctx.exception))

    def test_export_of_v2_never_includes_v1_claims(self) -> None:
        """Exporting v2 content pack must only contain v2 claims in review_checklist.md."""
        draft_v1 = ContentDraft(
            id="draft_export_iso",
            product_id=self.product.id,
            angle="Angle 1",
            hook="Hook 1",
            script="Script 1 with 50m claim",
            caption="Caption 1 #ShopeeAffiliate #KontenAI",
            cta="CTA 1",
            disclosure_text="#ShopeeAffiliate #KontenAI",
            status="waiting_approval",
            prompt_version="v1.0",
        )
        self.db.upsert_draft(draft_v1)
        self.db.save_compliance_report(
            ComplianceReport(draft_id="draft_export_iso", prompt_version="v1.0", passed=True)
        )
        claim_v1 = Claim(
            id="claim_exp_iso_v1",
            draft_id="draft_export_iso",
            prompt_version="v1.0",
            text="Baterai tahan 30 hari tanpa cas",
            source_ref=None,
            verification_status="UNVERIFIED",
        )
        self.db.save_claims([claim_v1])

        draft_v2 = ContentDraft(
            id="draft_export_iso",
            product_id=self.product.id,
            angle="Angle 2",
            hook="Hook 2",
            script="Script 2 with verified claims",
            caption="Caption 2 #ShopeeAffiliate #KontenAI",
            cta="CTA 2",
            disclosure_text="#ShopeeAffiliate #KontenAI",
            status="waiting_approval",
            prompt_version="v2.0",
        )
        self.db.upsert_draft(draft_v2)
        self.db.save_compliance_report(
            ComplianceReport(draft_id="draft_export_iso", prompt_version="v2.0", passed=True)
        )
        claim_v2 = Claim(
            id="claim_exp_iso_v2",
            draft_id="draft_export_iso",
            prompt_version="v2.0",
            text="Baterai 8 jam pemakaian nonstop",
            source_ref="https://shopee.co.id/wireless-lavalier-mic",
            verification_status="SOURCED",
        )
        self.db.save_claims([claim_v2])

        review_claim(self.db, "claim_exp_iso_v2", "VERIFIED", reviewer_note="Checked manual")
        approve_draft(self.db, "draft_export_iso", prompt_version="v2.0")

        # Export v2 pack
        packs_dir = Path(self.temp_dir.name) / "packs"
        pack_path = export_content_pack(
            self.db,
            draft_id="draft_export_iso",
            prompt_version="v2.0",
            base_output_dir=packs_dir,
        )

        checklist_content = (pack_path / "review_checklist.md").read_text(encoding="utf-8")
        self.assertIn("Baterai 8 jam pemakaian nonstop", checklist_content)
        self.assertNotIn("Baterai tahan 30 hari tanpa cas", checklist_content)

    def test_cannot_modify_claims_of_approved_draft(self) -> None:
        """Claims associated with an approved draft cannot be modified."""
        draft = ContentDraft(
            id="draft_approved_guard",
            product_id=self.product.id,
            angle="Angle",
            hook="Hook",
            script="Script",
            caption="Caption #ShopeeAffiliate #KontenAI",
            cta="CTA",
            disclosure_text="#ShopeeAffiliate #KontenAI",
            status="waiting_approval",
            prompt_version="v1.0",
        )
        self.db.upsert_draft(draft)
        self.db.save_compliance_report(
            ComplianceReport(draft_id="draft_approved_guard", prompt_version="v1.0", passed=True)
        )
        claim = Claim(
            id="claim_guard_01",
            draft_id="draft_approved_guard",
            prompt_version="v1.0",
            text="Port Type-C",
            source_ref=self.product.url,
            verification_status="SOURCED",
        )
        self.db.save_claims([claim])

        review_claim(self.db, "claim_guard_01", "VERIFIED")
        approve_draft(self.db, "draft_approved_guard", prompt_version="v1.0")

        # Attempting to modify claim after approval must be blocked
        with self.assertRaises(ReviewError) as ctx:
            review_claim(self.db, "claim_guard_01", "REJECTED")
        self.assertIn("already APPROVED", str(ctx.exception))

    def test_cannot_review_claims_of_rejected_draft(self) -> None:
        """Claims associated with a rejected draft cannot be reviewed."""
        draft = ContentDraft(
            id="draft_rejected_guard",
            product_id=self.product.id,
            angle="Angle",
            hook="Hook",
            script="Script",
            caption="Caption #ShopeeAffiliate #KontenAI",
            cta="CTA",
            disclosure_text="#ShopeeAffiliate #KontenAI",
            status="waiting_approval",
            prompt_version="v1.0",
        )
        self.db.upsert_draft(draft)
        self.db.save_compliance_report(
            ComplianceReport(draft_id="draft_rejected_guard", prompt_version="v1.0", passed=True)
        )
        claim = Claim(
            id="claim_rej_guard_01",
            draft_id="draft_rejected_guard",
            prompt_version="v1.0",
            text="Noise cancellation aktif",
            source_ref=self.product.url,
            verification_status="SOURCED",
        )
        self.db.save_claims([claim])

        reject_draft(self.db, "draft_rejected_guard", reason="Script audio quality is poor")

        # Attempting to review claim of rejected draft must be blocked
        with self.assertRaises(ReviewError) as ctx:
            review_claim(self.db, "claim_rej_guard_01", "VERIFIED")
        self.assertIn("is REJECTED", str(ctx.exception))

    def test_expected_prompt_version_mismatch_raises_error(self) -> None:
        """Reviewing a claim with an mismatched expected prompt version raises ReviewError."""
        claim = Claim(
            id="claim_ver_mismatch",
            draft_id="draft_ver_test",
            prompt_version="v2.0",
            text="Testing version mismatch",
            source_ref=self.product.url,
            verification_status="SOURCED",
        )
        self.db.save_claims([claim])

        with self.assertRaises(ReviewError) as ctx:
            review_claim(
                self.db,
                claim_id="claim_ver_mismatch",
                status="VERIFIED",
                expected_prompt_version="v1.0",
            )
        self.assertIn("belongs to prompt version 'v2.0', but expected 'v1.0'", str(ctx.exception))

    def test_fail_closed_sourced_claim_without_human_verification_blocks_approval(self) -> None:
        """A claim with a source URL is SOURCED, not VERIFIED; approval must fail closed."""
        draft = ContentDraft(
            id="draft_fail_closed",
            product_id=self.product.id,
            angle="Angle",
            hook="Hook",
            script="Script",
            caption="Caption #ShopeeAffiliate #KontenAI",
            cta="CTA",
            disclosure_text="#ShopeeAffiliate #KontenAI",
            status="waiting_approval",
            prompt_version="v1.0",
        )
        self.db.upsert_draft(draft)
        self.db.save_compliance_report(
            ComplianceReport(draft_id="draft_fail_closed", prompt_version="v1.0", passed=True)
        )
        claim = Claim(
            id="claim_fc_01",
            draft_id="draft_fail_closed",
            prompt_version="v1.0",
            text="Radius 20m",
            source_ref="https://shopee.co.id/item",
            verification_status="SOURCED",
        )
        self.db.save_claims([claim])

        # Attempting approval without human verification must fail
        with self.assertRaises(ReviewError) as ctx:
            approve_draft(self.db, "draft_fail_closed", prompt_version="v1.0")
        self.assertIn("SOURCED", str(ctx.exception))
        self.assertIn("not been explicitly human-verified", str(ctx.exception))

    def test_safe_overwrite_preserves_original_on_failure(self) -> None:
        """If overwrite fails midway, the original valid content pack must remain intact."""
        import os

        draft = ContentDraft(
            id="draft_overwrite_safety",
            product_id=self.product.id,
            angle="Angle",
            hook="Original Hook",
            script="Original Script Content",
            caption="Original Caption #ShopeeAffiliate #KontenAI",
            cta="Original CTA",
            disclosure_text="#ShopeeAffiliate #KontenAI",
            status="approved",
            prompt_version="v1.0",
        )
        self.db.upsert_draft(draft)
        self.db.save_compliance_report(
            ComplianceReport(draft_id="draft_overwrite_safety", prompt_version="v1.0", passed=True)
        )

        packs_dir = Path(self.temp_dir.name) / "safe_packs"
        original_pack = export_content_pack(
            self.db,
            draft_id="draft_overwrite_safety",
            prompt_version="v1.0",
            base_output_dir=packs_dir,
        )

        original_script_text = (original_pack / "script.md").read_text(encoding="utf-8")
        self.assertIn("Original Script Content", original_script_text)

        # Simulate failure during the atomic rename of staging_dir to target_dir
        real_os_rename = os.rename
        call_count = 0

        def rename_side_effect(src, dst):
            nonlocal call_count
            call_count += 1
            # Call 1: target_dir -> backup_dir (allow)
            # Call 2: staging_dir -> target_dir (simulate disk/permission error)
            # Call 3: backup_dir -> target_dir (rollback restore - allow)
            if call_count == 2:
                raise OSError("Simulated disk error during staging rename")
            return real_os_rename(src, dst)

        with patch("os.rename", side_effect=rename_side_effect):
            with self.assertRaises(OSError):
                export_content_pack(
                    self.db,
                    draft_id="draft_overwrite_safety",
                    prompt_version="v1.0",
                    base_output_dir=packs_dir,
                    overwrite=True,
                )

        # Confirm original content pack is restored and intact
        self.assertTrue(original_pack.exists())
        restored_script = (original_pack / "script.md").read_text(encoding="utf-8")
        self.assertEqual(restored_script, original_script_text)

    def test_symlink_target_rejection(self) -> None:
        """If the target content pack directory is a symlink, export must be rejected."""
        packs_dir = Path(self.temp_dir.name) / "symlink_packs"
        packs_dir.mkdir()
        real_target = packs_dir / "real_target"
        real_target.mkdir()
        target_dir = packs_dir / "draft_symlink_test"
        try:
            target_dir.symlink_to(real_target, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Filesystem symlink creation is unavailable: {exc}")

        with self.assertRaises(ValueError) as ctx:
            export_content_pack(
                self.db,
                draft_id="draft_symlink_test",
                prompt_version="v1.0",
                base_output_dir=packs_dir,
            )
        self.assertIn("symlink", str(ctx.exception).lower())
        self.assertTrue(target_dir.is_symlink())
        self.assertTrue(real_target.exists())

    def test_symlink_target_to_outside_base_is_rejected(self) -> None:
        packs_dir = Path(self.temp_dir.name) / "symlink_outside_packs"
        outside_dir = Path(self.temp_dir.name) / "outside_target"
        packs_dir.mkdir()
        outside_dir.mkdir()
        target_dir = packs_dir / "draft_symlink_outside"
        try:
            target_dir.symlink_to(outside_dir, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Filesystem symlink creation is unavailable: {exc}")

        with self.assertRaises(ValueError):
            export_content_pack(self.db, "draft_symlink_outside", base_output_dir=packs_dir)
        self.assertTrue(target_dir.is_symlink())
        self.assertTrue(outside_dir.exists())

    def test_broken_symlink_target_is_rejected(self) -> None:
        packs_dir = Path(self.temp_dir.name) / "broken_symlink_packs"
        packs_dir.mkdir()
        target_dir = packs_dir / "draft_broken_symlink"
        missing_target = packs_dir / "missing_target"
        try:
            target_dir.symlink_to(missing_target, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Filesystem symlink creation is unavailable: {exc}")

        with self.assertRaises(ValueError):
            export_content_pack(self.db, "draft_broken_symlink", base_output_dir=packs_dir)
        self.assertTrue(target_dir.is_symlink())
        self.assertFalse(missing_target.exists())

    def test_parent_directory_symlink_is_resolved_before_target_check(self) -> None:
        real_base = Path(self.temp_dir.name) / "real_base"
        real_base.mkdir()
        linked_base = Path(self.temp_dir.name) / "linked_base"
        try:
            linked_base.symlink_to(real_base, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Filesystem symlink creation is unavailable: {exc}")

        with self.assertRaises(ExportGateError):
            export_content_pack(self.db, "draft_under_parent_symlink", base_output_dir=linked_base)

    def test_database_migration_claims_prompt_version(self) -> None:
        """Legacy claims table without prompt_version must migrate safely without data loss.

        - Single-version draft: prompt_version is populated.
        - Multi-version draft: prompt_version remains NULL (not fabricated).
        - Orphan draft: prompt_version remains NULL (not fabricated).
        """
        legacy_db_path = Path(self.temp_dir.name) / "legacy_migration.db"
        conn = sqlite3.connect(str(legacy_db_path))
        try:
            with conn:
                conn.executescript(
                    """
                    CREATE TABLE products (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        url TEXT NOT NULL UNIQUE,
                        price REAL,
                        price_observed_at TEXT,
                        source TEXT NOT NULL,
                        notes TEXT
                    );
                    CREATE TABLE content_drafts (
                        id TEXT NOT NULL,
                        product_id TEXT NOT NULL,
                        angle TEXT NOT NULL,
                        hook TEXT NOT NULL,
                        script TEXT NOT NULL,
                        caption TEXT NOT NULL,
                        cta TEXT NOT NULL,
                        disclosure_text TEXT NOT NULL,
                        status TEXT NOT NULL,
                        prompt_version TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        PRIMARY KEY (id, prompt_version)
                    );
                    -- Legacy claims table without prompt_version column:
                    CREATE TABLE claims (
                        id TEXT PRIMARY KEY,
                        draft_id TEXT NOT NULL,
                        text TEXT NOT NULL,
                        source_ref TEXT,
                        verification_status TEXT NOT NULL
                    );

                    INSERT INTO products (id, name, url, source) VALUES ('p1', 'Product 1', 'https://shopee.co.id/p1', 'manual');

                    -- Draft 1 has exactly 1 version (v1.0)
                    INSERT INTO content_drafts (id, product_id, angle, hook, script, caption, cta, disclosure_text, status, prompt_version, created_at)
                    VALUES ('draft_single', 'p1', 'A', 'H', 'S', 'C', 'CTA', '#Shopee', 'waiting_approval', 'v1.0', '2026-01-01T00:00:00Z');

                    -- Draft 2 has 2 versions (v1.0 and v2.0)
                    INSERT INTO content_drafts (id, product_id, angle, hook, script, caption, cta, disclosure_text, status, prompt_version, created_at)
                    VALUES ('draft_multi', 'p1', 'A', 'H', 'S', 'C', 'CTA', '#Shopee', 'waiting_approval', 'v1.0', '2026-01-01T00:00:00Z');
                    INSERT INTO content_drafts (id, product_id, angle, hook, script, caption, cta, disclosure_text, status, prompt_version, created_at)
                    VALUES ('draft_multi', 'p1', 'A', 'H', 'S', 'C', 'CTA', '#Shopee', 'waiting_approval', 'v2.0', '2026-01-02T00:00:00Z');

                    -- Claims in legacy table
                    INSERT INTO claims (id, draft_id, text, source_ref, verification_status)
                    VALUES ('c_single', 'draft_single', 'Claim Single', 'https://ref1', 'SOURCED');

                    INSERT INTO claims (id, draft_id, text, source_ref, verification_status)
                    VALUES ('c_multi', 'draft_multi', 'Claim Multi', 'https://ref2', 'SOURCED');

                    INSERT INTO claims (id, draft_id, text, source_ref, verification_status)
                    VALUES ('c_orphan', 'draft_orphan', 'Claim Orphan', NULL, 'UNVERIFIED');
                    """
                )
        finally:
            conn.close()

        # Initialize Database on legacy DB, triggering init_schema migration
        migrated_db = Database(legacy_db_path)

        # Inspect resulting claims table
        migrated_conn = migrated_db.get_connection()
        try:
            # 1. Verify prompt_version column exists
            cols = {row["name"] for row in migrated_conn.execute("PRAGMA table_info(claims)").fetchall()}
            self.assertIn("prompt_version", cols)

            # 2. Check c_single: exactly 1 version in content_drafts -> must be 'v1.0'
            row_single = migrated_conn.execute("SELECT * FROM claims WHERE id = 'c_single'").fetchone()
            self.assertEqual(row_single["prompt_version"], "v1.0")

            # 3. Check c_multi: 2 versions in content_drafts -> must remain NULL (do NOT fabricate)
            row_multi = migrated_conn.execute("SELECT * FROM claims WHERE id = 'c_multi'").fetchone()
            self.assertIsNone(row_multi["prompt_version"])

            # 4. Check c_orphan: 0 versions in content_drafts -> must remain NULL (do NOT fabricate)
            row_orphan = migrated_conn.execute("SELECT * FROM claims WHERE id = 'c_orphan'").fetchone()
            self.assertIsNone(row_orphan["prompt_version"])
        finally:
            migrated_conn.close()


if __name__ == "__main__":
    unittest.main()
