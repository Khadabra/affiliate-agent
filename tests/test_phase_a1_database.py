"""Phase A1 Core Reliability — Database Integrity & Reliability Test Suite.

Verifies:
1. Domain-correct Foreign Key constraints on claims and compliance_reports referencing
   content_drafts(id, prompt_version) ON DELETE CASCADE.
2. Rejection of invalid draft references (FK violation IntegrityError).
3. Cascade deletion of child records upon draft deletion.
4. Transparent legacy schema migration with orphan detection and preservation (zero data loss).
5. Idempotent init_schema execution.
6. Helper inspection methods: find_orphaned_compliance_reports and find_orphaned_claims.
7. Query plan acceleration via EXPLAIN QUERY PLAN for events(run_id), events(ref_id, module, action),
   and content_drafts(product_id).
8. SQLite WAL journal mode, busy_timeout=5000, and concurrency verification.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path

from affiliate_factory.db import Database
from affiliate_factory.models import (
    Claim,
    ComplianceFinding,
    ComplianceReport,
    ContentDraft,
    Event,
    Product,
)


class TestPhaseA1DatabaseIntegrity(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_a1.db"
        self.db = Database(self.db_path)

        self.sample_product = Product(
            id="prod_a1_01",
            name="Ring Light LED Studio",
            url="https://shopee.co.id/ring-light-led-studio",
            price=99000.0,
            price_observed_at=datetime.now(timezone.utc),
            source="manual",
            notes="Testing Phase A1 Database",
        )
        self.db.insert_product(self.sample_product)

        self.sample_draft = ContentDraft(
            id="draft_a1_01",
            product_id=self.sample_product.id,
            angle="Problem-Benefit",
            hook="Pencahayaan video kamu masih gelap?",
            script="Gunakan Ring Light LED Studio 26cm.",
            caption="Ring light murah terbaik! #ShopeeAffiliate #KontenAI",
            cta="Cek keranjang sekarang!",
            disclosure_text="#ShopeeAffiliate #KontenAI",
            status="waiting_approval",
            prompt_version="v1.0",
        )
        self.db.upsert_draft(self.sample_draft)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # --- 1. Foreign Key Enforcement & Rejection ---
    def test_fk_valid_draft_reference_succeeds(self) -> None:
        """Saving compliance report and claims referencing valid draft succeeds."""
        report = ComplianceReport(
            draft_id=self.sample_draft.id,
            prompt_version=self.sample_draft.prompt_version,
            passed=True,
            findings=[],
        )
        self.db.save_compliance_report(report)

        claim = Claim(
            id="claim_a1_valid",
            draft_id=self.sample_draft.id,
            prompt_version=self.sample_draft.prompt_version,
            text="Diameter 26cm",
            source_ref=self.sample_product.url,
            verification_status="SOURCED",
        )
        self.db.save_claims([claim])

        persisted_report = self.db.get_compliance_report(self.sample_draft.id, "v1.0")
        self.assertIsNotNone(persisted_report)
        self.assertTrue(persisted_report.passed)

        persisted_claim = self.db.get_claim("claim_a1_valid")
        self.assertIsNotNone(persisted_claim)
        self.assertEqual(persisted_claim.text, "Diameter 26cm")

    def test_fk_invalid_compliance_report_reference_rejected(self) -> None:
        """Saving compliance report referencing non-existent draft raises IntegrityError."""
        report = ComplianceReport(
            draft_id="non_existent_draft_999",
            prompt_version="v1.0",
            passed=True,
            findings=[],
        )
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.db.save_compliance_report(report)
        self.assertIn("FOREIGN KEY", str(ctx.exception))

    def test_fk_invalid_claim_reference_rejected(self) -> None:
        """Saving claim with explicit prompt_version referencing non-existent draft raises IntegrityError."""
        claim = Claim(
            id="claim_a1_invalid",
            draft_id="non_existent_draft_999",
            prompt_version="v1.0",
            text="Klaim tanpa draf induk",
            source_ref=None,
            verification_status="UNVERIFIED",
        )
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.db.save_claims([claim])
        self.assertIn("FOREIGN KEY", str(ctx.exception))

    # --- 2. Cascade Deletion ---
    def test_fk_cascade_deletion_on_draft_delete(self) -> None:
        """Deleting a parent draft cascades and deletes associated compliance reports and claims."""
        report = ComplianceReport(
            draft_id=self.sample_draft.id,
            prompt_version="v1.0",
            passed=True,
            findings=[],
        )
        self.db.save_compliance_report(report)

        claim = Claim(
            id="claim_a1_cascade",
            draft_id=self.sample_draft.id,
            prompt_version="v1.0",
            text="Klaim cascade test",
            source_ref=None,
            verification_status="SOURCED",
        )
        self.db.save_claims([claim])

        # Verify records exist before cascade
        self.assertIsNotNone(self.db.get_compliance_report(self.sample_draft.id, "v1.0"))
        self.assertIsNotNone(self.db.get_claim("claim_a1_cascade"))

        # Delete parent draft directly from SQLite
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute(
                    "DELETE FROM content_drafts WHERE id = ? AND prompt_version = ?",
                    (self.sample_draft.id, self.sample_draft.prompt_version),
                )
        finally:
            conn.close()

        # Child records must be deleted automatically via ON DELETE CASCADE
        self.assertIsNone(self.db.get_compliance_report(self.sample_draft.id, "v1.0"))
        self.assertIsNone(self.db.get_claim("claim_a1_cascade"))

    # --- 3. Migration Idempotency ---
    def test_migration_idempotency(self) -> None:
        """Calling init_schema repeatedly causes no data loss or schema errors."""
        report = ComplianceReport(
            draft_id=self.sample_draft.id,
            prompt_version="v1.0",
            passed=True,
            findings=[],
        )
        self.db.save_compliance_report(report)

        # Run init_schema 3 additional times
        for _ in range(3):
            self.db.init_schema()

        # Check that existing data is fully intact
        persisted = self.db.get_compliance_report(self.sample_draft.id, "v1.0")
        self.assertIsNotNone(persisted)
        self.assertTrue(persisted.passed)
        self.assertIsNotNone(self.db.get_draft(self.sample_draft.id, "v1.0"))

    # --- 4. Orphan Detection and Preservation ---
    def test_orphan_compliance_report_preservation_during_migration(self) -> None:
        """Legacy compliance report without parent draft is detected and preserved with fallback stub."""
        legacy_db_file = Path(self.temp_dir.name) / "legacy_orphan_report.db"
        conn = sqlite3.connect(legacy_db_file)
        conn.executescript(
            """
            CREATE TABLE compliance_reports (
                draft_id TEXT PRIMARY KEY,
                passed INTEGER NOT NULL,
                findings_json TEXT NOT NULL
            );
            INSERT INTO compliance_reports (draft_id, passed, findings_json)
            VALUES ('orphan_legacy_rep_01', 1, '[]');
            """
        )
        conn.close()

        # Initialize Database to trigger migration and orphan recovery
        migrated_db = Database(legacy_db_file)

        # 1. Report is preserved with v1.0
        rep = migrated_db.get_compliance_report("orphan_legacy_rep_01", "v1.0")
        self.assertIsNotNone(rep)
        self.assertTrue(rep.passed)

        # 2. Stub draft was created in content_drafts to satisfy FK
        stub_draft = migrated_db.get_draft("orphan_legacy_rep_01", "v1.0")
        self.assertIsNotNone(stub_draft)
        self.assertEqual(stub_draft.status, "waiting_approval")

        # 3. PRAGMA foreign_key_check reports 0 violations
        m_conn = migrated_db.get_connection()
        try:
            fk_violations = m_conn.execute("PRAGMA foreign_key_check").fetchall()
            self.assertEqual(len(fk_violations), 0)
        finally:
            m_conn.close()

    def test_orphan_inspection_helper_methods(self) -> None:
        """Helper methods find_orphaned_claims and find_orphaned_compliance_reports work correctly."""
        # Clean state has 0 orphans
        self.assertEqual(len(self.db.find_orphaned_compliance_reports()), 0)
        self.assertEqual(len(self.db.find_orphaned_claims()), 0)

        # Temporarily insert an orphan claim directly by bypassing FK enforcement
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            """
            INSERT INTO claims (id, draft_id, prompt_version, text, verification_status)
            VALUES ('claim_raw_orphan', 'non_existent_draft_raw', 'v1.0', 'Raw Orphan', 'UNVERIFIED')
            """
        )
        conn.commit()
        conn.close()

        # Inspector detects the orphan claim
        orphans = self.db.find_orphaned_claims()
        self.assertEqual(len(orphans), 1)
        self.assertEqual(orphans[0]["id"], "claim_raw_orphan")

    # --- 5. Query Plan Acceleration (EXPLAIN QUERY PLAN) ---
    def test_query_plan_indexes_verified(self) -> None:
        """Verify that events(run_id), events(ref_id, module, action), and content_drafts(product_id) use indexes."""
        conn = self.db.get_connection()
        try:
            # 1. events(run_id)
            plan_run_id = conn.execute(
                "EXPLAIN QUERY PLAN SELECT * FROM events WHERE run_id = ? ORDER BY ts ASC",
                ("some_run_id",),
            ).fetchall()
            plan_str_1 = " ".join(str(row[3]) for row in plan_run_id)
            self.assertIn("idx_events_run_id", plan_str_1)

            # 2. events(ref_id, module, action)
            plan_ref = conn.execute(
                "EXPLAIN QUERY PLAN SELECT * FROM events WHERE ref_id = ? AND module = ? AND action = ?",
                ("ref1", "mod1", "act1"),
            ).fetchall()
            plan_str_2 = " ".join(str(row[3]) for row in plan_ref)
            self.assertIn("idx_events_ref", plan_str_2)

            # 3. content_drafts(product_id)
            plan_draft_prod = conn.execute(
                "EXPLAIN QUERY PLAN SELECT * FROM content_drafts WHERE product_id = ?",
                ("prod1",),
            ).fetchall()
            plan_str_3 = " ".join(str(row[3]) for row in plan_draft_prod)
            self.assertIn("idx_content_drafts_product", plan_str_3)
        finally:
            conn.close()

    # --- 6. WAL Mode & Concurrency Hardening ---
    def test_wal_mode_and_pragmas(self) -> None:
        """On-disk database enforces WAL mode, foreign keys, and busy timeout."""
        self.assertEqual(self.db.get_journal_mode(), "wal")
        self.assertTrue(self.db.get_foreign_keys_status())
        self.assertEqual(self.db.get_busy_timeout(), 5000)

    def test_concurrent_read_write_under_wal(self) -> None:
        """Multiple concurrent threads reading and writing under WAL without locking errors."""
        errors: list[Exception] = []

        def writer_thread(worker_id: int) -> None:
            try:
                for i in range(15):
                    self.db.append_event(
                        Event(
                            id=f"evt_worker_{worker_id}_{i}",
                            ts=datetime.now(timezone.utc),
                            run_id=f"run_worker_{worker_id}",
                            module="concurrency_test",
                            action="write_event",
                            status="succeeded",
                            ref_type="worker_id",
                            ref_id=str(worker_id),
                            note=f"Concurrent write iteration {i}",
                        )
                    )
            except Exception as e:
                errors.append(e)

        def reader_thread(worker_id: int) -> None:
            try:
                for _ in range(15):
                    events = self.db.list_events(f"run_worker_{worker_id}")
                    _ = len(events)
            except Exception as e:
                errors.append(e)

        threads: list[threading.Thread] = []
        for w in range(4):
            threads.append(threading.Thread(target=writer_thread, args=(w,)))
            threads.append(threading.Thread(target=reader_thread, args=(w,)))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Concurrent workers encountered errors: {errors}")


if __name__ == "__main__":
    unittest.main()
