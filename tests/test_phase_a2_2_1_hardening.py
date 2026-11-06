"""Phase A2.2.1 & A2.2.1.1 Approval Authorization Integrity & Hardening Test Suite.

Verifies:
1. Rejection of illegal approval decisions (must be 'APPROVE' or 'REJECT').
2. Strict content_sha256 & claims_fingerprint validation (64-char lowercase hex, length, non-hex rejection).
3. Complete replacement of fake_sha with authentic cryptographic digests.
4. Fail-closed authorization in can_authorize_export:
   - Draft content changed after approval -> rejects export.
   - Claims fingerprint changed after approval -> rejects export.
   - Optional security parameters set to None cannot bypass validation.
   - Authoritative path reads draft and claims from DB and recalculates canonical hashes.
   - Enforces prompt_version match against actual draft.
   - Enforces draft_id match against job.payload["draft_id"] if specified.
   - Enforces job_attempt match against job.attempts (stale attempt rejection).
5. Canonicalization collision prevention: boundary shifts that collide under naive string concatenation
   yield strictly distinct SHA-256 digests.
6. Legacy migration safety & quarantine:
   - Unknown legacy decisions (e.g. 'PENDING') quarantined into approval_records_quarantine.
   - Conflicting duplicate legacy APPROVE records quarantined.
   - Quarantined records cannot authorize exports.
   - Legacy databases open cleanly with PRAGMA integrity_check == 'ok'.
   - Aborts migration immediately if pre-migration backup fails without swallowing errors.
7. Atomic schema rollback upon migration failure.
8. Raw SQL insertion constraints: SQLite engine-level CHECK constraints block partial bindings,
   invalid SHA lengths/characters, and invalid job attempts.
9. Rejection of newer unsupported schema versions and idempotency of reopened databases.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from affiliate_factory.db import (
    CURRENT_SCHEMA_VERSION,
    ApprovalDecision,
    ApprovalRecord,
    Database,
    Product,
    ContentDraft,
    Claim,
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

    def test_content_sha256_length_and_hex_validation(self) -> None:
        """content_sha256 must be exactly 64 hexadecimal characters."""
        base_args = {
            "approval_id": "appr_sha_val",
            "job_id": self.job.job_id,
            "decision": "APPROVE",
            "reviewer": "editor_1",
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "draft_id": self.draft.id,
            "prompt_version": self.draft.prompt_version,
            "claims_fingerprint": self.claims_fp,
            "job_attempt": 1,
        }

        # Too short (63 chars)
        with self.assertRaises(ValueError) as ctx:
            ApprovalRecord(**base_args, content_sha256="a" * 63)
        self.assertIn("64", str(ctx.exception))

        # Too long (65 chars)
        with self.assertRaises(ValueError) as ctx:
            ApprovalRecord(**base_args, content_sha256="a" * 65)
        self.assertIn("64", str(ctx.exception))

        # Non-hex characters ('fake_sha' or containing 'z')
        with self.assertRaises(ValueError) as ctx:
            ApprovalRecord(**base_args, content_sha256="fake_sha")
        self.assertIn("hexadecimal", str(ctx.exception).lower())

        with self.assertRaises(ValueError) as ctx:
            ApprovalRecord(**base_args, content_sha256="z" + "a" * 63)
        self.assertIn("hexadecimal", str(ctx.exception).lower())

        # Uppercase hex is cleanly normalized to lowercase
        valid_upper = ("A" * 64)
        rec = ApprovalRecord(**base_args, content_sha256=valid_upper)
        self.assertEqual(rec.content_sha256, "a" * 64)

    def test_claims_fingerprint_length_and_hex_validation(self) -> None:
        """claims_fingerprint must be exactly 64 hexadecimal characters."""
        base_args = {
            "approval_id": "appr_fp_val",
            "job_id": self.job.job_id,
            "decision": "APPROVE",
            "reviewer": "editor_1",
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "draft_id": self.draft.id,
            "prompt_version": self.draft.prompt_version,
            "content_sha256": self.content_sha,
            "job_attempt": 1,
        }

        # Non-hex fingerprint
        with self.assertRaises(ValueError) as ctx:
            ApprovalRecord(**base_args, claims_fingerprint="not_a_valid_hex_fingerprint")
        self.assertIn("hexadecimal", str(ctx.exception).lower())

        # 63 characters
        with self.assertRaises(ValueError) as ctx:
            ApprovalRecord(**base_args, claims_fingerprint="b" * 63)
        self.assertIn("64", str(ctx.exception))

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

        # Invalid job_attempt (< 1) rejected directly on model instantiation
        with self.assertRaises(ValueError) as ctx:
            ApprovalRecord(**dict(valid_args, job_attempt=0))
        self.assertIn("job_attempt", str(ctx.exception).lower())

        # Missing job_attempt (None) rejected on save
        appr_none_attempt = ApprovalRecord(**dict(valid_args, job_attempt=None))
        with self.assertRaises(ValueError) as ctx:
            self.db.save_approval_record(appr_none_attempt)
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
        job_reject = self.db.submit_job("content_pipeline_reject", {"draft_id": self.draft.id})
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
            )
        )


class TestAuthorizationIntegrityFailClosed(unittest.TestCase):
    """Test fail-closed behavior of can_authorize_export under various mismatch and tampering conditions."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_auth_integrity.db"
        self.db = Database(self.db_path)

        # Seed product, draft, and claims
        self.product = Product(
            id="p_auth_01",
            name="Smart LED Desk Lamp",
            url="https://shopee.co.id/lamp-01",
            price=120000.0,
            source="manual",
        )
        self.db.insert_product(self.product)

        self.draft = ContentDraft(
            id="draft_auth_01",
            product_id=self.product.id,
            angle="Problem-Solution",
            hook="Mata cepat lelah saat kerja malam?",
            script="Lampu meja LED ini punya perlindungan mata.",
            caption="Cahaya lembut bebas radiasi. #ShopeeAffiliate",
            cta="Beli di bio sekarang!",
            disclosure_text="#ShopeeAffiliate #KontenAI",
            status="waiting_approval",
            prompt_version="v1.0",
        )
        self.db.upsert_draft(self.draft)

        self.claim = Claim(
            id="claim_auth_01",
            draft_id=self.draft.id,
            prompt_version=self.draft.prompt_version,
            text="Perlindungan mata tersertifikasi",
            source_ref="https://shopee.co.id/lamp-01",
            verification_status="VERIFIED",
        )
        self.db.save_claims([self.claim])

        # Claim job to simulate active execution attempt 1
        self.raw_job = self.db.submit_job("content_pipeline", {"draft_id": self.draft.id})
        self.claimed_job = self.db.claim_next_job("worker_1")
        self.assertEqual(self.claimed_job.job_id, self.raw_job.job_id)
        self.assertEqual(self.claimed_job.attempts, 1)

        self.content_sha = compute_content_sha256(self.draft)
        self.claims_fp = compute_claims_fingerprint([self.claim])

        self.valid_approval = ApprovalRecord(
            approval_id="appr_auth_ok",
            job_id=self.claimed_job.job_id,
            decision=ApprovalDecision.APPROVE,
            reviewer="senior_reviewer",
            reviewed_at=datetime.now(timezone.utc).isoformat(),
            draft_id=self.draft.id,
            prompt_version=self.draft.prompt_version,
            claims_fingerprint=self.claims_fp,
            content_sha256=self.content_sha,
            job_attempt=1,
        )
        self.db.save_approval_record(self.valid_approval)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_valid_approval_and_matching_db_state_authorizes_export(self) -> None:
        """When draft, claims, attempt, and job payload all match, authorization succeeds."""
        authorized = self.db.can_authorize_export(
            job_id=self.claimed_job.job_id,
            expected_draft_id=self.draft.id,
            expected_prompt_version=self.draft.prompt_version,
            expected_attempt=1,
            expected_content_sha256=self.content_sha,
            expected_claims_fingerprint=self.claims_fp,
        )
        self.assertTrue(authorized)

    def test_content_changed_after_approval_fails_authorization(self) -> None:
        """If draft content in database is modified after approval, authorization MUST return False."""
        # Tamper with the script in database
        tampered_draft = self.draft.model_copy(update={"script": "Naskah diubah diam-diam setelah disetujui."})
        self.db.upsert_draft(tampered_draft)

        authorized = self.db.can_authorize_export(
            job_id=self.claimed_job.job_id,
            expected_draft_id=self.draft.id,
            expected_prompt_version=self.draft.prompt_version,
        )
        self.assertFalse(authorized, "Export was authorized despite draft content modification!")

    def test_claims_fingerprint_changed_after_approval_fails_authorization(self) -> None:
        """If claims are modified or added in database after approval, authorization MUST return False."""
        # Add an unauthorized claim to the draft
        new_claim = Claim(
            id="claim_sneaky_02",
            draft_id=self.draft.id,
            prompt_version=self.draft.prompt_version,
            text="Klaim tambahan yang belum disetujui",
            verification_status="UNVERIFIED",
        )
        self.db.save_claims([new_claim])

        authorized = self.db.can_authorize_export(
            job_id=self.claimed_job.job_id,
            expected_draft_id=self.draft.id,
            expected_prompt_version=self.draft.prompt_version,
        )
        self.assertFalse(authorized, "Export was authorized despite claims fingerprint modification!")

    def test_missing_security_parameters_fail_closed(self) -> None:
        """Optional security parameters passing None still compute and verify DB state, and cannot bypass checks."""
        # Omitting expected_content_sha256 and expected_claims_fingerprint still enforces DB recomputation
        authorized = self.db.can_authorize_export(
            job_id=self.claimed_job.job_id,
            expected_draft_id=self.draft.id,
            expected_prompt_version=self.draft.prompt_version,
            expected_content_sha256=None,
            expected_claims_fingerprint=None,
        )
        self.assertTrue(authorized)

        # But if caller supplies wrong explicit hashes, it fails immediately
        wrong_sha = hashlib.sha256(b"wrong").hexdigest()
        bad_auth = self.db.can_authorize_export(
            job_id=self.claimed_job.job_id,
            expected_draft_id=self.draft.id,
            expected_prompt_version=self.draft.prompt_version,
            expected_content_sha256=wrong_sha,
        )
        self.assertFalse(bad_auth)

    def test_stale_job_attempt_cannot_authorize_new_attempt(self) -> None:
        """An approval granted on attempt 1 cannot authorize an export when the job has moved to attempt 2."""
        # Simulate job failure and subsequent retry (incrementing attempt to 2)
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute("UPDATE jobs SET attempts = 2 WHERE job_id = ?", (self.claimed_job.job_id,))
        finally:
            conn.close()

        # Authorization fails because approval.job_attempt (1) != job.attempts (2)
        authorized = self.db.can_authorize_export(
            job_id=self.claimed_job.job_id,
            expected_draft_id=self.draft.id,
            expected_prompt_version=self.draft.prompt_version,
        )
        self.assertFalse(authorized, "Stale attempt 1 approval authorized attempt 2 job run!")

        # Explicit expected_attempt mismatch also fails
        authorized_explicit = self.db.can_authorize_export(
            job_id=self.claimed_job.job_id,
            expected_draft_id=self.draft.id,
            expected_prompt_version=self.draft.prompt_version,
            expected_attempt=2,
        )
        self.assertFalse(authorized_explicit)

    def test_job_payload_mismatched_draft_fails_authorization(self) -> None:
        """If the job payload specifies a different draft_id than requested, authorization fails."""
        # Submit a second job with payload pointing to another draft
        job_other = self.db.submit_job("content_pipeline", {"draft_id": "draft_other_99"})
        claimed_other = self.db.claim_next_job("worker_1")
        self.assertEqual(claimed_other.job_id, job_other.job_id)

        # Attempt to authorize for self.draft.id on this other job
        authorized = self.db.can_authorize_export(
            job_id=job_other.job_id,
            expected_draft_id=self.draft.id,
            expected_prompt_version=self.draft.prompt_version,
        )
        self.assertFalse(authorized)


class TestCanonicalization(unittest.TestCase):
    """Test deterministic canonical JSON representations and collision resistance."""

    def test_canonicalization_collision_prevention(self) -> None:
        """Drafts with field boundary shifts that collide under naive string joins have distinct SHA-256."""
        d1 = ContentDraft(
            id="d_col",
            product_id="p1",
            angle="Problem-Benefit",
            hook="Promo Heboh\nDiskon 50%",
            script="Buruan beli sekarang!",
            caption="Cap",
            cta="CTA",
            disclosure_text="#AI",
            status="draft",
            prompt_version="v1.0",
        )
        d2 = ContentDraft(
            id="d_col",
            product_id="p1",
            angle="Problem-Benefit",
            hook="Promo Heboh",
            script="Diskon 50%\nBuruan beli sekarang!",
            caption="Cap",
            cta="CTA",
            disclosure_text="#AI",
            status="draft",
            prompt_version="v1.0",
        )

        # Prove naive join collides
        naive_str_1 = f"{d1.hook}\n{d1.script}\n{d1.caption}\n{d1.cta}\n{d1.disclosure_text}".encode("utf-8")
        naive_str_2 = f"{d2.hook}\n{d2.script}\n{d2.caption}\n{d2.cta}\n{d2.disclosure_text}".encode("utf-8")
        self.assertEqual(hashlib.sha256(naive_str_1).hexdigest(), hashlib.sha256(naive_str_2).hexdigest())

        # Assert canonical JSON hashing produces strictly distinct digests
        sha1 = compute_content_sha256(d1)
        sha2 = compute_content_sha256(d2)
        self.assertNotEqual(sha1, sha2)
        self.assertEqual(len(sha1), 64)
        self.assertEqual(len(sha2), 64)


class TestLegacyMigrationAndQuarantine(unittest.TestCase):
    """Test quarantine of invalid legacy records, backup enforcement, and migration atomicity."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_legacy_pending_unknown_decision_quarantined_and_db_opens_cleanly(self) -> None:
        """Legacy databases with unknown decision strings (e.g. 'PENDING') quarantine rows and open cleanly."""
        db_path = Path(self.temp_dir.name) / "legacy_pending.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE products (id TEXT PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL UNIQUE, price REAL, price_observed_at TEXT, source TEXT NOT NULL, notes TEXT)")
        conn.execute("CREATE TABLE content_drafts (id TEXT NOT NULL, product_id TEXT NOT NULL, angle TEXT, hook TEXT, script TEXT, caption TEXT, cta TEXT, disclosure_text TEXT, status TEXT, prompt_version TEXT, created_at TEXT, PRIMARY KEY (id, prompt_version))")
        conn.execute("CREATE TABLE jobs (job_id TEXT PRIMARY KEY, job_type TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued', priority INTEGER NOT NULL DEFAULT 100, attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 3, lease_token TEXT, lease_expires_at TEXT, worker_id TEXT, idempotency_key TEXT UNIQUE, cancellation_requested INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_heartbeat_at TEXT, completed_at TEXT, error_message TEXT, result_payload TEXT)")
        conn.execute("CREATE TABLE approval_records (approval_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, decision TEXT NOT NULL, reviewer TEXT NOT NULL, notes TEXT, reviewed_at TEXT NOT NULL)")

        conn.execute("INSERT INTO products VALUES ('p1', 'Prod 1', 'https://shopee.co.id/p1', 1000.0, NULL, 'manual', NULL)")
        conn.execute("INSERT INTO content_drafts VALUES ('d1', 'p1', 'a', 'h', 's', 'c', 'cta', '#ai', 'draft', 'v1.0', '2026-11-06T00:00:00Z')")
        conn.execute("INSERT INTO jobs (job_id, job_type, payload, created_at, updated_at) VALUES ('j1', 'task', '{}', '2026-11-06T00:00:00Z', '2026-11-06T00:00:00Z')")
        conn.execute("INSERT INTO approval_records VALUES ('app_pending', 'j1', 'PENDING', 'reviewer_old', 'Under review', '2026-11-06T00:00:00Z')")
        conn.commit()
        conn.close()

        # Opening Database migrates cleanly without crash
        db = Database(db_path)
        quarantined = db.get_quarantined_approval_records("j1")
        self.assertEqual(len(quarantined), 1)
        self.assertEqual(quarantined[0]["approval_id"], "app_pending")
        self.assertEqual(quarantined[0]["decision"], "PENDING")
        self.assertIn("invalid_legacy_decision", quarantined[0]["quarantine_reason"])

        # approval_records has 0 valid rows
        self.assertEqual(len(db.get_approval_records("j1")), 0)

        # Integrity check passes
        raw = db.get_connection()
        try:
            self.assertEqual(raw.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        finally:
            raw.close()

    def test_legacy_duplicate_approve_quarantined_and_db_opens_cleanly(self) -> None:
        """Legacy databases with duplicate APPROVE records for the same job quarantine duplicates and open cleanly."""
        db_path = Path(self.temp_dir.name) / "legacy_duplicates.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE products (id TEXT PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL UNIQUE, price REAL, price_observed_at TEXT, source TEXT NOT NULL, notes TEXT)")
        conn.execute("CREATE TABLE content_drafts (id TEXT NOT NULL, product_id TEXT NOT NULL, angle TEXT, hook TEXT, script TEXT, caption TEXT, cta TEXT, disclosure_text TEXT, status TEXT, prompt_version TEXT, created_at TEXT, PRIMARY KEY (id, prompt_version))")
        conn.execute("CREATE TABLE jobs (job_id TEXT PRIMARY KEY, job_type TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued', priority INTEGER NOT NULL DEFAULT 100, attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 3, lease_token TEXT, lease_expires_at TEXT, worker_id TEXT, idempotency_key TEXT UNIQUE, cancellation_requested INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_heartbeat_at TEXT, completed_at TEXT, error_message TEXT, result_payload TEXT)")
        conn.execute("CREATE TABLE approval_records (approval_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, decision TEXT NOT NULL, reviewer TEXT NOT NULL, notes TEXT, reviewed_at TEXT NOT NULL)")

        conn.execute("INSERT INTO products VALUES ('p1', 'Prod 1', 'https://shopee.co.id/p1', 1000.0, NULL, 'manual', NULL)")
        conn.execute("INSERT INTO content_drafts VALUES ('d1', 'p1', 'a', 'h', 's', 'c', 'cta', '#ai', 'draft', 'v1.0', '2026-11-06T00:00:00Z')")
        conn.execute("INSERT INTO jobs (job_id, job_type, payload, created_at, updated_at) VALUES ('j1', 'task', '{}', '2026-11-06T00:00:00Z', '2026-11-06T00:00:00Z')")
        conn.execute("INSERT INTO approval_records VALUES ('app_dup_1', 'j1', 'APPROVED', 'rev_1', 'First approval', '2026-11-06T01:00:00Z')")
        conn.execute("INSERT INTO approval_records VALUES ('app_dup_2', 'j1', 'approved', 'rev_2', 'Conflicting approval', '2026-11-06T02:00:00Z')")
        conn.commit()
        conn.close()

        # Opening Database migrates cleanly without UNIQUE constraint failure
        db = Database(db_path)
        quarantined = db.get_quarantined_approval_records("j1")
        self.assertEqual(len(quarantined), 2)
        q_reasons = [q["quarantine_reason"] for q in quarantined]
        self.assertTrue(all("duplicate_legacy_approval" in r for r in q_reasons))

        # Neither duplicate approval is in approval_records, so cannot authorize export
        self.assertEqual(len(db.get_approval_records("j1")), 0)
        self.assertFalse(db.can_authorize_export("j1", "d1", "v1.0"))

        # PRAGMA integrity_check is ok
        raw = db.get_connection()
        try:
            self.assertEqual(raw.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        finally:
            raw.close()

    def test_backup_failure_aborts_migration_without_corruption(self) -> None:
        """If mandatory pre-migration backup fails, migration halts immediately and raises RuntimeError."""
        db_path = Path(self.temp_dir.name) / "existing_user_db.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE products (id TEXT PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL UNIQUE, price REAL, price_observed_at TEXT, source TEXT NOT NULL, notes TEXT)")
        conn.execute("INSERT INTO products VALUES ('p_keep', 'Important Product', 'https://shopee.co.id/keep', 50000.0, NULL, 'manual', NULL)")
        conn.commit()
        conn.close()

        # Simulate backup failure
        with patch.object(Database, "create_safe_database_backup", side_effect=IOError("Disk permission denied")):
            with self.assertRaises(RuntimeError) as ctx:
                Database(db_path)
            self.assertIn("pre-migration backup failed", str(ctx.exception).lower())

        # Verify database was NOT migrated and original data is completely intact
        check_conn = sqlite3.connect(str(db_path))
        ver = check_conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(ver, 0)
        prod = check_conn.execute("SELECT name FROM products WHERE id = 'p_keep'").fetchone()
        self.assertIsNotNone(prod)
        self.assertEqual(prod[0], "Important Product")
        check_conn.close()

    def test_failed_migration_leaves_sqlite_master_identical_to_pre_migration_state(self) -> None:
        """Atomic rollback on failed migration leaves sqlite_master byte-for-byte identical."""
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

        check_conn = sqlite3.connect(str(db_path))
        pre_master = sorted(check_conn.execute("SELECT type, name, sql FROM sqlite_master").fetchall())
        pre_tables = sorted([r[0] for r in check_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()])
        check_conn.close()

        with self.assertRaises(RuntimeError) as ctx:
            Database(db_path)
        self.assertIn("failed foreign key validation", str(ctx.exception).lower())

        post_conn = sqlite3.connect(str(db_path))
        post_master = sorted(post_conn.execute("SELECT type, name, sql FROM sqlite_master").fetchall())
        post_tables = sorted([r[0] for r in post_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()])
        post_conn.close()

        self.assertEqual(pre_master, post_master)
        self.assertEqual(pre_tables, post_tables)

    def test_raw_sql_cannot_insert_invalid_binding_constraints(self) -> None:
        """SQLite engine-level constraints reject invalid SHA, attempt, and partial bindings via raw SQL."""
        db_path = Path(self.temp_dir.name) / "raw_sql_constraints.db"
        db = Database(db_path)
        conn = db.get_connection()
        try:
            # Seed job and draft
            db.insert_product(Product(id="p_raw", name="Raw Prod", url="https://shopee.co.id/raw", source="manual"))
            db.upsert_draft(ContentDraft(
                id="d_raw", product_id="p_raw", angle="a", hook="h", script="s",
                caption="c", cta="cta", disclosure_text="#ai", status="draft", prompt_version="v1.0"
            ))
            job = db.submit_job("content_pipeline", {"draft_id": "d_raw"})

            valid_sha = hashlib.sha256(b"content").hexdigest()
            valid_fp = hashlib.sha256(b"claims").hexdigest()

            # 1. Reject invalid content_sha256 (too short: 63 chars)
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO approval_records (
                        approval_id, job_id, decision, reviewer, reviewed_at,
                        draft_id, prompt_version, claims_fingerprint, content_sha256, job_attempt
                    ) VALUES ('bad_1', ?, 'APPROVE', 'rev', '2026-11-06T00:00:00Z', 'd_raw', 'v1.0', ?, ?, 1)
                    """,
                    (job.job_id, valid_fp, "a" * 63),
                )

            # 2. Reject non-hex characters in content_sha256 ('fake_sha' or containing 'z')
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO approval_records (
                        approval_id, job_id, decision, reviewer, reviewed_at,
                        draft_id, prompt_version, claims_fingerprint, content_sha256, job_attempt
                    ) VALUES ('bad_2', ?, 'APPROVE', 'rev', '2026-11-06T00:00:00Z', 'd_raw', 'v1.0', ?, ?, 1)
                    """,
                    (job.job_id, valid_fp, "z" + "a" * 63),
                )

            # 3. Reject uppercase hex in raw SQL (enforcing lowercase hex)
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO approval_records (
                        approval_id, job_id, decision, reviewer, reviewed_at,
                        draft_id, prompt_version, claims_fingerprint, content_sha256, job_attempt
                    ) VALUES ('bad_3', ?, 'APPROVE', 'rev', '2026-11-06T00:00:00Z', 'd_raw', 'v1.0', ?, ?, 1)
                    """,
                    (job.job_id, valid_fp, "A" * 64),
                )

            # 4. Reject partial binding (e.g. draft_id set but content_sha256 is NULL)
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO approval_records (
                        approval_id, job_id, decision, reviewer, reviewed_at,
                        draft_id, prompt_version, claims_fingerprint, content_sha256, job_attempt
                    ) VALUES ('bad_4', ?, 'APPROVE', 'rev', '2026-11-06T00:00:00Z', 'd_raw', 'v1.0', ?, NULL, 1)
                    """,
                    (job.job_id, valid_fp),
                )

            # 5. Reject job_attempt = 0
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO approval_records (
                        approval_id, job_id, decision, reviewer, reviewed_at,
                        draft_id, prompt_version, claims_fingerprint, content_sha256, job_attempt
                    ) VALUES ('bad_5', ?, 'APPROVE', 'rev', '2026-11-06T00:00:00Z', 'd_raw', 'v1.0', ?, ?, 0)
                    """,
                    (job.job_id, valid_fp, valid_sha),
                )
        finally:
            conn.close()

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
                content_sha256=hashlib.sha256(b"authentic_content_sha").hexdigest(),
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
