"""End-to-end workflow verification for Phase 2.2.3."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from pydantic import ValidationError

from affiliate_factory.analytics import calculate_performance_summary
from affiliate_factory.angle_ranker import AngleRanker
from affiliate_factory.cli import main
from affiliate_factory.db import Database
from affiliate_factory.models import Product


class TestPhase223Workflow(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / "workflow.db"
        self.export_dir = self.root / "exports"
        self.product_id = "e2e_product_01"
        self.draft_id = "e2e_draft_01"

        self.product_payload = {
            "id": self.product_id,
            "name": "Tripod E2E Workflow",
            "url": "https://example.com/e2e-tripod",
            "price": 125000.0,
            "price_observed_at": "2026-11-03T10:00:00+00:00",
            "source": "manual",
            "notes": "Tinggi maksimal 1.5m dan remote bluetooth.",
        }
        self.product_file = self.root / "product.json"
        self.product_file.write_text(json.dumps(self.product_payload), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_cli(self, *args: str) -> tuple[int, str]:
        output = io.StringIO()
        errors = io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            exit_code = main(list(args))
        return exit_code, output.getvalue() + errors.getvalue()

    def write_draft(self, filename: str, *, claim: dict | None = None, prohibited: bool = False) -> Path:
        claim_payload = [claim] if claim is not None else []
        benefit = "Tripod ini membantu pengambilan video lebih stabil."
        if prohibited:
            benefit = "Produk ini pasti sembuh untuk semua masalah kesehatan."
        payload = {
            "angle": "Stability",
            "hook": "Video kamu masih goyang?",
            "problem_benefit": benefit,
            "cta": "Lihat detail produk sebelum membeli.",
            "caption": "Uji tripod untuk workflow konten. #ShopeeAffiliate #KontenAI",
            "hashtags": ["#ShopeeAffiliate", "#KontenAI"],
            "disclosure_text": "#ShopeeAffiliate #KontenAI",
            "claims": claim_payload,
        }
        path = self.root / filename
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def import_draft(self, draft_file: Path, draft_id: str) -> tuple[int, str]:
        return self.run_cli(
            "import-draft",
            "--file",
            str(draft_file),
            "--product-id",
            self.product_id,
            "--draft-id",
            draft_id,
            "--db",
            str(self.db_path),
        )

    def test_successful_workflow_from_intake_to_analytics(self) -> None:
        # Product intake and repeatability: the same URL remains one product.
        code, output = self.run_cli("intake", "--file", str(self.product_file), "--db", str(self.db_path))
        self.assertEqual(code, 0, output)
        code, output = self.run_cli("intake", "--file", str(self.product_file), "--db", str(self.db_path))
        self.assertEqual(code, 0, output)

        db = Database(self.db_path)
        self.assertEqual(db.get_product(self.product_id).name, "Tripod E2E Workflow")
        conn = db.get_connection()
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS count FROM products").fetchone()["count"], 1)
        finally:
            conn.close()

        # Prompt generation uses the stored product and preserves source fields.
        code, prompt_output = self.run_cli(
            "prompt",
            "--product-id",
            self.product_id,
            "--db",
            str(self.db_path),
        )
        self.assertEqual(code, 0, prompt_output)
        for expected in (self.product_id, self.product_payload["name"], self.product_payload["url"]):
            self.assertIn(expected, prompt_output)

        sourced_claim = {
            "text": "Tinggi maksimal 1.5m",
            "source_ref": self.product_payload["url"],
            "verification_status": "SOURCED",
        }
        draft_file = self.write_draft("draft.json", claim=sourced_claim)

        # Draft import is repeated before review; the composite draft identity prevents duplicates.
        code, output = self.import_draft(draft_file, self.draft_id)
        self.assertEqual(code, 0, output)
        code, output = self.import_draft(draft_file, self.draft_id)
        self.assertEqual(code, 0, output)

        db = Database(self.db_path)
        draft = db.get_draft(self.draft_id, "v1.0")
        self.assertIsNotNone(draft)
        self.assertEqual(draft.product_id, self.product_id)
        self.assertEqual(draft.status, "waiting_approval")
        self.assertTrue(db.get_compliance_report(self.draft_id, "v1.0").passed)
        claims = db.get_claims_for_draft(self.draft_id, "v1.0")
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].verification_status, "SOURCED")

        conn = db.get_connection()
        try:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) AS count FROM content_drafts WHERE id = ? AND prompt_version = ?",
                    (self.draft_id, "v1.0"),
                ).fetchone()["count"],
                1,
            )
        finally:
            conn.close()

        # Export before human approval is rejected.
        code, output = self.run_cli(
            "export",
            "--draft-id",
            self.draft_id,
            "--output-dir",
            str(self.export_dir),
            "--db",
            str(self.db_path),
        )
        self.assertEqual(code, 1, output)
        self.assertFalse((self.export_dir / self.draft_id).exists())

        # Claim review and human approval are explicit CLI actions.
        claim_id = claims[0].id
        code, output = self.run_cli(
            "review",
            "claim",
            "--claim-id",
            claim_id,
            "--status",
            "VERIFIED",
            "--version",
            "v1.0",
            "--note",
            "Checked against the curated product source.",
            "--db",
            str(self.db_path),
        )
        self.assertEqual(code, 0, output)

        code, output = self.run_cli(
            "review",
            "approve",
            "--draft-id",
            self.draft_id,
            "--db",
            str(self.db_path),
        )
        self.assertEqual(code, 0, output)
        self.assertEqual(Database(self.db_path).get_draft(self.draft_id, "v1.0").status, "approved")

        # Approved export must contain every file in the content pack and readable source data.
        code, output = self.run_cli(
            "export",
            "--draft-id",
            self.draft_id,
            "--output-dir",
            str(self.export_dir),
            "--db",
            str(self.db_path),
        )
        self.assertEqual(code, 0, output)
        pack_dir = self.export_dir / self.draft_id
        expected_files = {
            "script.md",
            "caption.txt",
            "hashtags.txt",
            "product_info.json",
            "review_checklist.md",
            "manifest.json",
        }
        self.assertEqual({path.name for path in pack_dir.iterdir()}, expected_files)
        self.assertIn(self.product_id, (pack_dir / "product_info.json").read_text(encoding="utf-8"))
        manifest = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "APPROVED_AND_EXPORTED")
        self.assertEqual(manifest["draft_id"], self.draft_id)

        # Performance recording uses the approved draft, then analytics uses latest snapshots per platform.
        performance_args = (
            "performance",
            "record",
            "--content-id",
            self.draft_id,
            "--platform",
            "Shopee Video",
            "--source",
            "manual",
            "--db",
            str(self.db_path),
        )
        code, output = self.run_cli(
            *performance_args,
            "--views",
            "100",
            "--clicks",
            "10",
            "--orders",
            "2",
            "--commission",
            "2000",
            "--observed-at",
            "2026-11-03T10:00:00+00:00",
            "--record-id",
            "e2e_perf_1",
        )
        self.assertEqual(code, 0, output)
        code, output = self.run_cli(
            *performance_args,
            "--views",
            "250",
            "--clicks",
            "25",
            "--orders",
            "5",
            "--commission",
            "5000",
            "--observed-at",
            "2026-11-03T11:00:00+00:00",
            "--record-id",
            "e2e_perf_2",
        )
        self.assertEqual(code, 0, output)

        code, output = self.run_cli(
            "performance",
            "record",
            "--content-id",
            self.draft_id,
            "--platform",
            "TikTok",
            "--views",
            "90",
            "--clicks",
            "9",
            "--orders",
            "1",
            "--commission",
            "900",
            "--observed-at",
            "2026-11-03T11:00:00+00:00",
            "--record-id",
            "e2e_perf_tiktok",
            "--source",
            "manual",
            "--db",
            str(self.db_path),
        )
        self.assertEqual(code, 0, output)

        code, output = self.run_cli(
            "performance",
            "correct",
            "--record-id",
            "e2e_perf_2",
            "--views",
            "300",
            "--clicks",
            "30",
            "--orders",
            "6",
            "--commission",
            "6000",
            "--note",
            "Corrected from the latest manually reconciled snapshot.",
            "--db",
            str(self.db_path),
        )
        self.assertEqual(code, 0, output)

        db = Database(self.db_path)
        shopee_summary = calculate_performance_summary(db.list_performance_records(platform="Shopee Video"))
        self.assertEqual(shopee_summary.total_content_items, 1)
        self.assertEqual(shopee_summary.total_snapshots, 2)
        self.assertEqual(shopee_summary.total_views, 300)
        self.assertEqual(shopee_summary.total_clicks, 30)
        self.assertEqual(shopee_summary.total_orders, 6)
        self.assertAlmostEqual(shopee_summary.aggregate_rates.ctr, 10.0)
        self.assertAlmostEqual(shopee_summary.aggregate_rates.click_to_order, 20.0)
        self.assertEqual(shopee_summary.items[0].views_delta, 200)

        tiktok_summary = calculate_performance_summary(db.list_performance_records(platform="TikTok"))
        self.assertEqual(tiktok_summary.total_views, 90)
        self.assertAlmostEqual(tiktok_summary.aggregate_rates.ctr, 10.0)
        self.assertEqual(tiktok_summary.items[0].platform, "TikTok")

        rank_report = AngleRanker(db).rank_angles(
            platform="Shopee Video",
            min_samples=1,
            sort_by="click_to_order",
        )
        self.assertEqual(len(rank_report.ranked_angles), 1)
        self.assertEqual(rank_report.ranked_angles[0].metrics.angle, "Stability")
        self.assertAlmostEqual(rank_report.ranked_angles[0].metrics.click_to_order, 20.0)

        code, output = self.run_cli(
            "performance",
            "summary",
            "--platform",
            "Shopee Video",
            "--db",
            str(self.db_path),
        )
        self.assertEqual(code, 0, output)
        self.assertIn("300", output)
        self.assertIn("10.00%", output)
        self.assertIn("20.00%", output)

    def test_compliance_failure_blocks_approval_and_export(self) -> None:
        code, output = self.run_cli("intake", "--file", str(self.product_file), "--db", str(self.db_path))
        self.assertEqual(code, 0, output)
        prohibited_file = self.write_draft("prohibited.json", prohibited=True)

        code, output = self.import_draft(prohibited_file, "e2e_rejected_draft")
        self.assertEqual(code, 1, output)

        db = Database(self.db_path)
        rejected = db.get_draft("e2e_rejected_draft", "v1.0")
        self.assertIsNotNone(rejected)
        self.assertEqual(rejected.status, "rejected")
        report = db.get_compliance_report("e2e_rejected_draft", "v1.0")
        self.assertIsNotNone(report)
        self.assertFalse(report.passed)
        self.assertTrue(any(f.severity == "ERROR" for f in report.findings))

        code, output = self.run_cli(
            "review",
            "approve",
            "--draft-id",
            "e2e_rejected_draft",
            "--db",
            str(self.db_path),
        )
        self.assertEqual(code, 1, output)
        code, output = self.run_cli(
            "export",
            "--draft-id",
            "e2e_rejected_draft",
            "--output-dir",
            str(self.export_dir),
            "--db",
            str(self.db_path),
        )
        self.assertEqual(code, 1, output)
        self.assertFalse((self.export_dir / "e2e_rejected_draft").exists())

    def test_unsupported_claims_and_invalid_inputs_are_rejected_without_partial_records(self) -> None:
        code, output = self.run_cli("intake", "--file", str(self.product_file), "--db", str(self.db_path))
        self.assertEqual(code, 0, output)

        unsupported_file = self.write_draft(
            "unsupported.json",
            claim={
                "text": "Fitur yang belum memiliki bukti",
                "source_ref": None,
                "verification_status": "UNVERIFIED",
            },
        )
        code, output = self.import_draft(unsupported_file, "e2e_unsupported_draft")
        self.assertEqual(code, 0, output)

        db = Database(self.db_path)
        claims = db.get_claims_for_draft("e2e_unsupported_draft", "v1.0")
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].verification_status, "UNVERIFIED")

        code, output = self.run_cli(
            "review",
            "approve",
            "--draft-id",
            "e2e_unsupported_draft",
            "--db",
            str(self.db_path),
        )
        self.assertEqual(code, 1, output)
        self.assertEqual(db.get_draft("e2e_unsupported_draft", "v1.0").status, "waiting_approval")

        invalid_product_file = self.root / "invalid-product.json"
        invalid_product_file.write_text(
            json.dumps({"id": "invalid-product", "name": "Invalid", "url": "https://"}),
            encoding="utf-8",
        )
        code, output = self.run_cli(
            "intake",
            "--file",
            str(invalid_product_file),
            "--db",
            str(self.db_path),
        )
        self.assertEqual(code, 1, output)
        self.assertIsNone(db.get_product("invalid-product"))

        invalid_draft_file = self.root / "invalid-draft.json"
        invalid_draft_file.write_text("not-json", encoding="utf-8")
        code, output = self.import_draft(invalid_draft_file, "e2e_invalid_draft")
        self.assertEqual(code, 1, output)
        self.assertIsNone(db.get_draft("e2e_invalid_draft", "v1.0"))

        with self.assertRaises(ValidationError):
            Product(id="invalid-local", name="Invalid", url="ftp://example.com")


if __name__ == "__main__":
    unittest.main()
