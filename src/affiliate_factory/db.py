"""SQLite database manager and repository with UNIQUE constraints and append-only event logging."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from affiliate_factory.models import (
    Claim,
    ComplianceFinding,
    ComplianceReport,
    ContentDraft,
    Event,
    PerformanceCorrectionPayload,
    PerformanceRecord,
    PerformanceSnapshotState,
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
                # Check for legacy compliance_reports schema without prompt_version
                table_check = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='compliance_reports'"
                ).fetchone()
                if table_check:
                    cols = {
                        row["name"]
                        for row in conn.execute("PRAGMA table_info(compliance_reports)").fetchall()
                    }
                    if "prompt_version" not in cols:
                        conn.executescript(
                            """
                            CREATE TABLE compliance_reports_v2 (
                                draft_id TEXT NOT NULL,
                                prompt_version TEXT NOT NULL DEFAULT 'v1.0',
                                passed INTEGER NOT NULL,
                                findings_json TEXT NOT NULL,
                                PRIMARY KEY (draft_id, prompt_version)
                            );
                            INSERT INTO compliance_reports_v2 (draft_id, prompt_version, passed, findings_json)
                            SELECT draft_id, 'v1.0', passed, findings_json FROM compliance_reports;
                            DROP TABLE compliance_reports;
                            ALTER TABLE compliance_reports_v2 RENAME TO compliance_reports;
                            """
                        )

                # Check for legacy claims schema without prompt_version
                table_check_claims = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='claims'"
                ).fetchone()
                if table_check_claims:
                    claim_cols = {
                        row["name"]
                        for row in conn.execute("PRAGMA table_info(claims)").fetchall()
                    }
                    if "prompt_version" not in claim_cols:
                        conn.execute("ALTER TABLE claims ADD COLUMN prompt_version TEXT")
                        # Migrate existing claims:
                        # If prompt_version can be unambiguously established (exactly 1 distinct version
                        # in content_drafts for that draft_id), associate it.
                        # If 0 or >1 versions (ambiguous), leave as NULL (do NOT fabricate).
                        draft_ids = [
                            row["draft_id"]
                            for row in conn.execute("SELECT DISTINCT draft_id FROM claims").fetchall()
                        ]
                        for d_id in draft_ids:
                            pv_rows = conn.execute(
                                "SELECT DISTINCT prompt_version FROM content_drafts WHERE id = ?",
                                (d_id,),
                            ).fetchall()
                            if len(pv_rows) == 1:
                                single_pv = pv_rows[0]["prompt_version"]
                                conn.execute(
                                    "UPDATE claims SET prompt_version = ? WHERE draft_id = ? AND prompt_version IS NULL",
                                    (single_pv, d_id),
                                )

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
                        prompt_version TEXT,
                        text TEXT NOT NULL,
                        source_ref TEXT,
                        verification_status TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_claims_draft_version ON claims (draft_id, prompt_version);

                    CREATE TABLE IF NOT EXISTS compliance_reports (
                        draft_id TEXT NOT NULL,
                        prompt_version TEXT NOT NULL DEFAULT 'v1.0',
                        passed INTEGER NOT NULL,
                        findings_json TEXT NOT NULL,
                        PRIMARY KEY (draft_id, prompt_version)
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
                    CREATE INDEX IF NOT EXISTS idx_perf_content_platform ON performance_records (content_id, platform, observed_at);

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
                    INSERT INTO compliance_reports (draft_id, prompt_version, passed, findings_json)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(draft_id, prompt_version) DO UPDATE SET
                        passed=excluded.passed,
                        findings_json=excluded.findings_json
                    """,
                    (report.draft_id, report.prompt_version, 1 if report.passed else 0, json.dumps(findings_data)),
                )
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    def get_compliance_report(self, draft_id: str, prompt_version: str | None = None) -> ComplianceReport | None:
        conn = self.get_connection()
        try:
            if prompt_version is not None:
                cursor = conn.execute(
                    "SELECT * FROM compliance_reports WHERE draft_id = ? AND prompt_version = ?",
                    (draft_id, prompt_version),
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM compliance_reports WHERE draft_id = ? ORDER BY prompt_version DESC LIMIT 1",
                    (draft_id,),
                )
            row = cursor.fetchone()
            if not row:
                return None
            findings_list = json.loads(row["findings_json"])
            ver = row["prompt_version"] if "prompt_version" in row.keys() else "v1.0"
            return ComplianceReport(
                draft_id=row["draft_id"],
                prompt_version=ver,
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
                    pv = c.prompt_version
                    if pv is None:
                        # Check if there is exactly 1 distinct prompt_version for this draft in content_drafts
                        pv_rows = conn.execute(
                            "SELECT DISTINCT prompt_version FROM content_drafts WHERE id = ?",
                            (c.draft_id,),
                        ).fetchall()
                        if len(pv_rows) == 1:
                            pv = pv_rows[0]["prompt_version"]

                    conn.execute(
                        """
                        INSERT INTO claims (id, draft_id, prompt_version, text, source_ref, verification_status)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            draft_id=excluded.draft_id,
                            prompt_version=excluded.prompt_version,
                            text=excluded.text,
                            source_ref=excluded.source_ref,
                            verification_status=excluded.verification_status
                        """,
                        (c.id, c.draft_id, pv, c.text, c.source_ref, c.verification_status),
                    )
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    def get_claim(self, claim_id: str) -> Claim | None:
        conn = self.get_connection()
        try:
            cursor = conn.execute("SELECT * FROM claims WHERE id = ?", (claim_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return Claim(
                id=row["id"],
                draft_id=row["draft_id"],
                prompt_version=row["prompt_version"] if "prompt_version" in row.keys() else None,
                text=row["text"],
                source_ref=row["source_ref"],
                verification_status=row["verification_status"],
            )
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    def update_claim_status(self, claim_id: str, verification_status: str) -> bool:
        """Update verification status of an existing claim. Returns True if updated, False if not found."""
        conn = self.get_connection()
        try:
            with conn:
                cursor = conn.execute(
                    "UPDATE claims SET verification_status = ? WHERE id = ?",
                    (verification_status, claim_id),
                )
                return cursor.rowcount > 0
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    def get_claims_for_draft(self, draft_id: str, prompt_version: str | None = None) -> list[Claim]:
        conn = self.get_connection()
        try:
            if prompt_version is not None:
                cursor = conn.execute(
                    "SELECT * FROM claims WHERE draft_id = ? AND prompt_version = ? ORDER BY id ASC",
                    (draft_id, prompt_version),
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM claims WHERE draft_id = ? ORDER BY id ASC",
                    (draft_id,),
                )
            rows = cursor.fetchall()
            return [
                Claim(
                    id=row["id"],
                    draft_id=row["draft_id"],
                    prompt_version=row["prompt_version"] if "prompt_version" in row.keys() else None,
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
    def save_performance_record(
        self,
        record_id: str | PerformanceRecord,
        record: PerformanceRecord | None = None,
        allow_overwrite: bool = False,
    ) -> str:
        """Save a performance record snapshot.

        Invariants:
        - By default (allow_overwrite=False), duplicate snapshot IDs are strictly
          rejected with ValueError to protect historical snapshot immutability.
        - If allow_overwrite=True, explicitly updates an existing snapshot.
        """
        import uuid
        if isinstance(record_id, PerformanceRecord):
            rec = record_id
            rec_id = rec.id or str(uuid.uuid4())
        else:
            rec = record
            if rec is None:
                raise ValueError("PerformanceRecord instance is required.")
            rec_id = record_id or rec.id or str(uuid.uuid4())

        rec.id = rec_id
        conn = self.get_connection()
        try:
            with conn:
                if not allow_overwrite:
                    try:
                        conn.execute(
                            """
                            INSERT INTO performance_records (
                                id, content_id, platform, observed_at, views, clicks, orders, commission_idr, data_source
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                rec_id,
                                rec.content_id,
                                rec.platform,
                                rec.observed_at.isoformat(),
                                rec.views,
                                rec.clicks,
                                rec.orders,
                                rec.commission_idr,
                                rec.data_source,
                            ),
                        )
                    except sqlite3.IntegrityError as e:
                        raise ValueError(
                            f"Snapshot performa dengan ID '{rec_id}' sudah ada di database. "
                            f"Snapshot historis tidak boleh ditimpa secara tidak sengaja."
                        ) from e
                else:
                    conn.execute(
                        """
                        INSERT INTO performance_records (
                            id, content_id, platform, observed_at, views, clicks, orders, commission_idr, data_source
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            content_id=excluded.content_id,
                            platform=excluded.platform,
                            observed_at=excluded.observed_at,
                            views=excluded.views,
                            clicks=excluded.clicks,
                            orders=excluded.orders,
                            commission_idr=excluded.commission_idr,
                            data_source=excluded.data_source
                        """,
                        (
                            rec_id,
                            rec.content_id,
                            rec.platform,
                            rec.observed_at.isoformat(),
                            rec.views,
                            rec.clicks,
                            rec.orders,
                            rec.commission_idr,
                            rec.data_source,
                        ),
                    )
            return rec_id
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
                id=row["id"],
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

    def list_performance_records(
        self,
        content_id: str | None = None,
        platform: str | None = None,
        start_date: datetime | str | None = None,
        end_date: datetime | str | None = None,
    ) -> list[PerformanceRecord]:
        """List performance record snapshots filtered by content, platform, or date range.

        Returns snapshots sorted chronologically with deterministic tie-breaking (observed_at ASC, id ASC).
        """
        conn = self.get_connection()
        try:
            query = "SELECT * FROM performance_records WHERE 1=1"
            params: list[Any] = []
            if content_id:
                query += " AND content_id = ?"
                params.append(content_id)
            if platform:
                query += " AND platform = ?"
                params.append(platform)
            if start_date:
                if isinstance(start_date, datetime):
                    dt_start = start_date if start_date.tzinfo else start_date.replace(tzinfo=timezone.utc)
                    start_iso = dt_start.astimezone(timezone.utc).isoformat()
                else:
                    try:
                        parsed = datetime.fromisoformat(str(start_date).strip())
                        dt_start = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
                        start_iso = dt_start.astimezone(timezone.utc).isoformat()
                    except Exception:
                        start_iso = str(start_date)
                query += " AND observed_at >= ?"
                params.append(start_iso)
            if end_date:
                if isinstance(end_date, datetime):
                    dt_end = end_date if end_date.tzinfo else end_date.replace(tzinfo=timezone.utc)
                    end_iso = dt_end.astimezone(timezone.utc).isoformat()
                else:
                    try:
                        parsed = datetime.fromisoformat(str(end_date).strip())
                        dt_end = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
                        end_iso = dt_end.astimezone(timezone.utc).isoformat()
                    except Exception:
                        end_iso = str(end_date)
                query += " AND observed_at <= ?"
                params.append(end_iso)

            query += " ORDER BY observed_at ASC, id ASC"
            cursor = conn.execute(query, tuple(params))
            rows = cursor.fetchall()
            return [
                PerformanceRecord(
                    id=row["id"],
                    content_id=row["content_id"],
                    platform=row["platform"],
                    observed_at=datetime.fromisoformat(row["observed_at"]),
                    views=row["views"],
                    clicks=row["clicks"],
                    orders=row["orders"],
                    commission_idr=row["commission_idr"],
                    data_source=row["data_source"],
                )
                for row in rows
            ]
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    def correct_performance_record(
        self,
        record_id: str,
        updated_record: PerformanceRecord,
        reason: str | None = None,
        run_id: str | None = None,
    ) -> Event:
        """Atomically correct an existing performance snapshot and record an audit event.

        Invariants:
        1. Snapshot update and audit log insertion occur within the exact same SQLite transaction.
        2. Full representations of before and after states are saved in the audit event.
        3. If snapshot does not exist, raises ValueError without creating an audit event.
        4. If audit event creation or insertion fails, the entire transaction rolls back.
        """
        conn = self.get_connection()
        try:
            with conn:
                cursor = conn.execute(
                    "SELECT * FROM performance_records WHERE id = ?",
                    (record_id,),
                )
                row = cursor.fetchone()
                if not row:
                    raise ValueError(
                        f"Snapshot performa dengan ID '{record_id}' tidak ditemukan di database."
                    )

                before_state = PerformanceSnapshotState(
                    id=row["id"],
                    content_id=row["content_id"],
                    platform=row["platform"],
                    observed_at=row["observed_at"],
                    views=row["views"],
                    clicks=row["clicks"],
                    orders=row["orders"],
                    commission_idr=row["commission_idr"],
                    data_source=row["data_source"],
                )

                after_state = PerformanceSnapshotState(
                    id=updated_record.id or record_id,
                    content_id=updated_record.content_id,
                    platform=updated_record.platform,
                    observed_at=updated_record.observed_at.isoformat(),
                    views=updated_record.views,
                    clicks=updated_record.clicks,
                    orders=updated_record.orders,
                    commission_idr=updated_record.commission_idr,
                    data_source=updated_record.data_source,
                )

                conn.execute(
                    """
                    UPDATE performance_records SET
                        content_id = ?,
                        platform = ?,
                        observed_at = ?,
                        views = ?,
                        clicks = ?,
                        orders = ?,
                        commission_idr = ?,
                        data_source = ?
                    WHERE id = ?
                    """,
                    (
                        after_state.content_id,
                        after_state.platform,
                        after_state.observed_at,
                        after_state.views,
                        after_state.clicks,
                        after_state.orders,
                        after_state.commission_idr,
                        after_state.data_source,
                        record_id,
                    ),
                )

                payload = PerformanceCorrectionPayload(
                    record_id=record_id,
                    reason=(reason or "").strip(),
                    before=before_state,
                    after=after_state,
                )

                event = Event(
                    id=str(uuid.uuid4()),
                    ts=datetime.now(timezone.utc),
                    run_id=run_id or str(uuid.uuid4()),
                    module="performance",
                    action="correct_snapshot",
                    status="succeeded",
                    ref_type="performance_record",
                    ref_id=record_id,
                    note=payload.model_dump_json(),
                )

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
                return event
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    def list_correction_events(self, record_id: str | None = None) -> list[Event]:
        """List correction audit events, optionally filtered by snapshot record_id."""
        conn = self.get_connection()
        try:
            if record_id:
                cursor = conn.execute(
                    """
                    SELECT * FROM events
                    WHERE module = 'performance' AND action = 'correct_snapshot' AND ref_id = ?
                    ORDER BY ts ASC
                    """,
                    (record_id,),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT * FROM events
                    WHERE module = 'performance' AND action = 'correct_snapshot'
                    ORDER BY ts ASC
                    """
                )
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

    @staticmethod
    def parse_correction_payload(event: Event) -> PerformanceCorrectionPayload:
        """Parse structured correction payload from an audit event."""
        if not event.note:
            raise ValueError(f"Event '{event.id}' has empty note")
        return PerformanceCorrectionPayload.model_validate_json(event.note)

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

