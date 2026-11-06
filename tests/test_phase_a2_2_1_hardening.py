"""Phase A2.2.1 Database & Approval Hardening Test Suite.

Verifies:
1. Rejection of illegal approval decisions (must be 'APPROVE' or 'REJECT').
2. Rejection of duplicate authoritative approvals ('APPROVE') per job.
3. Enforcement of complete binding data (draft_id, prompt_version, claims_fingerprint,
   content_sha256, job_attempt) on new approvals.
4. Legacy unbound approvals remain readable but cannot authorize new exports.
5. Failed migration atomicity: leaves sqlite_master 100% identical to pre-migration state.
6. Preservation of existing rows, foreign keys, and relationships during migration.
7. Post-migration foreign key integrity verification (PRAGMA foreign_key_check).
8. Rejection of databases with newer unsupported schema versions.
9. Reopening an already migrated database is idempotent and does not repeat migrations.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from affiliate_factory.db import (
    CURRENT_SCHEMA_VERSION,
    ApprovalDecision,
    ApprovalRecord,
    Database,
    Product,
    ContentDraft,
    compute_claims_fingerprint,
    compute_content_sha256,
)


class TestApprovalBindingHardening(unittest.TestCase):
    """Test strict binding, decision validation, and authoritative approval rules."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_approvals.db"
        self.db = Database(self.db_path)

        # Seed product and draft
        self.product = Product(
            id="prod_appr_01",
            name="Wireless Microphone Pro",
            url="https://shopee.co.id/mic-pro",
            price=150000.0,
            source="manual",
        )
        self.db.insert_product(self.product)

        self.draft = ContentDraft(
            id="draft_appr_01",
            product_id=self.product.id,
            angle="Problem-Solution",
            hook="Audio video kamu kresek-kresek?",
            script="Gunakan Wireless Microphone Pro.",
            caption="Audio jernih seketika! #ShopeeAffiliate",
            cta="Beli di bio sekarang!",
            disclosure_text="#ShopeeAffiliate #KontenAI",
            status="waiting_approval",
            prompt_version="v1.0",
        )
        self.db.upsert_draft(self.draft)

        self.job = self.db.submit_job("content_pipeline", {"draft_id": self.draft.id})
        self.content_sha = compute_content_sha256(self.draft)
        self.claims_fp = compute_claims_fingerprint(["Garansi 1 tahun resmi"])

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_illegal_approval_decision_rejected(self) -> None:
        """An approval with decision other than APPROVE or REJECT is strictly rejected."""
        # 1. Pydantic validation rejects illegal decision on model instantiation
        with self.assertRaises(ValueError):
            ApprovalRecord(
                approval_id="appr_bad_1",
                job_id=self.job.job_id,
                decision="PENDING",
                reviewer="editor_1",
                reviewed_at=datetime.now(timezone.utc).isoformat(),
                draft_id=self.draft.id,
                prompt_version=self.draft.prompt_version,
                claims_fingerprint=self.claims_fp,
                content_sha256=self.content_sha,
                job_attempt=1,
            )

        with self.assertRaises(ValueError):
            ApprovalRecord(
                approval_id="appr_bad_2",
                job_id=self.job.job_id,
                decision="maybe",
                reviewer="editor_1",
                reviewed_at=datetime.now(timezone.utc).isoformat(),
            )

    def test_new_approval_cannot_be_accepted_without_complete_binding_data(self) -> None:
        """New approval records missing any binding fields must be rejected."""
        valid_args = {
            "approval_id": "appr_val_1",
            "job_id": self.job.job_id,
            "decision": ApprovalDecision.APPROVE,
            "reviewer": "human_editor_1",
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "draft_id": self.draft.id,
            "prompt_version": self.draft.prompt_version,
            "claims_fingerprint": self.claims_fp,
            "content_sha256": self.content_sha,
            "job_attempt": 1,
        }

        # Missing draft_id
        args_missing_draft = dict(valid_args, draft_id=None)
        appr = ApprovalRecord(**args_missing_draft)
        with self.assertRaises(ValueError) as ctx:
            self.db.save_approval_record(appr)
        self.assertIn("missing or incomplete binding data", str(ctx.exception).lower())

        # Missing prompt_version
        args_missing_pv = dict(valid_args, prompt_version="")
        appr = ApprovalRecord(**args_missing_pv)
        with self.assertRaises(ValueError) as ctx:
            self.db.save_approval_record(appr)
        self.assertIn("prompt_version", str(ctx.exception).lower())

        # Missing content_sha256
        args_missing_sha = dict(valid_args, content_sha256=None)
        appr = ApprovalRecord(**args_missing_sha)
        with self.assertRaises(ValueError) as ctx:
            self.db.save_approval_record(appr)
        self.assertIn("content_sha256", str(ctx.exception).lower())

        # Missing claims_fingerprint
        args_missing_fp = dict(valid_args, claims_fingerprint=None)
        appr = ApprovalRecord(**args_missing_fp)
        with self.assertRaises(ValueError) as ctx:
            self.db.save_approval_record(appr)
        self.assertIn("claims_fingerprint", str(ctx.exception).lower())

        # Missing or invalid job_attempt (< 1)
        args_bad_attempt = dict(valid_args, job_attempt=0)
        appr = ApprovalRecord(**args_bad_attempt)
        with self.assertRaises(ValueError) as ctx:
            self.db.save_approval_record(appr)
        self.assertIn("job_attempt", str(ctx.exception).lower())

    def test_duplicate_authoritative_approval_for_one_job_is_rejected(self) -> None:
        """At most one authoritative approval ('APPROVE') is permitted per job."""
        now_iso = datetime.now(timezone.utc).isoformat()
        appr1 = ApprovalRecord(
            approval_id="appr_auth_1",
            job_id=self.job.job_id,
            decision=ApprovalDecision.APPROVE,
            reviewer="human_reviewer_1",
            reviewed_at=now_iso,
            draft_id=self.draft.id,
            prompt_version=self.draft.prompt_version,
            claims_fingerprint=self.claims_fp,
            content_sha256=self.content_sha,
            job_attempt=1,
        )
        self.db.save_approval_record(appr1)

        # Attempt to insert a second APPROVE for the same job
        appr2 = ApprovalRecord(
            approval_id="appr_auth_2",
            job_id=self.job.job_id,
            decision=ApprovalDecision.APPROVE,
            reviewer="human_reviewer_2",
            reviewed_at=now_iso,
            draft_id=self.draft.id,
            prompt_version=self.draft.prompt_version,
            claims_fingerprint=self.claims_fp,
            content_sha256=self.content_sha,
            job_attempt=2,
        )
        with self.assertRaises(ValueError) as ctx:
            self.db.save_approval_record(appr2)
        self.assertIn("duplicate authoritative approval", str(ctx.exception).lower())

        # However, multiple REJECT records for the same job ARE permitted
        job_reject = self.db.submit_job("content_pipeline_reject", {})
        rej1 = ApprovalRecord(
            approval_id="appr_rej_1",
            job_id=job_reject.job_id,
            decision=ApprovalDecision.REJECT,
            reviewer="human_reviewer_1",
            notes="Audio issue",
            reviewed_at=now_iso,
            draft_id=self.draft.id,
            prompt_version=self.draft.prompt_version,
            claims_fingerprint=self.claims_fp,
            content_sha256=self.content_sha,
            job_attempt=1,
        )
        rej2 = ApprovalRecord(
            approval_id="appr_rej_2",
            job_id=job_reject.job_id,
            decision=ApprovalDecision.REJECT,
            reviewer="human_reviewer_2",
            notes="Visual issue",
            reviewed_at=now_iso,
            draft_id=self.draft.id,
            prompt_version=self.draft.prompt_version,
            claims_fingerprint=self.claims_fp,
            content_sha256=self.content_sha,
            job_attempt=2,
        )
        self.db.save_approval_record(rej1)
        self.db.save_approval_record(rej2)

        recs = self.db.get_approval_records(job_reject.job_id)
        self.assertEqual(len(recs), 2)

    def test_legacy_unbound_approvals_readable_but_cannot_authorize_export(self) -> None:
        """Legacy approval rows without binding data are readable but cannot authorize exports."""
        # Insert a raw unbound legacy row (simulating pre-A2.2.1 row)
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO approval_records (
                        approval_id, job_id, decision, reviewer, notes, reviewed_at
                    ) VALUES ('appr_legacy_01', ?, 'APPROVE', 'legacy_admin', 'Old approval', '2026-11-01T00:00:00Z')
                    """,
                    (self.job.job_id,),
                )
        finally:
            conn.close()

        records = self.db.get_approval_records(self.job.job_id)
        self.assertEqual(len(records), 1)
        legacy_rec = records[0]

        # Readable with None for binding attributes
        self.assertEqual(legacy_rec.approval_id, "appr_legacy_01")
        self.assertEqual(legacy_rec.decision, "APPROVE")
        self.assertIsNone(legacy_rec.draft_id)
        self.assertIsNone(legacy_rec.content_sha256)
        self.assertFalse(legacy_rec.has_complete_binding)

        # Must NOT authorize exports
        self.assertFalse(legacy_rec.is_valid_for_export(self.draft.id, self.draft.prompt_version))
        self.assertFalse(
            self.db.can_authorize_export(
                self.job.job_id,
                expected_draft_id=self.draft.id,
                expected_prompt_version=self.draft.prompt_version,
                expected_content_sha256=self.content_sha,
                expected_claims_fingerprint=self.claims_fp,
            )
        )


class TestDatabaseMigrationAtomicity(unittest.TestCase):
    """Test atomic schema initialization, PRAGMA user_version, and rollback on failure."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_failed_migration_leaves_sqlite_master_identical_to_pre_migration_state(self) -> None:
        """Reproduce failed-migration probe: verifying sqlite_master is completely untouched after rollback."""
        db_path = Path(self.temp_dir.name) / "probe_broken_fk.db"
        raw_conn = sqlite3.connect(str(db_path))
        raw_conn.execute("PRAGMA foreign_keys = OFF")
        raw_conn.execute("CREATE TABLE products (id TEXT PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL UNIQUE, price REAL, price_observed_at TEXT, source TEXT NOT NULL, notes TEXT)")
        raw_conn.execute(
            """
            CREATE TABLE content_drafts (
                id TEXT NOT NULL, product_id TEXT NOT NULL, angle TEXT, hook TEXT,
                script TEXT, caption TEXT, cta TEXT, disclosure_text TEXT, status TEXT,
                prompt_version TEXT, created_at TEXT,
                PRIMARY KEY (id, prompt_version),
                FOREIGN KEY (product_id) REFERENCES products (id)
            )
            """
        )
        raw_conn.execute(
            """
            INSERT INTO content_drafts VALUES (
                'orphan_draft', 'missing_prod_id', 'a', 'h', 's', 'c', 'cta', '#ai', 'draft', 'v1.0', '2026-11-05T00:00:00Z'
            )
            """
        )
        raw_conn.commit()
        raw_conn.close()

        # Capture pre-migration schema probe
        check_conn = sqlite3.connect(str(db_path))
        pre_master = sorted(check_conn.execute("SELECT type, name, sql FROM sqlite_master").fetchall())
        pre_tables = sorted([r[0] for r in check_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()])
        check_conn.close()

        # Database initialization must fail due to foreign key violation
        with self.assertRaises(RuntimeError) as ctx:
            Database(db_path)
        self.assertIn("failed foreign key validation", str(ctx.exception).lower())

        # Probe database state post-failure
        post_conn = sqlite3.connect(str(db_path))
        post_master = sorted(post_conn.execute("SELECT type, name, sql FROM sqlite_master").fetchall())
        post_tables = sorted([r[0] for r in post_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()])
        post_conn.close()

        # Assert sqlite_master is byte/schema identical
        self.assertEqual(pre_master, post_master, "sqlite_master was altered despite migration failure!")
        self.assertEqual(pre_tables, post_tables)

        # Specifically verify none of the newly introduced tables were committed
        forbidden_tables = {"jobs", "job_runs", "approval_records", "events", "performance_records", "agent_tasks"}
        self.assertTrue(forbidden_tables.isdisjoint(set(post_tables)), f"Leaked tables found in DB: {forbidden_tables & set(post_tables)}")

    def test_existing_rows_and_relationships_survive_successful_migration(self) -> None:
        """Existing legacy database with rows and relationships migrates cleanly with zero data loss."""
        db_path = Path(self.temp_dir.name) / "legacy_v1_db.db"
        raw_conn = sqlite3.connect(str(db_path))
        raw_conn.execute("CREATE TABLE products (id TEXT PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL UNIQUE, price REAL, price_observed_at TEXT, source TEXT NOT NULL, notes TEXT)")
        raw_conn.execute(
            """
            CREATE TABLE content_drafts (
                id TEXT NOT NULL, product_id TEXT NOT NULL, angle TEXT, hook TEXT,
                script TEXT, caption TEXT, cta TEXT, disclosure_text TEXT, status TEXT,
                prompt_version TEXT, created_at TEXT,
                PRIMARY KEY (id, prompt_version),
                FOREIGN KEY (product_id) REFERENCES products (id)
            )
            """
        )
        raw_conn.execute(
            """
            CREATE TABLE jobs (
                job_id TEXT PRIMARY KEY, job_type TEXT NOT NULL, payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued', priority INTEGER NOT NULL DEFAULT 100,
                attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 3,
                lease_token TEXT, lease_expires_at TEXT, worker_id TEXT, idempotency_key TEXT UNIQUE,
                cancellation_requested INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, last_heartbeat_at TEXT, completed_at TEXT,
                error_message TEXT, result_payload TEXT
            )
            """
        )
        raw_conn.execute(
            """
            CREATE TABLE approval_records (
                approval_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, decision TEXT NOT NULL,
                reviewer TEXT NOT NULL, notes TEXT, reviewed_at TEXT NOT NULL,
                FOREIGN KEY (job_id) REFERENCES jobs (job_id) ON DELETE CASCADE
            )
            """
        )
        raw_conn.execute("INSERT INTO products VALUES ('p1', 'Prod 1', 'https://shopee.co.id/p1', 50000.0, NULL, 'manual', NULL)")
        raw_conn.execute("INSERT INTO content_drafts VALUES ('d1', 'p1', 'ang', 'hk', 'sc', 'cap', 'cta', '#ai', 'draft', 'v1.0', '2026-11-06T00:00:00Z')")
        raw_conn.execute("INSERT INTO jobs (job_id, job_type, payload, created_at, updated_at) VALUES ('j1', 'task', '{}', '2026-11-06T00:00:00Z', '2026-11-06T00:00:00Z')")
        raw_conn.execute("INSERT INTO approval_records VALUES ('app_old', 'j1', 'approved', 'reviewer_old', 'Old notes', '2026-11-06T00:00:00Z')")
        raw_conn.commit()
        raw_conn.close()

        # Migrate by opening Database
        db = Database(db_path)

        # Check user_version set to CURRENT_SCHEMA_VERSION
        conn = db.get_connection()
        try:
            ver = conn.execute("PRAGMA user_version").fetchone()[0]
            self.assertEqual(ver, CURRENT_SCHEMA_VERSION)

            # Foreign key check passes
            fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            self.assertEqual(len(fk_violations), 0)
        finally:
            conn.close()

        # Check existing data preserved
        p = db.get_product("p1")
        self.assertIsNotNone(p)
        self.assertEqual(p.name, "Prod 1")

        d = db.get_draft("d1", "v1.0")
        self.assertIsNotNone(d)

        apprs = db.get_approval_records("j1")
        self.assertEqual(len(apprs), 1)
        self.assertEqual(apprs[0].approval_id, "app_old")
        self.assertEqual(apprs[0].decision, "APPROVE")  # Normalized during migration
        self.assertEqual(apprs[0].reviewer, "reviewer_old")

    def test_post_migration_foreign_key_integrity_validation(self) -> None:
        """Post-migration foreign key integrity is verified via PRAGMA foreign_key_check."""
        db_path = Path(self.temp_dir.name) / "fk_validation_db.db"
        db = Database(db_path)
        conn = db.get_connection()
        try:
            # Seed valid chain: product -> draft -> claim, compliance, job -> approval
            db.insert_product(Product(id="p_fk", name="FK Product", url="https://shopee.co.id/fk", source="manual"))
            db.upsert_draft(ContentDraft(
                id="d_fk", product_id="p_fk", angle="ang", hook="hk", script="sc",
                caption="cap", cta="cta", disclosure_text="#ai", status="draft", prompt_version="v1.0"
            ))
            job = db.submit_job("content_pipeline", {"draft_id": "d_fk"})
            approval = ApprovalRecord(
                approval_id="appr_fk",
                job_id=job.job_id,
                decision=ApprovalDecision.APPROVE,
                reviewer="reviewer_1",
                reviewed_at=datetime.now(timezone.utc).isoformat(),
                draft_id="d_fk",
                prompt_version="v1.0",
                claims_fingerprint=compute_claims_fingerprint(["claim 1"]),
                content_sha256="fake_sha",
                job_attempt=1,
            )
            db.save_approval_record(approval)

            # Assert PRAGMA foreign_key_check returns zero violations
            fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            self.assertEqual(len(fk_violations), 0)
        finally:
            conn.close()

    def test_newer_unsupported_schema_versions_rejected(self) -> None:
        """Databases with a PRAGMA user_version higher than supported must be rejected."""
        db_path = Path(self.temp_dir.name) / "future_db.db"
        raw_conn = sqlite3.connect(str(db_path))
        raw_conn.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION + 10}")
        raw_conn.commit()
        raw_conn.close()

        with self.assertRaises(RuntimeError) as ctx:
            Database(db_path)
        self.assertIn("newer than supported", str(ctx.exception).lower())

    def test_reopening_already_migrated_database_is_idempotent(self) -> None:
        """Reopening an already migrated database preserves version, data, and does not corrupt."""
        db_path = Path(self.temp_dir.name) / "idempotent_db.db"
        db1 = Database(db_path)
        prod = Product(id="prod_idem", name="Idem", url="https://shopee.co.id/idem", price=10.0, source="manual")
        db1.insert_product(prod)

        # Reopen
        db2 = Database(db_path)
        p_loaded = db2.get_product("prod_idem")
        self.assertIsNotNone(p_loaded)
        self.assertEqual(p_loaded.name, "Idem")

        conn = db2.get_connection()
        try:
            ver = conn.execute("PRAGMA user_version").fetchone()[0]
            self.assertEqual(ver, CURRENT_SCHEMA_VERSION)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
