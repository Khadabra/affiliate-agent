"""Unit and regression tests for Human Review Gate and Content Pack Exporter.

Covers:
- Safe review semantics (approval of valid waiting draft, repeated idempotent calls)
- Rejection with mandatory reason and rejection idempotency
- Blocked approval on unverified claims, unreviewed sourced claims, rejected claims, and failing compliance
- Blocked invalid state transitions (e.g. approve rejected, reject approved)
- Individual claim review with audit logging
- Export gate enforcement (blocks waiting, rejected, and draft statuses)
- Content pack generation and validation of all 6 generated files and SHA-256 manifest
- Path traversal rejection in draft ID
- Explicit collision handling (fail without overwrite, succeed with overwrite)
- Atomic staging failure safety (no incomplete pack or false export event)
- Database migration test for compliance_reports composite primary key
- CLI smoke tests for review and export subcommands
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from affiliate_factory.cli import main
from affiliate_factory.db import Database
from affiliate_factory.exporter import (
    ExportCollisionError,
    ExportGateError,
    compute_file_sha256,
    export_content_pack,
    sanitize_draft_id,
)
from affiliate_factory.models import (
    Claim,
    ComplianceFinding,
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


class TestReviewAndExport(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_review_export.db"
        self.db = Database(self.db_path)

        self.sample_product = Product(
            id="prod_rev_01",
            name="Ring Light LED 26cm Tripod",
            url="https://shopee.co.id/ring-light-26cm",
            price=85000.0,
            price_observed_at=datetime.now(timezone.utc),
            source="manual",
            notes="3 mode warna, 10 tingkat kecerahan, USB 5V.",
        )
        self.db.insert_product(self.sample_product)

        self.sample_draft = ContentDraft(
            id="draft_rev_01",
            product_id=self.sample_product.id,
            angle="Lighting Setup",
            hook="Video buram dan gelap bikin penonton kabur?",
            script="Ring light 26cm ini punya 3 mode cahaya dan 10 level terang.",
            caption="Upgrade pencahayaan live dan video kamu sekarang! #ShopeeAffiliate #KontenAI",
            cta="Beli di keranjang kuning profil sekarang!",
            disclosure_text="#ShopeeAffiliate #KontenAI",
            status="waiting_approval",
            prompt_version="v1.0",
        )
        self.db.upsert_draft(self.sample_draft)

        self.sample_compliance = ComplianceReport(
            draft_id=self.sample_draft.id,
            prompt_version=self.sample_draft.prompt_version,
            passed=True,
            findings=[],
        )
        self.db.save_compliance_report(self.sample_compliance)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # 1. Approve a valid waiting draft
    def test_approve_valid_waiting_draft(self) -> None:
        # Create a sourced claim and review it to VERIFIED
        claim = Claim(
            id="claim_01",
            draft_id=self.sample_draft.id,
            text="Diameter ring light 26 cm",
            source_ref=self.sample_product.url,
            verification_status="SOURCED",
        )
        self.db.save_claims([claim])
        review_claim(self.db, claim.id, "VERIFIED", reviewer_note="Checked spec sheet")

        approved = approve_draft(
            self.db,
            self.sample_draft.id,
            prompt_version=self.sample_draft.prompt_version,
            reviewer_note="Looks great and compliant",
        )
        self.assertEqual(approved.status, "approved")

        saved = self.db.get_draft(self.sample_draft.id, self.sample_draft.prompt_version)
        self.assertEqual(saved.status, "approved")

        # Verify audit event
        events = self.db.list_events()
        approve_event = next((e for e in events if e.action == "human_approve"), None)
        self.assertIsNotNone(approve_event)
        self.assertEqual(approve_event.status, "succeeded")
        self.assertEqual(approve_event.ref_id, self.sample_draft.id)

    # 2. Re-approval is idempotent
    def test_approve_idempotent(self) -> None:
        self.db.update_draft_status(self.sample_draft.id, self.sample_draft.prompt_version, "approved")
        approved_again = approve_draft(
            self.db,
            self.sample_draft.id,
            prompt_version=self.sample_draft.prompt_version,
        )
        self.assertEqual(approved_again.status, "approved")

    # 3. Reject an eligible draft and record a reason
    def test_reject_eligible_draft_and_record_reason(self) -> None:
        rejected = reject_draft(
            self.db,
            self.sample_draft.id,
            reason="Hook terlalu agresif, tolong perbaiki gaya bahasanya.",
            prompt_version=self.sample_draft.prompt_version,
        )
        self.assertEqual(rejected.status, "rejected")

        saved = self.db.get_draft(self.sample_draft.id, self.sample_draft.prompt_version)
        self.assertEqual(saved.status, "rejected")

        # Verify audit event
        events = self.db.list_events()
        reject_event = next((e for e in events if e.action == "human_reject"), None)
        self.assertIsNotNone(reject_event)
        self.assertIn("Hook terlalu agresif", reject_event.note)

        # Idempotent re-rejection
        rejected_again = reject_draft(
            self.db,
            self.sample_draft.id,
            reason="Repeated rejection",
            prompt_version=self.sample_draft.prompt_version,
        )
        self.assertEqual(rejected_again.status, "rejected")

    # 4. Reject requires non-empty reason
    def test_reject_empty_reason_blocked(self) -> None:
        with self.assertRaises(ReviewError) as ctx:
            reject_draft(self.db, self.sample_draft.id, reason="   ")
        self.assertIn("non-empty reason is required", str(ctx.exception))

    # 5. Prevent approval with unresolved required claims (UNVERIFIED or SOURCED)
    def test_prevent_approval_with_unresolved_claims(self) -> None:
        # Case A: UNVERIFIED claim
        draft_unver = ContentDraft(
            id="draft_test_unver",
            product_id=self.sample_product.id,
            angle="Angle",
            hook="Hook",
            script="Script",
            caption="Caption",
            cta="CTA",
            disclosure_text="#ShopeeAffiliate",
            status="waiting_approval",
            prompt_version="v1.0",
        )
        self.db.upsert_draft(draft_unver)
        self.db.save_compliance_report(
            ComplianceReport(draft_id="draft_test_unver", prompt_version="v1.0", passed=True)
        )
        claim_unverified = Claim(
            id="claim_unver",
            draft_id="draft_test_unver",
            text="Baterai tahan 7 hari",
            source_ref=None,
            verification_status="UNVERIFIED",
        )
        self.db.save_claims([claim_unverified])

        with self.assertRaises(ReviewError) as ctx:
            approve_draft(self.db, "draft_test_unver")
        self.assertIn("UNVERIFIED", str(ctx.exception))

        # Case B: SOURCED claim but not explicitly verified by human
        draft_src = ContentDraft(
            id="draft_test_src",
            product_id=self.sample_product.id,
            angle="Angle",
            hook="Hook",
            script="Script",
            caption="Caption",
            cta="CTA",
            disclosure_text="#ShopeeAffiliate",
            status="waiting_approval",
            prompt_version="v1.0",
        )
        self.db.upsert_draft(draft_src)
        self.db.save_compliance_report(
            ComplianceReport(draft_id="draft_test_src", prompt_version="v1.0", passed=True)
        )
        claim_sourced = Claim(
            id="claim_src",
            draft_id="draft_test_src",
            text="Diameter 26 cm",
            source_ref="https://shopee.co.id/ring-light-26cm",
            verification_status="SOURCED",
        )
        self.db.save_claims([claim_sourced])

        with self.assertRaises(ReviewError) as ctx:
            approve_draft(self.db, "draft_test_src")
        self.assertIn("SOURCED", str(ctx.exception))
        self.assertIn("not been explicitly human-verified", str(ctx.exception))

    # 6. Prevent approval with rejected claims
    def test_prevent_approval_with_rejected_claims(self) -> None:
        claim_rej = Claim(
            id="claim_bad",
            draft_id=self.sample_draft.id,
            text="Pasti viral setelah pakai ini",
            source_ref=None,
            verification_status="REJECTED",
        )
        self.db.save_claims([claim_rej])

        with self.assertRaises(ReviewError) as ctx:
            approve_draft(self.db, self.sample_draft.id)
        self.assertIn("REJECTED", str(ctx.exception))

    # 7. Prevent approval with blocking compliance findings
    def test_prevent_approval_with_blocking_compliance_findings(self) -> None:
        bad_compliance = ComplianceReport(
            draft_id=self.sample_draft.id,
            prompt_version=self.sample_draft.prompt_version,
            passed=False,
            findings=[
                ComplianceFinding(
                    rule_id="RULE-PROHIBITED-CLAIMS-01",
                    severity="ERROR",
                    message="Dilarang klaim mutlak.",
                )
            ],
        )
        self.db.save_compliance_report(bad_compliance)

        with self.assertRaises(ReviewError) as ctx:
            approve_draft(self.db, self.sample_draft.id)
        self.assertIn("compliance evaluation failed", str(ctx.exception))

    # 8. Prevent invalid state transitions
    def test_prevent_invalid_state_transitions(self) -> None:
        # Cannot approve a rejected draft
        self.db.update_draft_status(self.sample_draft.id, self.sample_draft.prompt_version, "rejected")
        with self.assertRaises(ReviewError) as ctx:
            approve_draft(self.db, self.sample_draft.id)
        self.assertIn("REJECTED", str(ctx.exception))

        # Cannot reject an approved draft
        self.db.update_draft_status(self.sample_draft.id, self.sample_draft.prompt_version, "approved")
        with self.assertRaises(ReviewError) as ctx:
            reject_draft(self.db, self.sample_draft.id, reason="Changed mind")
        self.assertIn("APPROVED", str(ctx.exception))

        # Cannot approve draft in raw 'draft' status
        self.db.update_draft_status(self.sample_draft.id, self.sample_draft.prompt_version, "draft")
        with self.assertRaises(ReviewError) as ctx:
            approve_draft(self.db, self.sample_draft.id)
        self.assertIn("waiting_approval", str(ctx.exception))

    # 9. Individual claim review and audit event
    def test_review_claim_individually(self) -> None:
        claim = Claim(
            id="claim_individual",
            draft_id=self.sample_draft.id,
            text="Port USB 5V",
            source_ref=self.sample_product.url,
            verification_status="SOURCED",
        )
        self.db.save_claims([claim])

        updated = review_claim(
            self.db,
            claim_id="claim_individual",
            status="VERIFIED",
            reviewer_note="Verified against product box photo",
        )
        self.assertEqual(updated.verification_status, "VERIFIED")

        saved_claim = self.db.get_claim("claim_individual")
        self.assertEqual(saved_claim.verification_status, "VERIFIED")

        events = self.db.list_events()
        claim_event = next((e for e in events if e.action == "review_claim"), None)
        self.assertIsNotNone(claim_event)
        self.assertIn("Verified against product box photo", claim_event.note)

    # 10. Prevent export of waiting, rejected, or draft statuses
    def test_prevent_export_of_unapproved_drafts(self) -> None:
        # Status waiting_approval
        with self.assertRaises(ExportGateError) as ctx:
            export_content_pack(self.db, self.sample_draft.id)
        self.assertIn("waiting_approval", str(ctx.exception))

        # Status rejected
        self.db.update_draft_status(self.sample_draft.id, self.sample_draft.prompt_version, "rejected")
        with self.assertRaises(ExportGateError) as ctx:
            export_content_pack(self.db, self.sample_draft.id)
        self.assertIn("rejected", str(ctx.exception))

        # Status draft
        self.db.update_draft_status(self.sample_draft.id, self.sample_draft.prompt_version, "draft")
        with self.assertRaises(ExportGateError) as ctx:
            export_content_pack(self.db, self.sample_draft.id)
        self.assertIn("draft", str(ctx.exception))

    # 11. Export approved draft and validate every generated file
    def test_export_approved_draft_and_validate_all_files(self) -> None:
        self.db.update_draft_status(self.sample_draft.id, self.sample_draft.prompt_version, "approved")

        claim = Claim(
            id="claim_exp_01",
            draft_id=self.sample_draft.id,
            text="Ring Light 26 cm",
            source_ref=self.sample_product.url,
            verification_status="VERIFIED",
        )
        self.db.save_claims([claim])

        packs_dir = Path(self.temp_dir.name) / "output" / "packs"
        exported_path = export_content_pack(
            self.db,
            draft_id=self.sample_draft.id,
            prompt_version=self.sample_draft.prompt_version,
            base_output_dir=packs_dir,
        )

        self.assertTrue(exported_path.exists())
        self.assertEqual(exported_path, packs_dir / self.sample_draft.id)

        # Validate all 6 files
        expected_files = [
            "script.md",
            "caption.txt",
            "hashtags.txt",
            "product_info.json",
            "review_checklist.md",
            "manifest.json",
        ]
        for fname in expected_files:
            fpath = exported_path / fname
            self.assertTrue(fpath.exists(), f"Missing file: {fname}")
            self.assertGreater(fpath.stat().st_size, 0)

        # Inspect manifest.json
        with open(exported_path / "manifest.json", "r", encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertEqual(manifest["status"], "APPROVED_AND_EXPORTED")
        self.assertEqual(manifest["draft_id"], self.sample_draft.id)
        self.assertIn("script.md", manifest["files"])
        self.assertEqual(manifest["files"]["script.md"]["sha256"], compute_file_sha256(exported_path / "script.md"))

        # Inspect review_checklist.md
        with open(exported_path / "review_checklist.md", "r", encoding="utf-8") as f:
            checklist = f.read()
        self.assertIn("CATATAN BUKTI SUMBER", checklist)
        self.assertIn("Keberadaan URL sumber dicatat", checklist)
        self.assertIn("Ring Light 26 cm", checklist)

        # Inspect audit event in DB
        events = self.db.list_events()
        export_event = next((e for e in events if e.action == "export_pack"), None)
        self.assertIsNotNone(export_event)
        self.assertEqual(export_event.status, "succeeded")

    # 12. Path traversal rejection in draft ID
    def test_reject_path_traversal_in_draft_id(self) -> None:
        traversal_ids = [
            "../secret",
            "..\\windows\\system32",
            "draft/sub",
            "draft\\sub",
            "draft\0bad",
            "draft name with spaces",
            "",
        ]
        for bad_id in traversal_ids:
            with self.assertRaises(ValueError):
                sanitize_draft_id(bad_id)

    # 13. Output collision handling
    def test_handle_output_collisions_safely(self) -> None:
        self.db.update_draft_status(self.sample_draft.id, self.sample_draft.prompt_version, "approved")
        packs_dir = Path(self.temp_dir.name) / "output" / "packs"

        # First export succeeds
        export_content_pack(
            self.db,
            self.sample_draft.id,
            base_output_dir=packs_dir,
        )

        # Second export without overwrite raises ExportCollisionError
        with self.assertRaises(ExportCollisionError) as ctx:
            export_content_pack(
                self.db,
                self.sample_draft.id,
                base_output_dir=packs_dir,
                overwrite=False,
            )
        self.assertIn("already exists", str(ctx.exception))

        # Third export with overwrite succeeds
        re_exported = export_content_pack(
            self.db,
            self.sample_draft.id,
            base_output_dir=packs_dir,
            overwrite=True,
        )
        self.assertTrue(re_exported.exists())

    # 14. Atomic write failure safety: no incomplete pack or false export event
    def test_failed_export_leaves_no_misleading_pack_or_event(self) -> None:
        self.db.update_draft_status(self.sample_draft.id, self.sample_draft.prompt_version, "approved")
        packs_dir = Path(self.temp_dir.name) / "output" / "packs"

        # Simulate missing product to trigger failure during staging
        bad_draft = ContentDraft(
            id="draft_missing_prod",
            product_id="prod_non_existent",
            angle="Angle",
            hook="Hook",
            script="Script",
            caption="Caption",
            cta="CTA",
            disclosure_text="#ShopeeAffiliate",
            status="approved",
            prompt_version="v1.0",
        )
        self.db.upsert_draft(bad_draft)
        self.db.save_compliance_report(
            ComplianceReport(draft_id="draft_missing_prod", prompt_version="v1.0", passed=True)
        )

        with self.assertRaises(ExportGateError):
            export_content_pack(self.db, "draft_missing_prod", base_output_dir=packs_dir)

        # Target directory must NOT exist
        target_dir = packs_dir / "draft_missing_prod"
        self.assertFalse(target_dir.exists())

        # No export_pack event for this draft
        events = self.db.list_events()
        bad_event = next(
            (e for e in events if e.action == "export_pack" and e.ref_id == "draft_missing_prod"), None
        )
        self.assertIsNone(bad_event)

    # 15. Database migration test for compliance_reports composite primary key
    def test_database_migration_compliance_reports(self) -> None:
        legacy_db_file = Path(self.temp_dir.name) / "legacy_test.db"

        # Create a legacy database manually with single draft_id primary key
        conn = sqlite3.connect(legacy_db_file)
        conn.executescript(
            """
            CREATE TABLE compliance_reports (
                draft_id TEXT PRIMARY KEY,
                passed INTEGER NOT NULL,
                findings_json TEXT NOT NULL
            );
            INSERT INTO compliance_reports (draft_id, passed, findings_json)
            VALUES ('draft_legacy_01', 1, '[]');
            """
        )
        conn.close()

        # Opening Database initializes schema and triggers transparent migration
        migrated_db = Database(legacy_db_file)

        # Check that table now has prompt_version column and composite key
        conn = migrated_db.get_connection()
        try:
            cols = {row["name"] for row in conn.execute("PRAGMA table_info(compliance_reports)").fetchall()}
            self.assertIn("prompt_version", cols)
        finally:
            conn.close()

        # Verify legacy row is preserved with prompt_version='v1.0'
        report_v1 = migrated_db.get_compliance_report("draft_legacy_01", "v1.0")
        self.assertIsNotNone(report_v1)
        self.assertTrue(report_v1.passed)

        # Verify that inserting a v2.0 report for the same draft_id works without overwriting v1.0
        report_v2 = ComplianceReport(
            draft_id="draft_legacy_01",
            prompt_version="v2.0",
            passed=False,
            findings=[ComplianceFinding(rule_id="RULE-AI-01", severity="WARNING", message="Label missing")],
        )
        migrated_db.save_compliance_report(report_v2)

        retrieved_v1 = migrated_db.get_compliance_report("draft_legacy_01", "v1.0")
        retrieved_v2 = migrated_db.get_compliance_report("draft_legacy_01", "v2.0")

        self.assertTrue(retrieved_v1.passed)
        self.assertFalse(retrieved_v2.passed)
        self.assertEqual(len(retrieved_v2.findings), 1)

    # 16. CLI Smoke Tests: review show, review claim, review approve, review reject, export
    def test_cli_review_and_export_smoke(self) -> None:
        # CLI review show
        code_show = main(["review", "show", "--draft-id", self.sample_draft.id, "--db", str(self.db_path)])
        self.assertEqual(code_show, 0)

        # Create and review a claim via CLI
        claim = Claim(
            id="claim_cli_01",
            draft_id=self.sample_draft.id,
            text="3 mode warna",
            source_ref=self.sample_product.url,
            verification_status="SOURCED",
        )
        self.db.save_claims([claim])

        code_claim = main([
            "review",
            "claim",
            "--claim-id",
            "claim_cli_01",
            "--status",
            "VERIFIED",
            "--note",
            "Checked packaging",
            "--db",
            str(self.db_path),
        ])
        self.assertEqual(code_claim, 0)

        # CLI review approve
        code_approve = main([
            "review",
            "approve",
            "--draft-id",
            self.sample_draft.id,
            "--note",
            "Approved via CLI test",
            "--db",
            str(self.db_path),
        ])
        self.assertEqual(code_approve, 0)

        # CLI export
        out_packs = Path(self.temp_dir.name) / "cli_packs"
        code_export = main([
            "export",
            "--draft-id",
            self.sample_draft.id,
            "--output-dir",
            str(out_packs),
            "--db",
            str(self.db_path),
        ])
        self.assertEqual(code_export, 0)
        self.assertTrue((out_packs / self.sample_draft.id / "manifest.json").exists())

        # CLI review reject on a separate draft
        draft_reject = ContentDraft(
            id="draft_for_rejection",
            product_id=self.sample_product.id,
            angle="Angle",
            hook="Hook",
            script="Script",
            caption="Caption",
            cta="CTA",
            disclosure_text="#ShopeeAffiliate",
            status="waiting_approval",
            prompt_version="v1.0",
        )
        self.db.upsert_draft(draft_reject)

        code_reject = main([
            "review",
            "reject",
            "--draft-id",
            "draft_for_rejection",
            "--reason",
            "Kualitas audio tidak sesuai standar.",
            "--db",
            str(self.db_path),
        ])
        self.assertEqual(code_reject, 0)
        saved_reject = self.db.get_draft("draft_for_rejection", "v1.0")
        self.assertEqual(saved_reject.status, "rejected")


if __name__ == "__main__":
    unittest.main()
