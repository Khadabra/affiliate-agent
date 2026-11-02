"""SQLite database manager and repository with UNIQUE constraints and append-only event logging."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from affiliate_factory.models import (
    Claim,
    ComplianceFinding,
    ComplianceReport,
    ContentDraft,
    Event,
    PerformanceRecord,
    Product,
)

DEFAULT_DB_PATH = Path("data") / "affiliate_factory.db"


class Database:
    """SQLite database manager for affiliate factory."""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH) -> None:
        if isinstance(db_path, str) and db_path != ":memory:":
            self.db_path = Path(db_path)
        else:
            self.db_path = db_path

        if isinstance(self.db_path, Path):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn_str = str(self.db_path)
        else:
            self._conn_str = ":memory:"

        self._conn: sqlite3.Connection | None = None
        self.init_schema()

    def get_connection(self) -> sqlite3.Connection:
        if self._conn_str == ":memory:":
            if self._conn is None:
                self._conn = sqlite3.connect(":memory:")
                self._conn.row_factory = sqlite3.Row
            return self._conn

        conn = sqlite3.connect(self._conn_str)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        """Create all required tables with appropriate constraints."""
        conn = self.get_connection()
        try:
            with conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS products (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        url TEXT NOT NULL UNIQUE,
                        price REAL,
                        price_observed_at TEXT,
                        source TEXT NOT NULL,
                        notes TEXT
                    );

                    CREATE TABLE IF NOT EXISTS content_drafts (
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
                        PRIMARY KEY (id, prompt_version),
                        FOREIGN KEY (product_id) REFERENCES products (id)
                    );

                    CREATE TABLE IF NOT EXISTS claims (
                        id TEXT PRIMARY KEY,
                        draft_id TEXT NOT NULL,
                        text TEXT NOT NULL,
                        source_ref TEXT,
                        verification_status TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS compliance_reports (
                        draft_id TEXT PRIMARY KEY,
                        passed INTEGER NOT NULL,
                        findings_json TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS performance_records (
                        id TEXT PRIMARY KEY,
                        content_id TEXT NOT NULL,
                        platform TEXT NOT NULL,
                        observed_at TEXT NOT NULL,
                        views INTEGER,
                        clicks INTEGER,
                        orders INTEGER,
                        commission_idr REAL,
                        data_source TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS events (
                        id TEXT PRIMARY KEY,
                        ts TEXT NOT NULL,
                        run_id TEXT NOT NULL,
                        module TEXT NOT NULL,
                        action TEXT NOT NULL,
                        status TEXT NOT NULL,
                        ref_type TEXT NOT NULL,
                        ref_id TEXT NOT NULL,
                        note TEXT
                    );
                    """
                )
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    # --- Product Operations ---
    def insert_product(self, product: Product) -> bool:
        """Insert a product. Returns True if inserted, False if URL already exists."""
        conn = self.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO products (id, name, url, price, price_observed_at, source, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        product.id,
                        product.name,
                        product.url,
                        product.price,
                        product.price_observed_at.isoformat() if product.price_observed_at else None,
                        product.source,
                        product.notes,
                    ),
                )
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    def get_product_by_url(self, url: str) -> Product | None:
        conn = self.get_connection()
        try:
            cursor = conn.execute("SELECT * FROM products WHERE url = ?", (url,))
            row = cursor.fetchone()
            if not row:
                return None
            return Product(
                id=row["id"],
                name=row["name"],
                url=row["url"],
                price=row["price"],
                price_observed_at=datetime.fromisoformat(row["price_observed_at"]) if row["price_observed_at"] else None,
                source=row["source"],
                notes=row["notes"],
            )
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    def get_product(self, product_id: str) -> Product | None:
        conn = self.get_connection()
        try:
            cursor = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return Product(
                id=row["id"],
                name=row["name"],
                url=row["url"],
                price=row["price"],
                price_observed_at=datetime.fromisoformat(row["price_observed_at"]) if row["price_observed_at"] else None,
                source=row["source"],
                notes=row["notes"],
            )
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    # --- ContentDraft Operations ---
    def upsert_draft(self, draft: ContentDraft) -> bool:
        """Insert or update a draft for a given (id, prompt_version)."""
        conn = self.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO content_drafts (
                        id, product_id, angle, hook, script, caption, cta,
                        disclosure_text, status, prompt_version, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id, prompt_version) DO UPDATE SET
                        angle=excluded.angle,
                        hook=excluded.hook,
                        script=excluded.script,
                        caption=excluded.caption,
                        cta=excluded.cta,
                        disclosure_text=excluded.disclosure_text,
                        status=excluded.status
                    """,
                    (
                        draft.id,
                        draft.product_id,
                        draft.angle,
                        draft.hook,
                        draft.script,
                        draft.caption,
                        draft.cta,
                        draft.disclosure_text,
                        draft.status,
                        draft.prompt_version,
                        draft.created_at.isoformat(),
                    ),
                )
            return True
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    def update_draft_status(self, draft_id: str, prompt_version: str, status: str) -> None:
        conn = self.get_connection()
        try:
            with conn:
                conn.execute(
                    "UPDATE content_drafts SET status = ? WHERE id = ? AND prompt_version = ?",
                    (status, draft_id, prompt_version),
                )
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    def get_draft(self, draft_id: str, prompt_version: str) -> ContentDraft | None:
        conn = self.get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM content_drafts WHERE id = ? AND prompt_version = ?",
                (draft_id, prompt_version),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return ContentDraft(
                id=row["id"],
                product_id=row["product_id"],
                angle=row["angle"],
                hook=row["hook"],
                script=row["script"],
                caption=row["caption"],
                cta=row["cta"],
                disclosure_text=row["disclosure_text"],
                status=row["status"],
                prompt_version=row["prompt_version"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    # --- Compliance Operations ---
    def save_compliance_report(self, report: ComplianceReport) -> None:
        conn = self.get_connection()
        try:
            findings_data = [f.model_dump() for f in report.findings]
            with conn:
                conn.execute(
                    """
                    INSERT INTO compliance_reports (draft_id, passed, findings_json)
                    VALUES (?, ?, ?)
                    ON CONFLICT(draft_id) DO UPDATE SET
                        passed=excluded.passed,
                        findings_json=excluded.findings_json
                    """,
                    (report.draft_id, 1 if report.passed else 0, json.dumps(findings_data)),
                )
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    def get_compliance_report(self, draft_id: str) -> ComplianceReport | None:
        conn = self.get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM compliance_reports WHERE draft_id = ?",
                (draft_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            findings_list = json.loads(row["findings_json"])
            return ComplianceReport(
                draft_id=row["draft_id"],
                passed=bool(row["passed"]),
                findings=[ComplianceFinding(**f) for f in findings_list],
            )
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    # --- Claims Operations ---
    def save_claims(self, claims: list[Claim]) -> None:
        conn = self.get_connection()
        try:
            with conn:
                for c in claims:
                    conn.execute(
                        """
                        INSERT INTO claims (id, draft_id, text, source_ref, verification_status)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            source_ref=excluded.source_ref,
                            verification_status=excluded.verification_status
                        """,
                        (c.id, c.draft_id, c.text, c.source_ref, c.verification_status),
                    )
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    def get_claims_for_draft(self, draft_id: str) -> list[Claim]:
        conn = self.get_connection()
        try:
            cursor = conn.execute("SELECT * FROM claims WHERE draft_id = ?", (draft_id,))
            rows = cursor.fetchall()
            return [
                Claim(
                    id=row["id"],
                    draft_id=row["draft_id"],
                    text=row["text"],
                    source_ref=row["source_ref"],
                    verification_status=row["verification_status"],
                )
                for row in rows
            ]
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    # --- Performance Records ---
    def save_performance_record(self, record_id: str, record: PerformanceRecord) -> None:
        conn = self.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO performance_records (
                        id, content_id, platform, observed_at, views, clicks, orders, commission_idr, data_source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        views=excluded.views,
                        clicks=excluded.clicks,
                        orders=excluded.orders,
                        commission_idr=excluded.commission_idr
                    """,
                    (
                        record_id,
                        record.content_id,
                        record.platform,
                        record.observed_at.isoformat(),
                        record.views,
                        record.clicks,
                        record.orders,
                        record.commission_idr,
                        record.data_source,
                    ),
                )
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    def get_performance_record(self, record_id: str) -> PerformanceRecord | None:
        conn = self.get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM performance_records WHERE id = ?",
                (record_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return PerformanceRecord(
                content_id=row["content_id"],
                platform=row["platform"],
                observed_at=datetime.fromisoformat(row["observed_at"]),
                views=row["views"],
                clicks=row["clicks"],
                orders=row["orders"],
                commission_idr=row["commission_idr"],
                data_source=row["data_source"],
            )
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    # --- Event Log Operations (Append-Only) ---
    def append_event(self, event: Event) -> None:
        conn = self.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO events (id, ts, run_id, module, action, status, ref_type, ref_id, note)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.id,
                        event.ts.isoformat(),
                        event.run_id,
                        event.module,
                        event.action,
                        event.status,
                        event.ref_type,
                        event.ref_id,
                        event.note,
                    ),
                )
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    def list_events(self, run_id: str | None = None) -> list[Event]:
        conn = self.get_connection()
        try:
            if run_id:
                cursor = conn.execute("SELECT * FROM events WHERE run_id = ? ORDER BY ts ASC", (run_id,))
            else:
                cursor = conn.execute("SELECT * FROM events ORDER BY ts ASC")
            rows = cursor.fetchall()
            return [
                Event(
                    id=row["id"],
                    ts=datetime.fromisoformat(row["ts"]),
                    run_id=row["run_id"],
                    module=row["module"],
                    action=row["action"],
                    status=row["status"],
                    ref_type=row["ref_type"],
                    ref_id=row["ref_id"],
                    note=row["note"],
                )
                for row in rows
            ]
        finally:
            if self._conn_str != ":memory:":
                conn.close()

