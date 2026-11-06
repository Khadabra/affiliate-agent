"""Phase A2.1 & A2.1.1 Unit and Concurrency Tests:
Transaction Boundaries, Persistent Queue Fencing, Safe Backup & Schema Verification.

Validates:
1. TransactionScope invariants: self-managed vs. caller-owned connection semantics,
   premature commit prevention, nested helper isolation, inactive transaction rejection,
   and commit failure recovery on cached :memory: connections.
2. Persistent Job Queue operations: submission, idempotency, atomic claiming with lease tokens,
   strict multi-attribute fencing (job_id, worker_id, lease_token, status='running', lease not expired)
   for heartbeat, completion, and failure.
3. Stale worker rejection: heartbeat, complete, and fail rejected after lease expiry or reclaim.
4. Multiprocessing concurrency: race-free atomic claim under multiple independent processes (Windows spawn safe).
5. Schema migration verification: PRAGMA foreign_key_check enforcement and rollback.
6. Safe Online Database Backup: WAL mode compatibility, integrity verification, and non-destructive failure handling.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

from affiliate_factory.db import (
    ApprovalRecord,
    Database,
    JobRecord,
    JobRunRecord,
    JobStatus,
    TransactionScope,
    TransactionScopeError,
    create_safe_database_backup,
)
from affiliate_factory.models import ContentDraft, Product


def _worker_claim_task(db_path: str, worker_id: str, results_queue: Any) -> None:
    """Top-level worker task for multiprocessing claim concurrency tests (Windows spawn compatible)."""
    try:
        db = Database(db_path)
        claimed = db.claim_next_job(worker_id=worker_id, lease_duration_seconds=30)
        if claimed is not None:
            results_queue.put((worker_id, claimed.job_id, claimed.lease_token))
        else:
            results_queue.put((worker_id, None, None))
    except Exception as e:
        results_queue.put((worker_id, "ERROR", str(e)))


class TestTransactionScope(unittest.TestCase):
    """Test SQLite TransactionScope boundary management and connection ownership contracts."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_tx.db"
        self.db = Database(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_self_managed_commit_on_success(self) -> None:
        """Self-managed TransactionScope automatically commits on normal block exit."""
        product = Product(
            id="prod_tx_1",
            name="Product 1",
            url="https://shopee.co.id/product-1",
            price=50000.0,
            source="manual",
        )
        inserted = self.db.insert_product(product)
        self.assertTrue(inserted)

        verify_conn = sqlite3.connect(str(self.db_path))
        verify_conn.row_factory = sqlite3.Row
        try:
            row = verify_conn.execute("SELECT * FROM products WHERE id = ?", ("prod_tx_1",)).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["name"], "Product 1")
        finally:
            verify_conn.close()

    def test_self_managed_rollback_on_exception(self) -> None:
        """Self-managed TransactionScope automatically rolls back when an exception is raised."""
        try:
            with TransactionScope(self.db) as conn:
                conn.execute(
                    "INSERT INTO products (id, name, url, price, source) VALUES (?, ?, ?, ?, ?)",
                    ("prod_tx_err", "Product Error", "https://shopee.co.id/product-err", 1000.0, "manual"),
                )
                raise RuntimeError("Simulated failure inside transaction block")
        except RuntimeError:
            pass

        verify_conn = sqlite3.connect(str(self.db_path))
        try:
            row = verify_conn.execute("SELECT * FROM products WHERE id = ?", ("prod_tx_err",)).fetchone()
            self.assertIsNone(row)
        finally:
            verify_conn.close()

    def test_caller_owned_connection_not_committed_by_helper(self) -> None:
        """Caller-owned connection is NOT committed when an inner helper exits."""
        caller_conn = self.db.get_connection()
        caller_conn.execute("BEGIN IMMEDIATE")
        try:
            product = Product(
                id="prod_tx_caller",
                name="Product Caller",
                url="https://shopee.co.id/product-caller",
                price=75000.0,
                source="manual",
            )
            self.db.insert_product(product, conn=caller_conn)

            verify_conn = sqlite3.connect(str(self.db_path))
            try:
                row = verify_conn.execute("SELECT * FROM products WHERE id = ?", ("prod_tx_caller",)).fetchone()
                self.assertIsNone(row, "Helper prematurely committed uncommitted caller transaction!")
            finally:
                verify_conn.close()

            caller_conn.commit()

            verify_conn2 = sqlite3.connect(str(self.db_path))
            try:
                row = verify_conn2.execute("SELECT * FROM products WHERE id = ?", ("prod_tx_caller",)).fetchone()
                self.assertIsNotNone(row)
            finally:
                verify_conn2.close()
        finally:
            caller_conn.close()

    def test_caller_owned_connection_rolled_back_by_caller(self) -> None:
        """Caller-owned connection rollback cleanly rolls back all helper writes."""
        caller_conn = self.db.get_connection()
        caller_conn.execute("BEGIN IMMEDIATE")
        try:
            product = Product(
                id="prod_tx_rb",
                name="Product Rollback",
                url="https://shopee.co.id/product-rb",
                price=85000.0,
                source="manual",
            )
            self.db.insert_product(product, conn=caller_conn)

            draft = ContentDraft(
                id="draft_tx_rb",
                product_id="prod_tx_rb",
                angle="Test Angle",
                hook="Test Hook",
                script="Test Script",
                caption="Test Caption",
                cta="Test CTA",
                disclosure_text="#ShopeeAffiliate",
                status="draft",
                prompt_version="v1.0",
            )
            self.db.upsert_draft(draft, conn=caller_conn)

            caller_conn.rollback()
        finally:
            caller_conn.close()

        verify_conn = sqlite3.connect(str(self.db_path))
        try:
            p_row = verify_conn.execute("SELECT * FROM products WHERE id = ?", ("prod_tx_rb",)).fetchone()
            d_row = verify_conn.execute("SELECT * FROM content_drafts WHERE id = ?", ("draft_tx_rb",)).fetchone()
            self.assertIsNone(p_row)
            self.assertIsNone(d_row)
        finally:
            verify_conn.close()

    def test_caller_owned_connection_without_active_transaction_rejected(self) -> None:
        """Providing a caller connection where in_transaction is False raises TransactionScopeError."""
        caller_conn = self.db.get_connection()
        try:
            self.assertFalse(caller_conn.in_transaction)
            product = Product(
                id="prod_tx_fail",
                name="Product Fail",
                url="https://shopee.co.id/product-fail",
                price=10000.0,
                source="manual",
            )
            with self.assertRaises(TransactionScopeError):
                self.db.insert_product(product, conn=caller_conn)
        finally:
            caller_conn.close()

    def test_nested_helper_calls_isolation(self) -> None:
        """Multiple helpers sharing one caller-owned transaction execute atomically without interference."""
        caller_conn = self.db.get_connection()
        caller_conn.execute("BEGIN IMMEDIATE")
        try:
            product = Product(
                id="prod_tx_nested",
                name="Product Nested",
                url="https://shopee.co.id/product-nested",
                price=99000.0,
                source="manual",
            )
            self.db.insert_product(product, conn=caller_conn)

            draft = ContentDraft(
                id="draft_tx_nested",
                product_id="prod_tx_nested",
                angle="Angle 1",
                hook="Hook 1",
                script="Script 1",
                caption="Caption 1",
                cta="CTA 1",
                disclosure_text="#ShopeeAffiliate",
                status="draft",
                prompt_version="v1.0",
            )
            self.db.upsert_draft(draft, conn=caller_conn)

            self.db.update_draft_status("draft_tx_nested", "v1.0", "waiting_approval", conn=caller_conn)

            d = self.db.get_draft("draft_tx_nested", "v1.0", conn=caller_conn)
            self.assertIsNotNone(d)
            self.assertEqual(d.status, "waiting_approval")

            caller_conn.commit()
        finally:
            caller_conn.close()

        d_after = self.db.get_draft("draft_tx_nested", "v1.0")
        self.assertIsNotNone(d_after)
        self.assertEqual(d_after.status, "waiting_approval")

    def test_memory_db_commit_failure_recovery(self) -> None:
        """Commit failure on self-managed :memory: connection rolls back and leaves connection reusable."""
        class ControllableConnection(sqlite3.Connection):
            should_fail_commit = False

            def commit(self) -> None:
                if self.should_fail_commit:
                    raise sqlite3.OperationalError("Simulated commit disk I/O error")
                super().commit()

        mem_db = Database(":memory:")
        if mem_db._conn is not None:
            mem_db._conn.close()

        raw_conn = sqlite3.connect(":memory:", timeout=5.0, factory=ControllableConnection)
        raw_conn.row_factory = sqlite3.Row
        raw_conn.execute("PRAGMA foreign_keys = ON")
        raw_conn.execute("PRAGMA busy_timeout = 5000")
        mem_db._conn = raw_conn
        mem_db.init_schema()

        raw_conn.should_fail_commit = True
        try:
            with self.assertRaises(sqlite3.OperationalError):
                with TransactionScope(mem_db) as conn:
                    conn.execute("CREATE TABLE test_table (id INT)")
                    conn.execute("INSERT INTO test_table VALUES (1)")
        finally:
            raw_conn.should_fail_commit = False

        # In-memory connection must NOT be left in an active transaction
        self.assertFalse(raw_conn.in_transaction, "Connection was left in active transaction after commit failure!")

        # Subsequent transaction on the same in-memory DB must succeed cleanly
        with TransactionScope(mem_db) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS test_table2 (id INT)")
            conn.execute("INSERT INTO test_table2 VALUES (42)")

        row = raw_conn.execute("SELECT * FROM test_table2 WHERE id = 42").fetchone()
        self.assertIsNotNone(row)
        raw_conn.close()

    def test_caller_owned_connection_not_automatically_rolled_back_on_internal_exception(self) -> None:
        """Caller-owned transaction is not automatically rolled back when an internal helper raises an exception."""
        caller_conn = self.db.get_connection()
        caller_conn.execute("BEGIN IMMEDIATE")
        try:
            self.assertTrue(caller_conn.in_transaction)

            # Insert initial product
            p1 = Product(id="prod_keep", name="Keep", url="https://shopee.co.id/keep", price=100.0, source="manual")
            self.db.insert_product(p1, conn=caller_conn)

            # An inner helper block raises an error
            try:
                with TransactionScope(self.db, conn=caller_conn) as c:
                    raise ValueError("Internal helper error")
            except ValueError:
                pass

            # TransactionScope must NOT have rolled back or committed caller_conn
            self.assertTrue(caller_conn.in_transaction, "Caller-owned transaction was rolled back prematurely!")

            # Caller can continue working in the same transaction
            p2 = Product(id="prod_keep2", name="Keep 2", url="https://shopee.co.id/keep2", price=200.0, source="manual")
            self.db.insert_product(p2, conn=caller_conn)

            caller_conn.commit()
        finally:
            caller_conn.close()

        # Both products committed successfully by caller
        self.assertIsNotNone(self.db.get_product("prod_keep"))
        self.assertIsNotNone(self.db.get_product("prod_keep2"))


class TestPersistentJobQueue(unittest.TestCase):
    """Test persistent job queue submission, claiming, leasing, fencing, and lifecycle."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_queue.db"
        self.db = Database(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_submit_job_queued_status(self) -> None:
        """Submitting a job creates a record with status 'queued' and initial attempts 0."""
        payload = {"product_id": "prod_1", "angle": "benefit"}
        job = self.db.submit_job(job_type="content_generation", payload=payload, priority=50)

        self.assertIsNotNone(job.job_id)
        self.assertEqual(job.job_type, "content_generation")
        self.assertEqual(job.status, JobStatus.QUEUED)
        self.assertEqual(job.priority, 50)
        self.assertEqual(job.attempts, 0)
        self.assertIsNone(job.lease_token)
        self.assertFalse(job.cancellation_requested)

        loaded = self.db.get_job(job.job_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.job_id, job.job_id)
        self.assertEqual(loaded.payload, payload)

    def test_submit_job_idempotency(self) -> None:
        """Submitting a job with duplicate idempotency_key returns existing record without duplicating."""
        key = "idemp_unique_key_123"
        job1 = self.db.submit_job("research", {"query": "shopee"}, idempotency_key=key)
        job2 = self.db.submit_job("research", {"query": "shopee"}, idempotency_key=key)

        self.assertEqual(job1.job_id, job2.job_id)
        self.assertEqual(job1.created_at, job2.created_at)

        all_jobs = self.db.list_jobs()
        self.assertEqual(len(all_jobs), 1)

    def test_claim_next_job_priority_and_fifo(self) -> None:
        """Claiming picks lower priority number first, then oldest created_at for tie-breaking."""
        j_low = self.db.submit_job("work", {"name": "low"}, priority=200)
        time.sleep(0.01)
        j_high1 = self.db.submit_job("work", {"name": "high1"}, priority=10)
        time.sleep(0.01)
        j_high2 = self.db.submit_job("work", {"name": "high2"}, priority=10)

        c1 = self.db.claim_next_job("worker_1")
        self.assertIsNotNone(c1)
        self.assertEqual(c1.job_id, j_high1.job_id)

        c2 = self.db.claim_next_job("worker_1")
        self.assertIsNotNone(c2)
        self.assertEqual(c2.job_id, j_high2.job_id)

        c3 = self.db.claim_next_job("worker_1")
        self.assertIsNotNone(c3)
        self.assertEqual(c3.job_id, j_low.job_id)

        c4 = self.db.claim_next_job("worker_1")
        self.assertIsNone(c4)

    def test_claim_next_job_supported_types(self) -> None:
        """Workers with supported_types filter only claim matching job types."""
        self.db.submit_job("type_a", {"val": "a"})
        j_b = self.db.submit_job("type_b", {"val": "b"})

        worker_b_claim = self.db.claim_next_job("worker_b", supported_types=["type_b"])
        self.assertIsNotNone(worker_b_claim)
        self.assertEqual(worker_b_claim.job_id, j_b.job_id)
        self.assertEqual(worker_b_claim.job_type, "type_b")

    def test_claim_next_job_lease_and_run_record(self) -> None:
        """Claiming updates status to running, increments attempts, sets lease, and inserts job_run."""
        job = self.db.submit_job("task", {"param": 1}, max_attempts=3)
        claimed = self.db.claim_next_job("worker_alpha", lease_duration_seconds=45)

        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.status, JobStatus.RUNNING)
        self.assertEqual(claimed.attempts, 1)
        self.assertEqual(claimed.worker_id, "worker_alpha")
        self.assertIsNotNone(claimed.lease_token)
        self.assertIsNotNone(claimed.lease_expires_at)
        self.assertIsNotNone(claimed.last_heartbeat_at)

        runs = self.db.get_job_runs(job.job_id)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].attempt_number, 1)
        self.assertEqual(runs[0].worker_id, "worker_alpha")
        self.assertIsNone(runs[0].ended_at)

    def test_heartbeat_job_lifecycle(self) -> None:
        """Heartbeat extends lease if active; fails if lease expired, wrong worker, or wrong token."""
        job = self.db.submit_job("task", {})
        claimed = self.db.claim_next_job("worker_hb", lease_duration_seconds=30)
        self.assertIsNotNone(claimed)

        # Valid heartbeat
        ok = self.db.heartbeat_job(claimed.job_id, "worker_hb", claimed.lease_token, extend_seconds=60)
        self.assertTrue(ok)

        # Wrong token rejected
        bad_token_ok = self.db.heartbeat_job(claimed.job_id, "worker_hb", "wrong_token", extend_seconds=60)
        self.assertFalse(bad_token_ok)

        # Wrong worker rejected
        bad_worker_ok = self.db.heartbeat_job(claimed.job_id, "wrong_worker", claimed.lease_token, extend_seconds=60)
        self.assertFalse(bad_worker_ok)

        # Artificially expire lease in DB to verify expired heartbeat rejection
        past_iso = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        with TransactionScope(self.db) as conn:
            conn.execute("UPDATE jobs SET lease_expires_at = ? WHERE job_id = ?", (past_iso, claimed.job_id))

        expired_hb_ok = self.db.heartbeat_job(claimed.job_id, "worker_hb", claimed.lease_token, extend_seconds=60)
        self.assertFalse(expired_hb_ok, "Heartbeat should NOT revive an expired lease!")

    def test_complete_job_success_and_fencing(self) -> None:
        """Completing a job records result_payload, marks completed, and prevents completion after lease expiry."""
        job = self.db.submit_job("task", {})
        claimed = self.db.claim_next_job("worker_c", lease_duration_seconds=30)
        self.assertIsNotNone(claimed)

        result_data = {"output": "success", "score": 98.5}
        ok = self.db.complete_job(claimed.job_id, "worker_c", claimed.lease_token, result_payload=result_data)
        self.assertTrue(ok)

        completed_job = self.db.get_job(claimed.job_id)
        self.assertEqual(completed_job.status, JobStatus.COMPLETED)
        self.assertEqual(completed_job.result_payload, result_data)
        self.assertIsNone(completed_job.lease_token)
        self.assertIsNotNone(completed_job.completed_at)

        runs = self.db.get_job_runs(claimed.job_id)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].final_status, "completed")
        self.assertIsNotNone(runs[0].ended_at)

        # Expired lease fencing test on another job
        job2 = self.db.submit_job("task2", {})
        claimed2 = self.db.claim_next_job("worker_c2", lease_duration_seconds=30)
        past_iso = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
        with TransactionScope(self.db) as conn:
            conn.execute("UPDATE jobs SET lease_expires_at = ? WHERE job_id = ?", (past_iso, claimed2.job_id))

        fenced_ok = self.db.complete_job(claimed2.job_id, "worker_c2", claimed2.lease_token, {"out": "too_late"})
        self.assertFalse(fenced_ok, "complete_job must reject completion with expired lease!")

    def test_fail_job_success_and_fencing(self) -> None:
        """Failing a job records error_message, marks failed, and rejects expired lease."""
        job = self.db.submit_job("task", {})
        claimed = self.db.claim_next_job("worker_fail", lease_duration_seconds=30)
        self.assertIsNotNone(claimed)

        failed_ok = self.db.fail_job(claimed.job_id, "worker_fail", claimed.lease_token, "Network timeout during API call")
        self.assertTrue(failed_ok)

        failed_job = self.db.get_job(claimed.job_id)
        self.assertEqual(failed_job.status, JobStatus.FAILED)
        self.assertEqual(failed_job.error_message, "Network timeout during API call")
        self.assertIsNone(failed_job.lease_token)

        runs = self.db.get_job_runs(claimed.job_id)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].final_status, "failed")
        self.assertEqual(runs[0].error_message, "Network timeout during API call")

    def test_fail_job_rejected_on_expired_lease_before_reclaim(self) -> None:
        """fail_job cannot modify a job whose lease has expired even if not yet reclaimed."""
        job = self.db.submit_job("task_expire_fail", {})
        claimed = self.db.claim_next_job("worker_ef", lease_duration_seconds=10)
        self.assertIsNotNone(claimed)

        past_iso = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        with TransactionScope(self.db) as conn:
            conn.execute("UPDATE jobs SET lease_expires_at = ? WHERE job_id = ?", (past_iso, claimed.job_id))

        # Attempt to fail after lease expired
        ok = self.db.fail_job(claimed.job_id, "worker_ef", claimed.lease_token, "Too late failure")
        self.assertFalse(ok, "fail_job should be rejected when lease has expired!")

        # Job must still be running (not killed prematurely)
        j = self.db.get_job(claimed.job_id)
        self.assertEqual(j.status, JobStatus.RUNNING)

    def test_stale_worker_rejection_after_reclaim(self) -> None:
        """Worker A with expired lease cannot heartbeat, complete, or fail job after Worker B reclaims it."""
        job = self.db.submit_job("task_reclaim", {}, max_attempts=3)
        claimed_a = self.db.claim_next_job("worker_a", lease_duration_seconds=10)
        self.assertIsNotNone(claimed_a)

        # Worker A lease expires
        past_iso = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        with TransactionScope(self.db) as conn:
            conn.execute("UPDATE jobs SET lease_expires_at = ? WHERE job_id = ?", (past_iso, claimed_a.job_id))

        # Worker B reclaims job
        claimed_b = self.db.claim_next_job("worker_b", lease_duration_seconds=30)
        self.assertIsNotNone(claimed_b)
        self.assertEqual(claimed_b.job_id, job.job_id)
        self.assertEqual(claimed_b.worker_id, "worker_b")
        self.assertNotEqual(claimed_b.lease_token, claimed_a.lease_token)

        # 1. Worker A cannot heartbeat
        hb_a = self.db.heartbeat_job(job.job_id, "worker_a", claimed_a.lease_token)
        self.assertFalse(hb_a)

        # 2. Worker A cannot complete
        comp_a = self.db.complete_job(job.job_id, "worker_a", claimed_a.lease_token, {"result": "stale_data"})
        self.assertFalse(comp_a)

        # 3. Worker A cannot fail
        fail_a = self.db.fail_job(job.job_id, "worker_a", claimed_a.lease_token, "stale_error")
        self.assertFalse(fail_a)

        # Verify job is still running under Worker B
        current_job = self.db.get_job(job.job_id)
        self.assertEqual(current_job.status, JobStatus.RUNNING)
        self.assertEqual(current_job.worker_id, "worker_b")
        self.assertEqual(current_job.lease_token, claimed_b.lease_token)

    def test_worker_and_token_identity_fencing(self) -> None:
        """Wrong worker ID with correct token, and wrong token with correct worker ID are both strictly rejected."""
        job = self.db.submit_job("task_fencing", {})
        claimed = self.db.claim_next_job("worker_valid", lease_duration_seconds=30)
        self.assertIsNotNone(claimed)

        # 1. Wrong worker ID with correct token rejected
        self.assertFalse(self.db.heartbeat_job(claimed.job_id, "worker_wrong", claimed.lease_token))
        self.assertFalse(self.db.complete_job(claimed.job_id, "worker_wrong", claimed.lease_token))
        self.assertFalse(self.db.fail_job(claimed.job_id, "worker_wrong", claimed.lease_token, "err"))

        # 2. Correct worker ID with wrong token rejected
        self.assertFalse(self.db.heartbeat_job(claimed.job_id, "worker_valid", "token_wrong"))
        self.assertFalse(self.db.complete_job(claimed.job_id, "worker_valid", "token_wrong"))
        self.assertFalse(self.db.fail_job(claimed.job_id, "worker_valid", "token_wrong", "err"))

    def test_stale_recovery_requeue(self) -> None:
        """An expired running job with attempts < max_attempts is swept back to queued on next claim."""
        job = self.db.submit_job("task", {}, max_attempts=2)
        claimed1 = self.db.claim_next_job("worker_1", lease_duration_seconds=10)
        self.assertIsNotNone(claimed1)
        self.assertEqual(claimed1.attempts, 1)

        past_iso = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        with TransactionScope(self.db) as conn:
            conn.execute("UPDATE jobs SET lease_expires_at = ? WHERE job_id = ?", (past_iso, claimed1.job_id))

        claimed2 = self.db.claim_next_job("worker_2", lease_duration_seconds=20)
        self.assertIsNotNone(claimed2)
        self.assertEqual(claimed2.job_id, job.job_id)
        self.assertEqual(claimed2.attempts, 2)
        self.assertEqual(claimed2.worker_id, "worker_2")
        self.assertNotEqual(claimed2.lease_token, claimed1.lease_token)

        runs = self.db.get_job_runs(job.job_id)
        self.assertEqual(len(runs), 2)
        self.assertEqual(runs[0].attempt_number, 1)
        self.assertEqual(runs[0].final_status, "expired")
        self.assertEqual(runs[1].attempt_number, 2)
        self.assertIsNone(runs[1].ended_at)

    def test_stale_recovery_terminal_fail(self) -> None:
        """An expired running job with attempts >= max_attempts is permanently marked failed."""
        job = self.db.submit_job("task", {}, max_attempts=1)
        claimed = self.db.claim_next_job("worker_1", lease_duration_seconds=10)
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.attempts, 1)

        past_iso = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        with TransactionScope(self.db) as conn:
            conn.execute("UPDATE jobs SET lease_expires_at = ? WHERE job_id = ?", (past_iso, claimed.job_id))

        next_claim = self.db.claim_next_job("worker_2")
        self.assertIsNone(next_claim)

        failed_job = self.db.get_job(job.job_id)
        self.assertEqual(failed_job.status, JobStatus.FAILED)
        self.assertIn("Lease expired after 1 attempts", failed_job.error_message or "")

    def test_cancel_job_lifecycle(self) -> None:
        """Test cancelling queued vs. running vs. terminal jobs."""
        # 1. Queued job cancelled immediately
        job1 = self.db.submit_job("task1", {})
        c1_ok = self.db.cancel_job(job1.job_id)
        self.assertTrue(c1_ok)
        j1_after = self.db.get_job(job1.job_id)
        self.assertEqual(j1_after.status, JobStatus.CANCELLED)
        self.assertTrue(j1_after.cancellation_requested)
        self.assertIsNone(self.db.claim_next_job("w"))

        # 2. Running job flags cancellation_requested=1
        job2 = self.db.submit_job("task2", {})
        claimed2 = self.db.claim_next_job("w")
        c2_ok = self.db.cancel_job(claimed2.job_id)
        self.assertTrue(c2_ok)
        j2_after = self.db.get_job(claimed2.job_id)
        self.assertEqual(j2_after.status, JobStatus.RUNNING)
        self.assertTrue(j2_after.cancellation_requested)

        # 3. Terminal job returns False on cancel
        self.db.complete_job(claimed2.job_id, "w", claimed2.lease_token)
        c3_ok = self.db.cancel_job(claimed2.job_id)
        self.assertFalse(c3_ok)

    def test_approval_records(self) -> None:
        """Approval and rejection records can be saved and retrieved in chronological order."""
        self.db.insert_product(Product(id="p_appr", name="Prod Appr", url="https://shopee.co.id/appr", source="manual"))
        self.db.upsert_draft(ContentDraft(
            id="draft_appr",
            product_id="p_appr",
            angle="angle",
            hook="hook",
            script="script",
            caption="caption",
            cta="cta",
            disclosure_text="#ShopeeAffiliate",
            status="waiting_approval",
            prompt_version="v1.0",
        ))
        job = self.db.submit_job("content_pipeline", {"draft_id": "draft_appr"})
        now_iso = datetime.now(timezone.utc).isoformat()
        approval = ApprovalRecord(
            approval_id="appr_1",
            job_id=job.job_id,
            decision="approved",
            reviewer="human_editor_1",
            notes="Passed fact checking and quality gate",
            reviewed_at=now_iso,
            draft_id="draft_appr",
            prompt_version="v1.0",
            claims_fingerprint="claims_fp_sample",
            content_sha256="content_sha_sample",
            job_attempt=1,
        )
        self.db.save_approval_record(approval)

        records = self.db.get_approval_records(job.job_id)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].approval_id, "appr_1")
        self.assertEqual(records[0].decision, "APPROVE")
        self.assertEqual(records[0].reviewer, "human_editor_1")
        self.assertEqual(records[0].draft_id, "draft_appr")
        self.assertEqual(records[0].prompt_version, "v1.0")
        self.assertEqual(records[0].content_sha256, "content_sha_sample")
        self.assertEqual(records[0].claims_fingerprint, "claims_fp_sample")
        self.assertEqual(records[0].job_attempt, 1)


class TestMigrationValidation(unittest.TestCase):
    """Test database migration validation and rollback upon foreign key violations."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_migration_fails_and_rolls_back_on_foreign_key_violation(self) -> None:
        """When an invalid database state with broken foreign keys is opened, migration fails with RuntimeError."""
        db_path = Path(self.temp_dir.name) / "broken_fk.db"
        raw_conn = sqlite3.connect(str(db_path))
        # Create schema with broken FK without orphan preservation
        raw_conn.execute("PRAGMA foreign_keys = OFF")
        raw_conn.execute("CREATE TABLE products (id TEXT PRIMARY KEY, name TEXT, url TEXT UNIQUE, source TEXT)")
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
        # Insert draft pointing to non-existent product
        raw_conn.execute(
            """
            INSERT INTO content_drafts VALUES (
                'orphan_draft', 'missing_prod_id', 'a', 'h', 's', 'c', 'cta', '#ai', 'draft', 'v1.0', '2026-11-05T00:00:00Z'
            )
            """
        )
        raw_conn.commit()
        raw_conn.close()

        # Opening Database initializes schema and enforces PRAGMA foreign_key_check
        with self.assertRaises(RuntimeError) as ctx:
            Database(db_path)

        self.assertIn("failed foreign key validation", str(ctx.exception).lower())
        self.assertIn("content_drafts", str(ctx.exception))


class TestJobQueueConcurrency(unittest.TestCase):
    """Test multiprocessing concurrent claim safety under Windows spawn multiprocessing."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "concurrent_queue.db"
        self.db = Database(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_multiprocessing_claim_race(self) -> None:
        """When 2 independent processes race to claim 1 queued job, exactly one wins."""
        job = self.db.submit_job("heavy_task", {"target": "process_race"})

        ctx = mp.get_context("spawn")
        results_queue = ctx.Queue()

        p1 = ctx.Process(target=_worker_claim_task, args=(str(self.db_path), "proc_1", results_queue))
        p2 = ctx.Process(target=_worker_claim_task, args=(str(self.db_path), "proc_2", results_queue))

        p1.start()
        p2.start()

        p1.join(timeout=10)
        p2.join(timeout=10)

        results = []
        while not results_queue.empty():
            results.append(results_queue.get_nowait())

        self.assertEqual(len(results), 2, f"Expected 2 worker responses, got: {results}")

        winners = [r for r in results if r[1] == job.job_id]
        losers = [r for r in results if r[1] is None]

        self.assertEqual(len(winners), 1, f"Expected exactly 1 winner, results were: {results}")
        self.assertEqual(len(losers), 1, f"Expected exactly 1 loser, results were: {results}")

        runs = self.db.get_job_runs(job.job_id)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].attempt_number, 1)
        self.assertEqual(runs[0].worker_id, winners[0][0])


class TestSafeDatabaseBackup(unittest.TestCase):
    """Test SQLite WAL online backup integrity, atomic rename, and failure safety."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "live_db.db"
        self.backup_dir = Path(self.temp_dir.name) / "backups"
        self.db = Database(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_safe_backup_in_wal_mode(self) -> None:
        """Online backup in active WAL mode succeeds with passing PRAGMA integrity_check."""
        for i in range(5):
            self.db.insert_product(
                Product(
                    id=f"prod_bk_{i}",
                    name=f"Backup Product {i}",
                    url=f"https://shopee.co.id/backup-prod-{i}",
                    price=float(i * 10000),
                    source="manual",
                )
            )

        backup_file = self.db.create_safe_database_backup(self.backup_dir, backup_name="snapshot_1.db")

        self.assertTrue(backup_file.exists())
        self.assertEqual(backup_file.name, "snapshot_1.db")

        check_conn = sqlite3.connect(str(backup_file))
        check_conn.row_factory = sqlite3.Row
        try:
            integrity = check_conn.execute("PRAGMA integrity_check").fetchone()[0]
            self.assertEqual(str(integrity).lower(), "ok")

            rows = check_conn.execute("SELECT * FROM products").fetchall()
            self.assertEqual(len(rows), 5)
        finally:
            check_conn.close()

    def test_module_level_backup_helper(self) -> None:
        """Module-level create_safe_database_backup helper operates identically."""
        self.db.submit_job("test_job", {"data": 123})
        backup_file = create_safe_database_backup(self.db, self.backup_dir)

        self.assertTrue(backup_file.exists())
        check_conn = sqlite3.connect(str(backup_file))
        try:
            integrity = check_conn.execute("PRAGMA integrity_check").fetchone()[0]
            self.assertEqual(str(integrity).lower(), "ok")
        finally:
            check_conn.close()

    def test_backup_failure_does_not_corrupt_existing_valid_backup(self) -> None:
        """A failed backup attempt does not overwrite or corrupt a pre-existing valid backup file."""
        self.db.insert_product(
            Product(id="p_original", name="Original", url="https://shopee.co.id/orig", price=100.0, source="manual")
        )

        # 1. First backup succeeds
        target_name = "production_backup.db"
        valid_backup = self.db.create_safe_database_backup(self.backup_dir, backup_name=target_name)
        self.assertTrue(valid_backup.exists())

        conn_orig = sqlite3.connect(str(valid_backup))
        try:
            row = conn_orig.execute("SELECT name FROM products WHERE id = 'p_original'").fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "Original")
        finally:
            conn_orig.close()

        # 2. Add new data to DB
        self.db.insert_product(
            Product(id="p_new", name="New", url="https://shopee.co.id/new", price=200.0, source="manual")
        )

        # 3. Simulate failure during destination integrity check on second backup attempt with same target_name
        class FaultyIntegrityConnection(sqlite3.Connection):
            def execute(self, sql, *args, **kwargs):
                if "PRAGMA integrity_check" in sql:
                    return super().execute("SELECT 'corrupt database' as integrity_check")
                return super().execute(sql, *args, **kwargs)

        original_connect = sqlite3.connect

        def faulty_connect(database, *args, **kwargs):
            if ".tmp_" in str(database):
                kwargs["factory"] = FaultyIntegrityConnection
            return original_connect(database, *args, **kwargs)

        with patch("sqlite3.connect", side_effect=faulty_connect):
            with self.assertRaises(RuntimeError) as ctx:
                self.db.create_safe_database_backup(self.backup_dir, backup_name=target_name)
            self.assertIn("integrity check failed", str(ctx.exception).lower())

        # 4. Verify existing valid backup is completely uncorrupted and contains only original data
        conn_after = sqlite3.connect(str(valid_backup))
        try:
            integrity = conn_after.execute("PRAGMA integrity_check").fetchone()[0]
            self.assertEqual(str(integrity).lower(), "ok")

            rows = conn_after.execute("SELECT id FROM products").fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][0], "p_original")
        finally:
            conn_after.close()

        # 5. Verify no staging temp files were left behind in the backup directory
        tmp_files = list(self.backup_dir.glob("*.tmp_*"))
        self.assertEqual(len(tmp_files), 0, f"Lingering staging files found: {tmp_files}")


if __name__ == "__main__":
    unittest.main()
