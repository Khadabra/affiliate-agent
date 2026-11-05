"""Tests for Phase 3.5.1 SQLite Hardening (WAL, busy_timeout, foreign_keys, concurrency)."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
import threading

from affiliate_factory.db import Database
from affiliate_factory.models import Product


class TestDatabaseHardening(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_hardened.db"
        self.db = Database(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_wal_mode_enabled_on_file_database(self) -> None:
        """Verify journal_mode is WAL on a disk-backed database."""
        mode = self.db.get_journal_mode()
        self.assertEqual(mode, "wal", f"Expected 'wal', got '{mode}'")

    def test_foreign_keys_enabled(self) -> None:
        """Verify PRAGMA foreign_keys = ON is active."""
        fk_status = self.db.get_foreign_keys_status()
        self.assertTrue(fk_status, "PRAGMA foreign_keys must be True (1)")

    def test_busy_timeout_configured(self) -> None:
        """Verify PRAGMA busy_timeout is 5000ms."""
        timeout = self.db.get_busy_timeout()
        self.assertEqual(timeout, 5000, f"Expected busy_timeout=5000, got {timeout}")

    def test_new_connections_consistently_configured(self) -> None:
        """Verify every fresh connection gets foreign_keys=1 and busy_timeout=5000."""
        conn1 = self.db.get_connection()
        conn2 = self.db.get_connection()
        try:
            fk1 = conn1.execute("PRAGMA foreign_keys").fetchone()[0]
            bt1 = conn1.execute("PRAGMA busy_timeout").fetchone()[0]
            fk2 = conn2.execute("PRAGMA foreign_keys").fetchone()[0]
            bt2 = conn2.execute("PRAGMA busy_timeout").fetchone()[0]

            self.assertEqual(fk1, 1)
            self.assertEqual(bt1, 5000)
            self.assertEqual(fk2, 1)
            self.assertEqual(bt2, 5000)
        finally:
            conn1.close()
            conn2.close()

    def test_transaction_rollback_integrity(self) -> None:
        """Verify that a failed transaction rolls back cleanly without partial writes."""
        conn = self.db.get_connection()
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                with conn:
                    conn.execute(
                        "INSERT INTO products (id, name, url, price, source) VALUES (?, ?, ?, ?, ?)",
                        ("p1", "Product 1", "https://example.com/p1", 1000.0, "manual"),
                    )
                    # This duplicate insert violates PRIMARY KEY constraint on 'id'
                    conn.execute(
                        "INSERT INTO products (id, name, url, price, source) VALUES (?, ?, ?, ?, ?)",
                        ("p1", "Duplicate ID", "https://example.com/p2", 2000.0, "manual"),
                    )
        finally:
            conn.close()

        # Confirm rollback: p1 must NOT exist
        p = self.db.get_product("p1")
        self.assertIsNone(p, "Transaction failure should have rolled back completely")

    def test_concurrent_read_write_under_wal(self) -> None:
        """Verify that readers do not block writers and writers do not block readers under WAL."""
        writer_errors: list[Exception] = []
        reader_errors: list[Exception] = []
        read_counts: list[int] = []

        def writer_thread():
            try:
                for i in range(10):
                    prod = Product(
                        id=f"prod_thread_{i}",
                        name=f"Thread Product {i}",
                        url=f"https://example.com/item/{i}",
                        price=50000.0 + i,
                        source="manual",
                    )
                    self.db.insert_product(prod)
            except Exception as e:
                writer_errors.append(e)

        def reader_thread():
            try:
                for _ in range(20):
                    conn = self.db.get_connection()
                    try:
                        count = conn.execute("SELECT count(*) FROM products").fetchone()[0]
                        read_counts.append(count)
                    finally:
                        conn.close()
            except Exception as e:
                reader_errors.append(e)

        t1 = threading.Thread(target=writer_thread)
        t2 = threading.Thread(target=reader_thread)
        t3 = threading.Thread(target=reader_thread)

        t1.start()
        t2.start()
        t3.start()

        t1.join(timeout=10)
        t2.join(timeout=10)
        t3.join(timeout=10)

        self.assertEqual(len(writer_errors), 0, f"Writer errors: {writer_errors}")
        self.assertEqual(len(reader_errors), 0, f"Reader errors: {reader_errors}")
        self.assertGreater(len(read_counts), 0, "Readers should have executed queries successfully")

    def test_in_memory_database_fallback(self) -> None:
        """Verify in-memory database behaves properly with foreign_keys and busy_timeout."""
        mem_db = Database(":memory:")
        self.assertTrue(mem_db.get_foreign_keys_status())
        self.assertEqual(mem_db.get_busy_timeout(), 5000)
        # in-memory journal mode is typically 'memory'
        mode = mem_db.get_journal_mode()
        self.assertIn(mode, ("memory", "wal"))


if __name__ == "__main__":
    unittest.main()
