"""Regression tests for Phase 2.2.2 security and data-integrity hardening."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from affiliate_factory.compliance import check_compliance
from affiliate_factory.db import Database
from affiliate_factory.models import ContentDraft, Product
from affiliate_factory.orchestrator import run_pipeline
from affiliate_factory.review import ReviewError, approve_draft


class TestPhase222Security(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.product = Product(
            id="prod_security_01",
            name="Produk Uji Keamanan",
            url="https://example.com/product-security-01",
            price=100000.0,
            price_observed_at=datetime.now(timezone.utc),
            source="manual",
        )
        self.draft = ContentDraft(
            id="draft_security_01",
            product_id=self.product.id,
            angle="Problem-Benefit",
            hook="Hook uji keamanan",
            script="Naskah uji keamanan",
            caption="#ShopeeAffiliate #KontenAI",
            cta="Lihat detail produk",
            disclosure_text="#ShopeeAffiliate #KontenAI",
            prompt_version="v1.0",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _assert_config_failure(self, config_path: Path) -> None:
        db = Database(":memory:")
        report = check_compliance(
            db=db,
            draft=self.draft,
            product=self.product,
            config_path=config_path,
        )

        self.assertFalse(report.passed)
        self.assertEqual(report.findings[0].rule_id, "RULE-COMPLIANCE-CONFIG-01")
        persisted = db.get_compliance_report(self.draft.id, self.draft.prompt_version)
        self.assertIsNotNone(persisted)
        self.assertFalse(persisted.passed)
        self.assertEqual(persisted.findings[0].severity, "ERROR")

    def test_missing_compliance_config_fails_closed(self) -> None:
        missing_path = Path(self.temp_dir.name) / "missing-compliance-rules.json"
        self._assert_config_failure(missing_path)

    def test_malformed_compliance_config_fails_closed(self) -> None:
        malformed_path = Path(self.temp_dir.name) / "malformed-compliance-rules.json"
        malformed_path.write_text('{"rules": [', encoding="utf-8")
        self._assert_config_failure(malformed_path)

    def test_unreadable_compliance_config_fails_closed(self) -> None:
        config_path = Path(self.temp_dir.name) / "unreadable-compliance-rules.json"
        config_path.write_text('{"rules": []}', encoding="utf-8")
        with patch("builtins.open", side_effect=OSError("permission denied")):
            self._assert_config_failure(config_path)

    def test_failed_compliance_config_rejects_pipeline_and_blocks_approval(self) -> None:
        db = Database(":memory:")
        missing_path = Path(self.temp_dir.name) / "missing-pipeline-rules.json"

        result = run_pipeline(
            db=db,
            product=self.product,
            draft=self.draft,
            config_path=missing_path,
        )

        self.assertFalse(result.compliance_report.passed)
        self.assertEqual(result.draft.status, "rejected")
        with self.assertRaises(ReviewError):
            approve_draft(db, self.draft.id, self.draft.prompt_version)

    def test_product_url_accepts_http_https_with_valid_host(self) -> None:
        for index, url in enumerate((
            "http://example.com/path?affiliate=1",
            "HTTPS://Example.com:8443/path",
            "https://127.0.0.1:8080/local",
            "https://[::1]/local",
        )):
            product = Product(id=f"valid_{index}", name="Valid URL", url=url)
            self.assertEqual(product.url, url)

    def test_product_url_rejects_malformed_hosts_ports_credentials_and_whitespace(self) -> None:
        invalid_urls = (
            "https://",
            "http://",
            "https:///path",
            "https://?query=value",
            "https://example.com:invalid/path",
            "https://example.com:70000/path",
            "https://user:password@example.com/path",
            "https://exa mple.com/path",
            "https://example.com/path with space",
            "https://exa_mple.com/path",
            "https://[invalid",
        )
        for index, url in enumerate(invalid_urls):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    Product(id=f"invalid_{index}", name="Invalid URL", url=url)

    def test_foreign_keys_enabled_for_memory_and_file_connections(self) -> None:
        memory_db = Database(":memory:")
        memory_conn = memory_db.get_connection()
        self.assertEqual(memory_conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)

        file_db = Database(Path(self.temp_dir.name) / "foreign_keys.db")
        file_conn = file_db.get_connection()
        try:
            self.assertEqual(file_conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        finally:
            file_conn.close()

    def test_orphan_content_draft_product_is_rejected(self) -> None:
        db = Database(":memory:")
        orphan_draft = self.draft.model_copy(update={"product_id": "missing-product"})

        with self.assertRaises(sqlite3.IntegrityError):
            db.upsert_draft(orphan_draft)


if __name__ == "__main__":
    unittest.main()
