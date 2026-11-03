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
from affiliate_factory.agent_contracts import (
    AgentError,
    AgentEvent,
    AgentResult,
    AgentTask,
    TaskStatus,
    ALLOWED_TASK_TRANSITIONS,
)
from affiliate_factory.workflow_contracts import (
    WorkflowDefinition,
    WorkflowEvent,
    WorkflowExecutionRecord,
    WorkflowExecutionRequest,
    WorkflowStepResult,
    WorkflowStepStatus,
    WorkflowStatus,
    ALLOWED_WORKFLOW_TRANSITIONS,
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
                self._conn.execute("PRAGMA foreign_keys = ON")
            return self._conn

        conn = sqlite3.connect(self._conn_str)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
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

                workflow_table_check = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='workflow_executions'"
                ).fetchone()
                if workflow_table_check:
                    workflow_cols = {
                        row["name"]
                        for row in conn.execute("PRAGMA table_info(workflow_executions)").fetchall()
                    }
                    if "workflow_json" not in workflow_cols:
                        conn.execute(
                            "ALTER TABLE workflow_executions ADD COLUMN workflow_json TEXT NOT NULL DEFAULT '{}'"
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

                     CREATE TABLE IF NOT EXISTS agent_tasks (
                         task_id TEXT PRIMARY KEY,
                         agent_id TEXT NOT NULL,
                         status TEXT NOT NULL,
                         input_json TEXT NOT NULL,
                         context_json TEXT NOT NULL,
                         created_at TEXT NOT NULL,
                         correlation_id TEXT NOT NULL,
                         parent_task_id TEXT,
                         started_at TEXT,
                         completed_at TEXT,
                         output_json TEXT NOT NULL DEFAULT '{}',
                         error_json TEXT,
                         execution_metadata_json TEXT NOT NULL DEFAULT '{}'
                     );

                     CREATE INDEX IF NOT EXISTS idx_agent_tasks_correlation
                         ON agent_tasks (correlation_id);

                     CREATE TABLE IF NOT EXISTS agent_events (
                         sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                         event_id TEXT NOT NULL UNIQUE,
                         task_id TEXT NOT NULL,
                         agent_id TEXT NOT NULL,
                         event_type TEXT NOT NULL,
                         timestamp TEXT NOT NULL,
                         payload_json TEXT NOT NULL,
                         correlation_id TEXT NOT NULL,
                         FOREIGN KEY (task_id) REFERENCES agent_tasks (task_id)
                     );

                     CREATE INDEX IF NOT EXISTS idx_agent_events_task
                         ON agent_events (task_id, sequence);

                     CREATE TABLE IF NOT EXISTS workflow_executions (
                         execution_id TEXT PRIMARY KEY,
                         workflow_id TEXT NOT NULL,
                         workflow_version TEXT NOT NULL,
                         status TEXT NOT NULL,
                         input_json TEXT NOT NULL,
                         output_json TEXT NOT NULL DEFAULT '{}',
                         error_type TEXT,
                         error_message TEXT,
                         correlation_id TEXT NOT NULL,
                         parent_execution_id TEXT,
                         current_step_id TEXT,
                         workflow_json TEXT NOT NULL DEFAULT '{}',
                         created_at TEXT NOT NULL,
                         updated_at TEXT NOT NULL
                     );

                     CREATE INDEX IF NOT EXISTS idx_workflow_executions_correlation
                         ON workflow_executions (correlation_id);

                     CREATE TABLE IF NOT EXISTS workflow_steps (
                         execution_id TEXT NOT NULL,
                         step_id TEXT NOT NULL,
                         status TEXT NOT NULL,
                         task_id TEXT,
                         attempts INTEGER NOT NULL DEFAULT 0,
                         output_json TEXT NOT NULL DEFAULT '{}',
                         error_type TEXT,
                         error_message TEXT,
                         updated_at TEXT NOT NULL,
                         PRIMARY KEY (execution_id, step_id),
                         FOREIGN KEY (execution_id) REFERENCES workflow_executions (execution_id)
                     );

                     CREATE TABLE IF NOT EXISTS workflow_events (
                         sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                         event_id TEXT NOT NULL UNIQUE,
                         execution_id TEXT NOT NULL,
                         workflow_id TEXT NOT NULL,
                         step_id TEXT,
                         task_id TEXT,
                         event_type TEXT NOT NULL,
                         timestamp TEXT NOT NULL,
                         payload_json TEXT NOT NULL,
                         correlation_id TEXT NOT NULL,
                         FOREIGN KEY (execution_id) REFERENCES workflow_executions (execution_id)
                     );

                     CREATE INDEX IF NOT EXISTS idx_workflow_events_execution
                         ON workflow_events (execution_id, sequence);
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

    def get_drafts_by_id(self, draft_id: str) -> list[ContentDraft]:
        """Retrieve all prompt versions of a draft by its ID."""
        conn = self.get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM content_drafts WHERE id = ? ORDER BY prompt_version ASC",
                (draft_id,),
            )
            rows = cursor.fetchall()
            return [
                ContentDraft(
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
                for row in rows
            ]
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    def list_all_drafts(self) -> list[ContentDraft]:
        """List all drafts in the database across all versions."""
        conn = self.get_connection()
        try:
            cursor = conn.execute("SELECT * FROM content_drafts ORDER BY id ASC, prompt_version ASC")
            rows = cursor.fetchall()
            return [
                ContentDraft(
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
                for row in rows
            ]
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

    # --- Agent Foundation Persistence ---
    def save_agent_task(self, task: AgentTask) -> None:
        """Insert a new agent task; duplicate IDs fail instead of overwriting."""
        conn = self.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO agent_tasks (
                        task_id, agent_id, status, input_json, context_json, created_at,
                        correlation_id, parent_task_id, started_at, completed_at,
                        output_json, error_json, execution_metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task.task_id,
                        task.agent_id,
                        task.status.value,
                        json.dumps(task.input_data, ensure_ascii=False, default=str),
                        json.dumps(task.context, ensure_ascii=False, default=str),
                        task.created_at.isoformat(),
                        task.correlation_id,
                        task.parent_task_id,
                        task.started_at.isoformat() if task.started_at else None,
                        task.completed_at.isoformat() if task.completed_at else None,
                        "{}",
                        None,
                        "{}",
                    ),
                )
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    def update_agent_task(self, task: AgentTask, result: AgentResult | None = None) -> None:
        """Persist lifecycle state and, when available, the terminal result."""
        conn = self.get_connection()
        try:
            output_json = json.dumps(result.output_data, ensure_ascii=False, default=str) if result else "{}"
            error_json = result.error.model_dump_json() if result and result.error else None
            metadata_json = (
                json.dumps(result.execution_metadata, ensure_ascii=False, default=str) if result else "{}"
            )
            with conn:
                current_row = conn.execute(
                    "SELECT status FROM agent_tasks WHERE task_id = ?", (task.task_id,)
                ).fetchone()
                if current_row is None:
                    raise KeyError(f"Unknown agent task ID: '{task.task_id}'")
                current_status = TaskStatus(current_row["status"])
                if task.status != current_status and task.status not in ALLOWED_TASK_TRANSITIONS[current_status]:
                    raise ValueError(
                        f"Invalid persisted task transition: {current_status.value} -> {task.status.value}"
                    )
                cursor = conn.execute(
                    """
                    UPDATE agent_tasks SET
                        status = ?, started_at = ?, completed_at = ?,
                        output_json = ?, error_json = ?, execution_metadata_json = ?
                    WHERE task_id = ?
                    """,
                    (
                        task.status.value,
                        task.started_at.isoformat() if task.started_at else None,
                        task.completed_at.isoformat() if task.completed_at else None,
                        output_json,
                        error_json,
                        metadata_json,
                        task.task_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise KeyError(f"Unknown agent task ID: '{task.task_id}'")
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    def save_agent_task_with_event(self, task: AgentTask, event: AgentEvent) -> None:
        """Atomically create an agent task and its first event."""
        conn = self.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO agent_tasks (
                        task_id, agent_id, status, input_json, context_json, created_at,
                        correlation_id, parent_task_id, started_at, completed_at,
                        output_json, error_json, execution_metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', NULL, '{}')
                    """,
                    (
                        task.task_id,
                        task.agent_id,
                        task.status.value,
                        json.dumps(task.input_data, ensure_ascii=False, default=str),
                        json.dumps(task.context, ensure_ascii=False, default=str),
                        task.created_at.isoformat(),
                        task.correlation_id,
                        task.parent_task_id,
                        task.started_at.isoformat() if task.started_at else None,
                        task.completed_at.isoformat() if task.completed_at else None,
                    ),
                )
                self._insert_agent_event(conn, event)
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    def update_agent_task_with_event(
        self,
        task: AgentTask,
        result: AgentResult | None,
        event: AgentEvent,
    ) -> None:
        """Atomically update an agent task and append its lifecycle event."""
        conn = self.get_connection()
        try:
            output_json = json.dumps(result.output_data, ensure_ascii=False, default=str) if result else "{}"
            error_json = result.error.model_dump_json() if result and result.error else None
            metadata_json = (
                json.dumps(result.execution_metadata, ensure_ascii=False, default=str) if result else "{}"
            )
            with conn:
                current_row = conn.execute(
                    "SELECT status FROM agent_tasks WHERE task_id = ?", (task.task_id,)
                ).fetchone()
                if current_row is None:
                    raise KeyError(f"Unknown agent task ID: '{task.task_id}'")
                current_status = TaskStatus(current_row["status"])
                if task.status != current_status and task.status not in ALLOWED_TASK_TRANSITIONS[current_status]:
                    raise ValueError(
                        f"Invalid persisted task transition: {current_status.value} -> {task.status.value}"
                    )
                cursor = conn.execute(
                    """
                    UPDATE agent_tasks SET
                        status = ?, started_at = ?, completed_at = ?,
                        output_json = ?, error_json = ?, execution_metadata_json = ?
                    WHERE task_id = ?
                    """,
                    (
                        task.status.value,
                        task.started_at.isoformat() if task.started_at else None,
                        task.completed_at.isoformat() if task.completed_at else None,
                        output_json,
                        error_json,
                        metadata_json,
                        task.task_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise KeyError(f"Unknown agent task ID: '{task.task_id}'")
                self._insert_agent_event(conn, event)
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    @staticmethod
    def _insert_agent_event(conn: sqlite3.Connection, event: AgentEvent) -> None:
        conn.execute(
            """
            INSERT INTO agent_events (
                event_id, task_id, agent_id, event_type, timestamp,
                payload_json, correlation_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.task_id,
                event.agent_id,
                event.event_type,
                event.timestamp.isoformat(),
                json.dumps(event.payload, ensure_ascii=False, default=str),
                event.correlation_id,
            ),
        )

    def get_agent_task(self, task_id: str) -> AgentTask | None:
        """Load one persisted task, or ``None`` when it does not exist."""
        conn = self.get_connection()
        try:
            row = conn.execute("SELECT * FROM agent_tasks WHERE task_id = ?", (task_id,)).fetchone()
            if row is None:
                return None
            return AgentTask(
                task_id=row["task_id"],
                agent_id=row["agent_id"],
                status=row["status"],
                input_data=json.loads(row["input_json"]),
                context=json.loads(row["context_json"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                correlation_id=row["correlation_id"],
                parent_task_id=row["parent_task_id"],
                started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
                completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            )
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    def get_agent_result(self, task_id: str) -> AgentResult | None:
        """Load a persisted terminal result, including output and error data."""
        conn = self.get_connection()
        try:
            row = conn.execute("SELECT * FROM agent_tasks WHERE task_id = ?", (task_id,)).fetchone()
            if row is None or row["status"] not in {TaskStatus.COMPLETED.value, TaskStatus.FAILED.value}:
                return None
            return AgentResult(
                task_id=row["task_id"],
                agent_id=row["agent_id"],
                status=row["status"],
                output_data=json.loads(row["output_json"]),
                error=AgentError.model_validate_json(row["error_json"]) if row["error_json"] else None,
                started_at=datetime.fromisoformat(row["started_at"]),
                completed_at=datetime.fromisoformat(row["completed_at"]),
                execution_metadata=json.loads(row["execution_metadata_json"]),
            )
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    def append_agent_event(self, event: AgentEvent) -> None:
        """Append one agent event; FK enforcement prevents orphan events."""
        conn = self.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO agent_events (
                        event_id, task_id, agent_id, event_type, timestamp,
                        payload_json, correlation_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.task_id,
                        event.agent_id,
                        event.event_type,
                        event.timestamp.isoformat(),
                        json.dumps(event.payload, ensure_ascii=False, default=str),
                        event.correlation_id,
                    ),
                )
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    def list_agent_events(self, task_id: str | None = None) -> list[AgentEvent]:
        """Return events in insertion order, optionally scoped to a task."""
        conn = self.get_connection()
        try:
            if task_id is None:
                rows = conn.execute("SELECT * FROM agent_events ORDER BY sequence ASC").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM agent_events WHERE task_id = ? ORDER BY sequence ASC", (task_id,)
                ).fetchall()
            return [
                AgentEvent(
                    event_id=row["event_id"],
                    task_id=row["task_id"],
                    agent_id=row["agent_id"],
                    event_type=row["event_type"],
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    payload=json.loads(row["payload_json"]),
                    correlation_id=row["correlation_id"],
                )
                for row in rows
            ]
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    # --- Workflow Foundation Persistence ---
    def save_workflow_execution(
        self,
        request: WorkflowExecutionRequest,
        definition: WorkflowDefinition,
        record: WorkflowExecutionRecord,
        steps: list[WorkflowStepResult],
        event: WorkflowEvent | None = None,
    ) -> None:
        """Create one workflow execution and its initial step records atomically."""
        conn = self.get_connection()
        try:
            with conn:
                self._insert_workflow_execution(conn, request, definition, record)
                for step in steps:
                    self._upsert_workflow_step(conn, record.execution_id, step, record.updated_at)
                if event is not None:
                    self._insert_workflow_event(conn, event)
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    @staticmethod
    def _insert_workflow_execution(
        conn: sqlite3.Connection,
        request: WorkflowExecutionRequest,
        definition: WorkflowDefinition,
        record: WorkflowExecutionRecord,
    ) -> None:
        conn.execute(
            """
            INSERT INTO workflow_executions (
                execution_id, workflow_id, workflow_version, status, input_json,
                output_json, error_type, error_message, correlation_id,
                parent_execution_id, current_step_id, workflow_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, '{}', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.execution_id,
                record.workflow_id,
                definition.version,
                record.status.value,
                json.dumps(request.input_data, ensure_ascii=False, default=str),
                record.error_type,
                record.error_message,
                record.correlation_id,
                record.parent_execution_id,
                record.current_step_id,
                definition.model_dump_json(),
                record.created_at.isoformat(),
                record.updated_at.isoformat(),
            ),
        )

    @staticmethod
    def _upsert_workflow_step(
        conn: sqlite3.Connection,
        execution_id: str,
        step: WorkflowStepResult,
        updated_at: datetime,
    ) -> None:
        conn.execute(
            """
            INSERT INTO workflow_steps (
                execution_id, step_id, status, task_id, attempts, output_json,
                error_type, error_message, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(execution_id, step_id) DO UPDATE SET
                status = excluded.status,
                task_id = excluded.task_id,
                attempts = excluded.attempts,
                output_json = excluded.output_json,
                error_type = excluded.error_type,
                error_message = excluded.error_message,
                updated_at = excluded.updated_at
            """,
            (
                execution_id,
                step.step_id,
                step.status.value,
                step.task_id,
                step.attempts,
                json.dumps(step.output_data, ensure_ascii=False, default=str),
                step.error_type,
                step.error_message,
                updated_at.isoformat(),
            ),
        )

    def update_workflow_execution(
        self,
        record: WorkflowExecutionRecord,
        steps: list[WorkflowStepResult],
        event: WorkflowEvent | None = None,
    ) -> None:
        """Atomically update workflow/step state and optionally append one event."""
        conn = self.get_connection()
        try:
            with conn:
                current_row = conn.execute(
                    "SELECT status FROM workflow_executions WHERE execution_id = ?",
                    (record.execution_id,),
                ).fetchone()
                if current_row is None:
                    raise KeyError(f"Unknown workflow execution ID: '{record.execution_id}'")
                current_status = WorkflowStatus(current_row["status"])
                if (
                    record.status != current_status
                    and record.status not in ALLOWED_WORKFLOW_TRANSITIONS[current_status]
                ):
                    raise ValueError(
                        f"Invalid persisted workflow transition: "
                        f"{current_status.value} -> {record.status.value}"
                    )
                cursor = conn.execute(
                    """
                    UPDATE workflow_executions SET
                        status = ?, output_json = ?, error_type = ?, error_message = ?,
                        current_step_id = ?, updated_at = ?
                    WHERE execution_id = ?
                    """,
                    (
                        record.status.value,
                        json.dumps(record.output_data, ensure_ascii=False, default=str),
                        record.error_type,
                        record.error_message,
                        record.current_step_id,
                        record.updated_at.isoformat(),
                        record.execution_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise KeyError(f"Unknown workflow execution ID: '{record.execution_id}'")
                for step in steps:
                    self._upsert_workflow_step(conn, record.execution_id, step, record.updated_at)
                if event is not None:
                    self._insert_workflow_event(conn, event)
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    def get_workflow_execution(self, execution_id: str) -> WorkflowExecutionRecord | None:
        conn = self.get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM workflow_executions WHERE execution_id = ?", (execution_id,)
            ).fetchone()
            if row is None:
                return None
            return WorkflowExecutionRecord(
                execution_id=row["execution_id"],
                workflow_id=row["workflow_id"],
                workflow_version=row["workflow_version"],
                status=row["status"],
                input_data=json.loads(row["input_json"]),
                output_data=json.loads(row["output_json"]),
                error_type=row["error_type"],
                error_message=row["error_message"],
                correlation_id=row["correlation_id"],
                parent_execution_id=row["parent_execution_id"],
                current_step_id=row["current_step_id"],
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    def list_workflow_steps(self, execution_id: str) -> list[WorkflowStepResult]:
        conn = self.get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM workflow_steps WHERE execution_id = ? ORDER BY rowid ASC", (execution_id,)
            ).fetchall()
            return [
                WorkflowStepResult(
                    step_id=row["step_id"],
                    status=row["status"],
                    task_id=row["task_id"],
                    attempts=row["attempts"],
                    output_data=json.loads(row["output_json"]),
                    error_type=row["error_type"],
                    error_message=row["error_message"],
                )
                for row in rows
            ]
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    def get_workflow_definition(self, execution_id: str) -> WorkflowDefinition | None:
        conn = self.get_connection()
        try:
            row = conn.execute(
                "SELECT workflow_json FROM workflow_executions WHERE execution_id = ?", (execution_id,)
            ).fetchone()
            if row is None or not row["workflow_json"] or row["workflow_json"] == "{}":
                return None
            return WorkflowDefinition.model_validate_json(row["workflow_json"])
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    def append_workflow_event(self, event: WorkflowEvent) -> None:
        conn = self.get_connection()
        try:
            with conn:
                self._insert_workflow_event(conn, event)
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    @staticmethod
    def _insert_workflow_event(conn: sqlite3.Connection, event: WorkflowEvent) -> None:
        conn.execute(
            """
            INSERT INTO workflow_events (
                event_id, execution_id, workflow_id, step_id, task_id,
                event_type, timestamp, payload_json, correlation_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.execution_id,
                event.workflow_id,
                event.step_id,
                event.task_id,
                event.event_type,
                event.timestamp.isoformat(),
                json.dumps(event.payload, ensure_ascii=False, default=str),
                event.correlation_id,
            ),
        )

    def list_workflow_events(self, execution_id: str | None = None) -> list[WorkflowEvent]:
        conn = self.get_connection()
        try:
            if execution_id is None:
                rows = conn.execute("SELECT * FROM workflow_events ORDER BY sequence ASC").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM workflow_events WHERE execution_id = ? ORDER BY sequence ASC",
                    (execution_id,),
                ).fetchall()
            return [
                WorkflowEvent(
                    event_id=row["event_id"],
                    execution_id=row["execution_id"],
                    workflow_id=row["workflow_id"],
                    step_id=row["step_id"],
                    task_id=row["task_id"],
                    event_type=row["event_type"],
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    payload=json.loads(row["payload_json"]),
                    correlation_id=row["correlation_id"],
                )
                for row in rows
            ]
        finally:
            if self._conn_str != ":memory:":
                conn.close()

