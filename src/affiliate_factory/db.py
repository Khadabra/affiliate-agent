"""SQLite database manager and repository with UNIQUE constraints and append-only event logging."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


class TransactionScopeError(RuntimeError):
    """Raised when transaction invariants or ownership contracts are violated."""
    pass


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: str
    job_type: str
    payload: dict[str, Any]
    status: JobStatus
    priority: int = 100
    attempts: int = 0
    max_attempts: int = 3
    lease_token: str | None = None
    lease_expires_at: str | None = None
    worker_id: str | None = None
    idempotency_key: str | None = None
    cancellation_requested: bool = False
    created_at: str
    updated_at: str
    last_heartbeat_at: str | None = None
    completed_at: str | None = None
    error_message: str | None = None
    result_payload: dict[str, Any] | None = None


class JobRunRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    job_id: str
    attempt_number: int
    worker_id: str
    started_at: str
    ended_at: str | None = None
    final_status: str | None = None
    error_message: str | None = None


CURRENT_SCHEMA_VERSION: int = 2


class ApprovalDecision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class ApprovalRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    approval_id: str
    job_id: str
    decision: str
    reviewer: str
    notes: str | None = None
    reviewed_at: str
    draft_id: str | None = None
    prompt_version: str | None = None
    claims_fingerprint: str | None = None
    content_sha256: str | None = None
    job_attempt: int | None = None

    @field_validator("decision")
    @classmethod
    def validate_decision(cls, v: str) -> str:
        upper = v.upper()
        if upper == "APPROVED":
            upper = "APPROVE"
        elif upper == "REJECTED":
            upper = "REJECT"
        if upper not in (ApprovalDecision.APPROVE, ApprovalDecision.REJECT):
            raise ValueError(f"Invalid approval decision '{v}'. Decision must be 'APPROVE' or 'REJECT'.")
        return upper

    @property
    def has_complete_binding(self) -> bool:
        """Return True only if all 5 binding fields are present and valid."""
        return (
            bool(self.draft_id and str(self.draft_id).strip())
            and bool(self.prompt_version and str(self.prompt_version).strip())
            and bool(self.claims_fingerprint and str(self.claims_fingerprint).strip())
            and bool(self.content_sha256 and str(self.content_sha256).strip())
            and (self.job_attempt is not None and self.job_attempt >= 1)
        )

    def is_valid_for_export(
        self,
        draft_id: str | None = None,
        prompt_version: str | None = None,
        content_sha256: str | None = None,
        claims_fingerprint: str | None = None,
    ) -> bool:
        """Check if this approval is authoritative and strictly bound to the requested content.

        Legacy unbound approvals or approvals missing any binding data always return False.
        """
        if self.decision != ApprovalDecision.APPROVE:
            return False
        if not self.has_complete_binding:
            return False
        if draft_id is not None and self.draft_id != draft_id:
            return False
        if prompt_version is not None and self.prompt_version != prompt_version:
            return False
        if content_sha256 is not None and self.content_sha256 != content_sha256:
            return False
        if claims_fingerprint is not None and self.claims_fingerprint != claims_fingerprint:
            return False
        return True


def compute_content_sha256(content: str | bytes | ContentDraft) -> str:
    """Compute deterministic SHA-256 hex digest for content or ContentDraft."""
    if isinstance(content, ContentDraft):
        raw = f"{content.hook}\n{content.script}\n{content.caption}\n{content.cta}\n{content.disclosure_text}".encode("utf-8")
    elif isinstance(content, str):
        raw = content.encode("utf-8")
    else:
        raw = content
    return hashlib.sha256(raw).hexdigest()


def compute_claims_fingerprint(claims: list[Claim] | list[dict[str, Any]] | list[str]) -> str:
    """Compute deterministic SHA-256 fingerprint for a list of claims."""
    serialized: list[str] = []
    for c in claims:
        if isinstance(c, Claim):
            serialized.append(f"{c.id}:{c.text}:{c.verification_status}:{c.source_ref or ''}")
        elif isinstance(c, dict):
            serialized.append(f"{c.get('id', '')}:{c.get('text', '')}:{c.get('verification_status', '')}:{c.get('source_ref') or ''}")
        else:
            serialized.append(str(c))
    serialized.sort()
    raw = "\n".join(serialized).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class TransactionScope:
    """Manages SQLite transaction boundaries for self-managed or caller-owned connections."""

    def __init__(self, db: Database, conn: sqlite3.Connection | None = None) -> None:
        self._db = db
        self._caller_conn = conn
        self._conn: sqlite3.Connection | None = None
        self._owned = False

    def __enter__(self) -> sqlite3.Connection:
        if self._caller_conn is not None:
            if not self._caller_conn.in_transaction:
                raise TransactionScopeError(
                    "Caller-owned connection must be in an active transaction (conn.in_transaction must be True)"
                )
            self._owned = False
            self._conn = self._caller_conn
            return self._conn

        self._owned = True
        conn = self._db.get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
        except Exception:
            if self._db._conn_str != ":memory:":
                conn.close()
            raise
        self._conn = conn
        return self._conn

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        if not self._owned:
            # Caller owns the connection and transaction lifecycle.
            # Do NOT commit, do NOT rollback, do NOT close.
            return

        conn = self._conn
        if conn is None:
            return

        try:
            if exc_type is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
            else:
                try:
                    conn.commit()
                except BaseException as commit_exc:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    raise commit_exc
        finally:
            if self._db._conn_str != ":memory:":
                conn.close()


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
                self._conn = sqlite3.connect(":memory:", timeout=5.0)
                self._conn.row_factory = sqlite3.Row
                self._conn.execute("PRAGMA foreign_keys = ON")
                self._conn.execute("PRAGMA busy_timeout = 5000")
            return self._conn

        conn = sqlite3.connect(self._conn_str, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def get_journal_mode(self) -> str:
        """Return the current journal mode."""
        conn = self.get_connection()
        try:
            row = conn.execute("PRAGMA journal_mode").fetchone()
            return str(row[0]).lower() if row else ""
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    def get_busy_timeout(self) -> int:
        """Return the current busy timeout in milliseconds."""
        conn = self.get_connection()
        try:
            row = conn.execute("PRAGMA busy_timeout").fetchone()
            return int(row[0]) if row else 0
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    def get_foreign_keys_status(self) -> bool:
        """Return True if foreign key enforcement is active."""
        conn = self.get_connection()
        try:
            row = conn.execute("PRAGMA foreign_keys").fetchone()
            return bool(row[0]) if row else False
        finally:
            if self._conn_str != ":memory:":
                conn.close()

    def init_schema(self) -> None:
        """Create all required tables with appropriate constraints atomically."""
        conn = self.get_connection()
        try:
            if self._conn_str != ":memory:":
                conn.execute("PRAGMA journal_mode = WAL")

            current_version = conn.execute("PRAGMA user_version").fetchone()[0]
            if current_version > CURRENT_SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database schema version {current_version} is newer than supported version {CURRENT_SCHEMA_VERSION}."
                )

            # Check if database is already fully migrated
            if current_version == CURRENT_SCHEMA_VERSION:
                fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
                if fk_violations:
                    details = [
                        f"table={row[0]}, rowid={row[1]}, parent={row[2]}, fkid={row[3]}"
                        for row in fk_violations
                    ]
                    raise RuntimeError(
                        f"Database schema initialization/migration failed foreign key validation: {', '.join(details)}"
                    )
                return

            # Pre-migration backup for existing non-empty on-disk databases
            if isinstance(self.db_path, Path) and self.db_path.exists() and self.db_path.stat().st_size > 0:
                backup_dir = self.db_path.parent / ".backups"
                ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                backup_name = f"{self.db_path.stem}_pre_migration_v{current_version}_{ts}.db"
                try:
                    self.create_safe_database_backup(backup_dir, backup_name=backup_name)
                except Exception:
                    pass

            conn.execute("BEGIN IMMEDIATE")
            try:
                # 1. Base entities (products, content_drafts)
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS products (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        url TEXT NOT NULL UNIQUE,
                        price REAL,
                        price_observed_at TEXT,
                        source TEXT NOT NULL,
                        notes TEXT
                    )
                    """
                )
                conn.execute(
                    """
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
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_content_drafts_product ON content_drafts (product_id)"
                )

                # 2. Transparent migration & orphan preservation for compliance_reports
                table_check = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='compliance_reports'"
                ).fetchone()
                if table_check:
                    cols = {
                        row["name"]
                        for row in conn.execute("PRAGMA table_info(compliance_reports)").fetchall()
                    }
                    fk_list = conn.execute("PRAGMA foreign_key_list(compliance_reports)").fetchall()
                    has_fk = any(row["table"] == "content_drafts" for row in fk_list)
                    has_pv = "prompt_version" in cols

                    if not (has_fk and has_pv):
                        if not has_pv:
                            orphans = conn.execute(
                                """
                                SELECT cr.draft_id, 'v1.0' AS prompt_version
                                FROM compliance_reports cr
                                LEFT JOIN content_drafts cd
                                    ON cr.draft_id = cd.id AND cd.prompt_version = 'v1.0'
                                WHERE cd.id IS NULL
                                """
                            ).fetchall()
                        else:
                            orphans = conn.execute(
                                """
                                SELECT cr.draft_id, cr.prompt_version
                                FROM compliance_reports cr
                                LEFT JOIN content_drafts cd
                                    ON cr.draft_id = cd.id AND cr.prompt_version = cd.prompt_version
                                WHERE cd.id IS NULL
                                """
                            ).fetchall()

                        if orphans:
                            conn.execute(
                                """
                                INSERT OR IGNORE INTO products (id, name, url, source, notes)
                                VALUES (
                                    'orphan_recovery_fallback_prod',
                                    'Orphan Recovery Fallback Product',
                                    'https://shopee.co.id/internal-orphan-fallback',
                                    'migration_orphan_preservation',
                                    'Auto-created during migration to preserve orphaned compliance reports and claims'
                                )
                                """
                            )
                            now_iso = datetime.now(timezone.utc).isoformat()
                            for o in orphans:
                                d_id = o["draft_id"]
                                p_ver = o["prompt_version"]
                                conn.execute(
                                    """
                                    INSERT OR IGNORE INTO content_drafts (
                                        id, product_id, angle, hook, script, caption, cta,
                                        disclosure_text, status, prompt_version, created_at
                                    ) VALUES (
                                        ?, 'orphan_recovery_fallback_prod', 'Recovered Orphan',
                                        'Preserved orphan hook', 'Preserved orphan script',
                                        'Preserved orphan caption', 'Preserved orphan cta',
                                        '#PreservedOrphan', 'waiting_approval', ?, ?
                                    )
                                    """,
                                    (d_id, p_ver, now_iso),
                                )

                        conn.execute(
                            """
                            CREATE TABLE compliance_reports_v2 (
                                draft_id TEXT NOT NULL,
                                prompt_version TEXT NOT NULL DEFAULT 'v1.0',
                                passed INTEGER NOT NULL,
                                findings_json TEXT NOT NULL,
                                PRIMARY KEY (draft_id, prompt_version),
                                FOREIGN KEY (draft_id, prompt_version) REFERENCES content_drafts (id, prompt_version) ON DELETE CASCADE
                            )
                            """
                        )
                        if not has_pv:
                            conn.execute(
                                """
                                INSERT INTO compliance_reports_v2 (draft_id, prompt_version, passed, findings_json)
                                SELECT draft_id, 'v1.0', passed, findings_json FROM compliance_reports
                                """
                            )
                        else:
                            conn.execute(
                                """
                                INSERT INTO compliance_reports_v2 (draft_id, prompt_version, passed, findings_json)
                                SELECT draft_id, prompt_version, passed, findings_json FROM compliance_reports
                                """
                            )
                        conn.execute("DROP TABLE compliance_reports")
                        conn.execute("ALTER TABLE compliance_reports_v2 RENAME TO compliance_reports")

                # 3. Transparent migration & orphan preservation for claims
                table_check_claims = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='claims'"
                ).fetchone()
                if table_check_claims:
                    claim_cols = {
                        row["name"]
                        for row in conn.execute("PRAGMA table_info(claims)").fetchall()
                    }
                    claim_fk_list = conn.execute("PRAGMA foreign_key_list(claims)").fetchall()
                    claim_has_fk = any(row["table"] == "content_drafts" for row in claim_fk_list)
                    claim_has_pv = "prompt_version" in claim_cols

                    if not (claim_has_fk and claim_has_pv):
                        if not claim_has_pv:
                            conn.execute("ALTER TABLE claims ADD COLUMN prompt_version TEXT")
                            claim_cols.add("prompt_version")

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

                        orphaned_claims = conn.execute(
                            """
                            SELECT DISTINCT c.draft_id, c.prompt_version
                            FROM claims c
                            LEFT JOIN content_drafts cd
                                ON c.draft_id = cd.id AND c.prompt_version = cd.prompt_version
                            WHERE c.prompt_version IS NOT NULL AND cd.id IS NULL
                            """
                        ).fetchall()

                        if orphaned_claims:
                            conn.execute(
                                """
                                INSERT OR IGNORE INTO products (id, name, url, source, notes)
                                VALUES (
                                    'orphan_recovery_fallback_prod',
                                    'Orphan Recovery Fallback Product',
                                    'https://shopee.co.id/internal-orphan-fallback',
                                    'migration_orphan_preservation',
                                    'Auto-created during migration to preserve orphaned compliance reports and claims'
                                )
                                """
                            )
                            now_iso = datetime.now(timezone.utc).isoformat()
                            for o in orphaned_claims:
                                d_id = o["draft_id"]
                                p_ver = o["prompt_version"]
                                conn.execute(
                                    """
                                    INSERT OR IGNORE INTO content_drafts (
                                        id, product_id, angle, hook, script, caption, cta,
                                        disclosure_text, status, prompt_version, created_at
                                    ) VALUES (
                                        ?, 'orphan_recovery_fallback_prod', 'Recovered Orphan',
                                        'Preserved orphan hook', 'Preserved orphan script',
                                        'Preserved orphan caption', 'Preserved orphan cta',
                                        '#PreservedOrphan', 'waiting_approval', ?, ?
                                    )
                                    """,
                                    (d_id, p_ver, now_iso),
                                )

                        conn.execute(
                            """
                            CREATE TABLE claims_v2 (
                                id TEXT PRIMARY KEY,
                                draft_id TEXT NOT NULL,
                                prompt_version TEXT,
                                text TEXT NOT NULL,
                                source_ref TEXT,
                                verification_status TEXT NOT NULL,
                                FOREIGN KEY (draft_id, prompt_version) REFERENCES content_drafts (id, prompt_version) ON DELETE CASCADE
                            )
                            """
                        )
                        conn.execute(
                            """
                            INSERT INTO claims_v2 (id, draft_id, prompt_version, text, source_ref, verification_status)
                            SELECT id, draft_id, prompt_version, text, source_ref, verification_status FROM claims
                            """
                        )
                        conn.execute("DROP TABLE claims")
                        conn.execute("ALTER TABLE claims_v2 RENAME TO claims")
                        conn.execute(
                            "CREATE INDEX IF NOT EXISTS idx_claims_draft_version ON claims (draft_id, prompt_version)"
                        )

                # 4. workflow_executions check
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

                # 5. approval_records migration
                table_check_approvals = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='approval_records'"
                ).fetchone()
                if table_check_approvals:
                    appr_cols = {
                        row["name"]
                        for row in conn.execute("PRAGMA table_info(approval_records)").fetchall()
                    }
                    if "draft_id" not in appr_cols:
                        conn.execute(
                            """
                            CREATE TABLE approval_records_v2 (
                                approval_id TEXT PRIMARY KEY,
                                job_id TEXT NOT NULL,
                                decision TEXT NOT NULL CHECK (decision IN ('APPROVE', 'REJECT')),
                                reviewer TEXT NOT NULL,
                                notes TEXT,
                                reviewed_at TEXT NOT NULL,
                                draft_id TEXT,
                                prompt_version TEXT,
                                claims_fingerprint TEXT,
                                content_sha256 TEXT,
                                job_attempt INTEGER,
                                FOREIGN KEY (job_id) REFERENCES jobs (job_id) ON DELETE CASCADE,
                                FOREIGN KEY (draft_id, prompt_version) REFERENCES content_drafts (id, prompt_version) ON DELETE CASCADE
                            )
                            """
                        )
                        conn.execute(
                            """
                            INSERT INTO approval_records_v2 (
                                approval_id, job_id, decision, reviewer, notes, reviewed_at,
                                draft_id, prompt_version, claims_fingerprint, content_sha256, job_attempt
                            )
                            SELECT
                                approval_id,
                                job_id,
                                CASE
                                    WHEN UPPER(decision) = 'APPROVED' THEN 'APPROVE'
                                    WHEN UPPER(decision) = 'REJECTED' THEN 'REJECT'
                                    ELSE UPPER(decision)
                                END,
                                reviewer,
                                notes,
                                reviewed_at,
                                NULL, NULL, NULL, NULL, NULL
                            FROM approval_records
                            """
                        )
                        conn.execute("DROP TABLE approval_records")
                        conn.execute("ALTER TABLE approval_records_v2 RENAME TO approval_records")
                        conn.execute(
                            "CREATE INDEX IF NOT EXISTS idx_approval_records_job ON approval_records (job_id)"
                        )
                        conn.execute(
                            "CREATE INDEX IF NOT EXISTS idx_approval_records_draft ON approval_records (draft_id, prompt_version)"
                        )
                        conn.execute(
                            """
                            CREATE UNIQUE INDEX IF NOT EXISTS idx_approval_records_authoritative_unique
                                ON approval_records (job_id)
                                WHERE decision = 'APPROVE'
                            """
                        )

                # 6. Ensure all required tables and indexes exist
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS products (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        url TEXT NOT NULL UNIQUE,
                        price REAL,
                        price_observed_at TEXT,
                        source TEXT NOT NULL,
                        notes TEXT
                    )
                    """
                )
                conn.execute(
                    """
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
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_content_drafts_product ON content_drafts (product_id)")

                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS claims (
                        id TEXT PRIMARY KEY,
                        draft_id TEXT NOT NULL,
                        prompt_version TEXT,
                        text TEXT NOT NULL,
                        source_ref TEXT,
                        verification_status TEXT NOT NULL,
                        FOREIGN KEY (draft_id, prompt_version) REFERENCES content_drafts (id, prompt_version) ON DELETE CASCADE
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_claims_draft_version ON claims (draft_id, prompt_version)")

                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS compliance_reports (
                        draft_id TEXT NOT NULL,
                        prompt_version TEXT NOT NULL DEFAULT 'v1.0',
                        passed INTEGER NOT NULL,
                        findings_json TEXT NOT NULL,
                        PRIMARY KEY (draft_id, prompt_version),
                        FOREIGN KEY (draft_id, prompt_version) REFERENCES content_drafts (id, prompt_version) ON DELETE CASCADE
                    )
                    """
                )

                conn.execute(
                    """
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
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_perf_content_platform ON performance_records (content_id, platform, observed_at)")

                conn.execute(
                    """
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
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_events_run_id ON events (run_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_events_ref ON events (ref_id, module, action)")

                conn.execute(
                    """
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
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_tasks_correlation ON agent_tasks (correlation_id)")

                conn.execute(
                    """
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
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_events_task ON agent_events (task_id, sequence)")

                conn.execute(
                    """
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
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_workflow_executions_correlation ON workflow_executions (correlation_id)")

                conn.execute(
                    """
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
                    )
                    """
                )

                conn.execute(
                    """
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
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_workflow_events_execution ON workflow_events (execution_id, sequence)")

                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS jobs (
                        job_id TEXT PRIMARY KEY,
                        job_type TEXT NOT NULL,
                        payload TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'queued',
                        priority INTEGER NOT NULL DEFAULT 100,
                        attempts INTEGER NOT NULL DEFAULT 0,
                        max_attempts INTEGER NOT NULL DEFAULT 3,
                        lease_token TEXT,
                        lease_expires_at TEXT,
                        worker_id TEXT,
                        idempotency_key TEXT UNIQUE,
                        cancellation_requested INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        last_heartbeat_at TEXT,
                        completed_at TEXT,
                        error_message TEXT,
                        result_payload TEXT
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_claim_candidate ON jobs (status, priority, created_at) WHERE status = 'queued'")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_stale_recovery ON jobs (status, lease_expires_at) WHERE status = 'running'")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_idempotency ON jobs (idempotency_key) WHERE idempotency_key IS NOT NULL")

                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS job_runs (
                        run_id TEXT PRIMARY KEY,
                        job_id TEXT NOT NULL,
                        attempt_number INTEGER NOT NULL,
                        worker_id TEXT NOT NULL,
                        started_at TEXT NOT NULL,
                        ended_at TEXT,
                        final_status TEXT,
                        error_message TEXT,
                        FOREIGN KEY (job_id) REFERENCES jobs (job_id) ON DELETE CASCADE
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_job_runs_job ON job_runs (job_id, attempt_number)")

                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS approval_records (
                        approval_id TEXT PRIMARY KEY,
                        job_id TEXT NOT NULL,
                        decision TEXT NOT NULL CHECK (decision IN ('APPROVE', 'REJECT')),
                        reviewer TEXT NOT NULL,
                        notes TEXT,
                        reviewed_at TEXT NOT NULL,
                        draft_id TEXT,
                        prompt_version TEXT,
                        claims_fingerprint TEXT,
                        content_sha256 TEXT,
                        job_attempt INTEGER,
                        FOREIGN KEY (job_id) REFERENCES jobs (job_id) ON DELETE CASCADE,
                        FOREIGN KEY (draft_id, prompt_version) REFERENCES content_drafts (id, prompt_version) ON DELETE CASCADE
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_approval_records_job ON approval_records (job_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_approval_records_draft ON approval_records (draft_id, prompt_version)")
                conn.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_approval_records_authoritative_unique
                        ON approval_records (job_id)
                        WHERE decision = 'APPROVE'
                    """
                )

                # 7. PRAGMA foreign_key_check before commit
                fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
                if fk_violations:
                    details = [
                        f"table={row[0]}, rowid={row[1]}, parent={row[2]}, fkid={row[3]}"
                        for row in fk_violations
                    ]
                    raise RuntimeError(
                        f"Database schema initialization/migration failed foreign key validation: {', '.join(details)}"
                    )

                # 8. Set user_version to CURRENT_SCHEMA_VERSION and commit
                conn.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        finally:
            if self._conn_str != ":memory:":
                conn.close()
    # --- Product Operations ---
    def insert_product(self, product: Product, conn: sqlite3.Connection | None = None) -> bool:
        """Insert a product. Returns True if inserted, False if URL already exists."""
        try:
            with TransactionScope(self, conn) as c:
                c.execute(
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

    def get_product_by_url(self, url: str, conn: sqlite3.Connection | None = None) -> Product | None:
        c = conn if conn is not None else self.get_connection()
        try:
            cursor = c.execute("SELECT * FROM products WHERE url = ?", (url,))
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
            if conn is None and self._conn_str != ":memory:":
                c.close()

    def get_product(self, product_id: str, conn: sqlite3.Connection | None = None) -> Product | None:
        c = conn if conn is not None else self.get_connection()
        try:
            cursor = c.execute("SELECT * FROM products WHERE id = ?", (product_id,))
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
            if conn is None and self._conn_str != ":memory:":
                c.close()

    # --- ContentDraft Operations ---
    def upsert_draft(self, draft: ContentDraft, conn: sqlite3.Connection | None = None) -> bool:
        """Insert or update a draft for a given (id, prompt_version)."""
        with TransactionScope(self, conn) as c:
            c.execute(
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

    def update_draft_status(
        self, draft_id: str, prompt_version: str, status: str, conn: sqlite3.Connection | None = None
    ) -> None:
        with TransactionScope(self, conn) as c:
            c.execute(
                "UPDATE content_drafts SET status = ? WHERE id = ? AND prompt_version = ?",
                (status, draft_id, prompt_version),
            )

    def get_draft(self, draft_id: str, prompt_version: str, conn: sqlite3.Connection | None = None) -> ContentDraft | None:
        c = conn if conn is not None else self.get_connection()
        try:
            cursor = c.execute(
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
            if conn is None and self._conn_str != ":memory:":
                c.close()

    def get_drafts_by_id(self, draft_id: str, conn: sqlite3.Connection | None = None) -> list[ContentDraft]:
        """Retrieve all prompt versions of a draft by its ID."""
        c = conn if conn is not None else self.get_connection()
        try:
            cursor = c.execute(
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
            if conn is None and self._conn_str != ":memory:":
                c.close()

    def list_all_drafts(self, conn: sqlite3.Connection | None = None) -> list[ContentDraft]:
        """List all drafts in the database across all versions."""
        c = conn if conn is not None else self.get_connection()
        try:
            cursor = c.execute("SELECT * FROM content_drafts ORDER BY id ASC, prompt_version ASC")
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
            if conn is None and self._conn_str != ":memory:":
                c.close()

    # --- Compliance Operations ---
    def save_compliance_report(self, report: ComplianceReport, conn: sqlite3.Connection | None = None) -> None:
        findings_data = [f.model_dump() for f in report.findings]
        with TransactionScope(self, conn) as c:
            c.execute(
                """
                INSERT INTO compliance_reports (draft_id, prompt_version, passed, findings_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(draft_id, prompt_version) DO UPDATE SET
                    passed=excluded.passed,
                    findings_json=excluded.findings_json
                """,
                (report.draft_id, report.prompt_version, 1 if report.passed else 0, json.dumps(findings_data)),
            )

    def get_compliance_report(
        self, draft_id: str, prompt_version: str | None = None, conn: sqlite3.Connection | None = None
    ) -> ComplianceReport | None:
        c = conn if conn is not None else self.get_connection()
        try:
            if prompt_version is not None:
                cursor = c.execute(
                    "SELECT * FROM compliance_reports WHERE draft_id = ? AND prompt_version = ?",
                    (draft_id, prompt_version),
                )
            else:
                cursor = c.execute(
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
            if conn is None and self._conn_str != ":memory:":
                c.close()

    # --- Claims Operations ---
    def save_claims(self, claims: list[Claim], conn: sqlite3.Connection | None = None) -> None:
        with TransactionScope(self, conn) as c:
            for clm in claims:
                pv = clm.prompt_version
                if pv is None:
                    # Check if there is exactly 1 distinct prompt_version for this draft in content_drafts
                    pv_rows = c.execute(
                        "SELECT DISTINCT prompt_version FROM content_drafts WHERE id = ?",
                        (clm.draft_id,),
                    ).fetchall()
                    if len(pv_rows) == 1:
                        pv = pv_rows[0]["prompt_version"]

                c.execute(
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
                    (clm.id, clm.draft_id, pv, clm.text, clm.source_ref, clm.verification_status),
                )

    def find_orphaned_compliance_reports(self, conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
        """Return all compliance reports that reference a non-existent draft version."""
        c = conn if conn is not None else self.get_connection()
        try:
            cursor = c.execute(
                """
                SELECT cr.*
                FROM compliance_reports cr
                LEFT JOIN content_drafts cd
                    ON cr.draft_id = cd.id AND cr.prompt_version = cd.prompt_version
                WHERE cd.id IS NULL
                ORDER BY cr.draft_id ASC, cr.prompt_version ASC
                """
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            if conn is None and self._conn_str != ":memory:":
                c.close()

    def find_orphaned_claims(self, conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
        """Return all claims that reference a non-existent draft version."""
        c = conn if conn is not None else self.get_connection()
        try:
            cursor = c.execute(
                """
                SELECT c.*
                FROM claims c
                LEFT JOIN content_drafts cd
                    ON c.draft_id = cd.id AND (
                        c.prompt_version = cd.prompt_version
                        OR (c.prompt_version IS NULL AND cd.id IS NOT NULL)
                    )
                WHERE cd.id IS NULL
                ORDER BY c.id ASC
                """
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            if conn is None and self._conn_str != ":memory:":
                c.close()

    def get_claim(self, claim_id: str, conn: sqlite3.Connection | None = None) -> Claim | None:
        c = conn if conn is not None else self.get_connection()
        try:
            cursor = c.execute("SELECT * FROM claims WHERE id = ?", (claim_id,))
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
            if conn is None and self._conn_str != ":memory:":
                c.close()

    def update_claim_status(
        self, claim_id: str, verification_status: str, conn: sqlite3.Connection | None = None
    ) -> bool:
        """Update verification status of an existing claim. Returns True if updated, False if not found."""
        with TransactionScope(self, conn) as c:
            cursor = c.execute(
                "UPDATE claims SET verification_status = ? WHERE id = ?",
                (verification_status, claim_id),
            )
            return cursor.rowcount > 0

    def get_claims_for_draft(
        self, draft_id: str, prompt_version: str | None = None, conn: sqlite3.Connection | None = None
    ) -> list[Claim]:
        c = conn if conn is not None else self.get_connection()
        try:
            if prompt_version is not None:
                cursor = c.execute(
                    "SELECT * FROM claims WHERE draft_id = ? AND prompt_version = ? ORDER BY id ASC",
                    (draft_id, prompt_version),
                )
            else:
                cursor = c.execute(
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
            if conn is None and self._conn_str != ":memory:":
                c.close()

    # --- Performance Records ---
    def save_performance_record(
        self,
        record_id: str | PerformanceRecord,
        record: PerformanceRecord | None = None,
        allow_overwrite: bool = False,
        conn: sqlite3.Connection | None = None,
    ) -> str:
        """Save a performance record snapshot.

        Invariants:
        - By default (allow_overwrite=False), duplicate snapshot IDs are strictly
          rejected with ValueError to protect historical snapshot immutability.
        - If allow_overwrite=True, explicitly updates an existing snapshot.
        """
        if isinstance(record_id, PerformanceRecord):
            rec = record_id
            rec_id = rec.id or str(uuid.uuid4())
        else:
            rec = record
            if rec is None:
                raise ValueError("PerformanceRecord instance is required.")
            rec_id = record_id or rec.id or str(uuid.uuid4())

        rec.id = rec_id
        with TransactionScope(self, conn) as c:
            if not allow_overwrite:
                try:
                    c.execute(
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
                c.execute(
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

    def get_performance_record(self, record_id: str, conn: sqlite3.Connection | None = None) -> PerformanceRecord | None:
        c = conn if conn is not None else self.get_connection()
        try:
            cursor = c.execute(
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
            if conn is None and self._conn_str != ":memory:":
                c.close()

    def list_performance_records(
        self,
        content_id: str | None = None,
        platform: str | None = None,
        start_date: datetime | str | None = None,
        end_date: datetime | str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> list[PerformanceRecord]:
        """List performance record snapshots filtered by content, platform, or date range.

        Returns snapshots sorted chronologically with deterministic tie-breaking (observed_at ASC, id ASC).
        """
        c = conn if conn is not None else self.get_connection()
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
            cursor = c.execute(query, tuple(params))
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
            if conn is None and self._conn_str != ":memory:":
                c.close()

    def correct_performance_record(
        self,
        record_id: str,
        updated_record: PerformanceRecord,
        reason: str | None = None,
        run_id: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> Event:
        """Atomically correct an existing performance snapshot and record an audit event."""
        with TransactionScope(self, conn) as c:
            cursor = c.execute(
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

            c.execute(
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

            c.execute(
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

    def list_correction_events(
        self, record_id: str | None = None, conn: sqlite3.Connection | None = None
    ) -> list[Event]:
        """List correction audit events, optionally filtered by snapshot record_id."""
        c = conn if conn is not None else self.get_connection()
        try:
            if record_id:
                cursor = c.execute(
                    """
                    SELECT * FROM events
                    WHERE module = 'performance' AND action = 'correct_snapshot' AND ref_id = ?
                    ORDER BY ts ASC
                    """,
                    (record_id,),
                )
            else:
                cursor = c.execute(
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
            if conn is None and self._conn_str != ":memory:":
                c.close()

    @staticmethod
    def parse_correction_payload(event: Event) -> PerformanceCorrectionPayload:
        """Parse structured correction payload from an audit event."""
        if not event.note:
            raise ValueError(f"Event '{event.id}' has empty note")
        return PerformanceCorrectionPayload.model_validate_json(event.note)

    # --- Event Log Operations (Append-Only) ---
    def append_event(self, event: Event, conn: sqlite3.Connection | None = None) -> None:
        with TransactionScope(self, conn) as c:
            c.execute(
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

    def list_events(self, run_id: str | None = None, conn: sqlite3.Connection | None = None) -> list[Event]:
        c = conn if conn is not None else self.get_connection()
        try:
            if run_id:
                cursor = c.execute("SELECT * FROM events WHERE run_id = ? ORDER BY ts ASC", (run_id,))
            else:
                cursor = c.execute("SELECT * FROM events ORDER BY ts ASC")
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
            if conn is None and self._conn_str != ":memory:":
                c.close()

    # --- Agent Foundation Persistence ---
    def save_agent_task(self, task: AgentTask, conn: sqlite3.Connection | None = None) -> None:
        """Insert a new agent task; duplicate IDs fail instead of overwriting."""
        with TransactionScope(self, conn) as c:
            c.execute(
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

    def update_agent_task(
        self, task: AgentTask, result: AgentResult | None = None, conn: sqlite3.Connection | None = None
    ) -> None:
        """Persist lifecycle state and, when available, the terminal result."""
        output_json = json.dumps(result.output_data, ensure_ascii=False, default=str) if result else "{}"
        error_json = result.error.model_dump_json() if result and result.error else None
        metadata_json = (
            json.dumps(result.execution_metadata, ensure_ascii=False, default=str) if result else "{}"
        )
        with TransactionScope(self, conn) as c:
            current_row = c.execute(
                "SELECT status FROM agent_tasks WHERE task_id = ?", (task.task_id,)
            ).fetchone()
            if current_row is None:
                raise KeyError(f"Unknown agent task ID: '{task.task_id}'")
            current_status = TaskStatus(current_row["status"])
            if task.status != current_status and task.status not in ALLOWED_TASK_TRANSITIONS[current_status]:
                raise ValueError(
                    f"Invalid persisted task transition: {current_status.value} -> {task.status.value}"
                )
            cursor = c.execute(
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

    def save_agent_task_with_event(
        self, task: AgentTask, event: AgentEvent, conn: sqlite3.Connection | None = None
    ) -> None:
        """Atomically create an agent task and its first event."""
        with TransactionScope(self, conn) as c:
            c.execute(
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
            self._insert_agent_event(c, event)

    def update_agent_task_with_event(
        self,
        task: AgentTask,
        result: AgentResult | None,
        event: AgentEvent,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        """Atomically update an agent task and append its lifecycle event."""
        output_json = json.dumps(result.output_data, ensure_ascii=False, default=str) if result else "{}"
        error_json = result.error.model_dump_json() if result and result.error else None
        metadata_json = (
            json.dumps(result.execution_metadata, ensure_ascii=False, default=str) if result else "{}"
        )
        with TransactionScope(self, conn) as c:
            current_row = c.execute(
                "SELECT status FROM agent_tasks WHERE task_id = ?", (task.task_id,)
            ).fetchone()
            if current_row is None:
                raise KeyError(f"Unknown agent task ID: '{task.task_id}'")
            current_status = TaskStatus(current_row["status"])
            if task.status != current_status and task.status not in ALLOWED_TASK_TRANSITIONS[current_status]:
                raise ValueError(
                    f"Invalid persisted task transition: {current_status.value} -> {task.status.value}"
                )
            cursor = c.execute(
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
            self._insert_agent_event(c, event)

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

    def get_agent_task(self, task_id: str, conn: sqlite3.Connection | None = None) -> AgentTask | None:
        """Load one persisted task, or ``None`` when it does not exist."""
        c = conn if conn is not None else self.get_connection()
        try:
            row = c.execute("SELECT * FROM agent_tasks WHERE task_id = ?", (task_id,)).fetchone()
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
            if conn is None and self._conn_str != ":memory:":
                c.close()

    def get_agent_result(self, task_id: str, conn: sqlite3.Connection | None = None) -> AgentResult | None:
        """Load a persisted terminal result, including output and error data."""
        c = conn if conn is not None else self.get_connection()
        try:
            row = c.execute("SELECT * FROM agent_tasks WHERE task_id = ?", (task_id,)).fetchone()
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
            if conn is None and self._conn_str != ":memory:":
                c.close()

    def append_agent_event(self, event: AgentEvent, conn: sqlite3.Connection | None = None) -> None:
        """Append one agent event; FK enforcement prevents orphan events."""
        with TransactionScope(self, conn) as c:
            self._insert_agent_event(c, event)

    def list_agent_events(self, task_id: str | None = None, conn: sqlite3.Connection | None = None) -> list[AgentEvent]:
        """Return events in insertion order, optionally scoped to a task."""
        c = conn if conn is not None else self.get_connection()
        try:
            if task_id is None:
                rows = c.execute("SELECT * FROM agent_events ORDER BY sequence ASC").fetchall()
            else:
                rows = c.execute(
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
            if conn is None and self._conn_str != ":memory:":
                c.close()

    # --- Workflow Foundation Persistence ---
    def save_workflow_execution(
        self,
        request: WorkflowExecutionRequest,
        definition: WorkflowDefinition,
        record: WorkflowExecutionRecord,
        steps: list[WorkflowStepResult],
        event: WorkflowEvent | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        """Create one workflow execution and its initial step records atomically."""
        with TransactionScope(self, conn) as c:
            self._insert_workflow_execution(c, request, definition, record)
            for step in steps:
                self._upsert_workflow_step(c, record.execution_id, step, record.updated_at)
            if event is not None:
                self._insert_workflow_event(c, event)

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
        conn: sqlite3.Connection | None = None,
    ) -> None:
        """Atomically update workflow/step state and optionally append one event."""
        with TransactionScope(self, conn) as c:
            current_row = c.execute(
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
            cursor = c.execute(
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
                self._upsert_workflow_step(c, record.execution_id, step, record.updated_at)
            if event is not None:
                self._insert_workflow_event(c, event)

    def get_workflow_execution(
        self, execution_id: str, conn: sqlite3.Connection | None = None
    ) -> WorkflowExecutionRecord | None:
        c = conn if conn is not None else self.get_connection()
        try:
            row = c.execute(
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
            if conn is None and self._conn_str != ":memory:":
                c.close()

    def list_workflow_steps(
        self, execution_id: str, conn: sqlite3.Connection | None = None
    ) -> list[WorkflowStepResult]:
        c = conn if conn is not None else self.get_connection()
        try:
            rows = c.execute(
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
            if conn is None and self._conn_str != ":memory:":
                c.close()

    def get_workflow_definition(
        self, execution_id: str, conn: sqlite3.Connection | None = None
    ) -> WorkflowDefinition | None:
        c = conn if conn is not None else self.get_connection()
        try:
            row = c.execute(
                "SELECT workflow_json FROM workflow_executions WHERE execution_id = ?", (execution_id,)
            ).fetchone()
            if row is None or not row["workflow_json"] or row["workflow_json"] == "{}":
                return None
            return WorkflowDefinition.model_validate_json(row["workflow_json"])
        finally:
            if conn is None and self._conn_str != ":memory:":
                c.close()

    def append_workflow_event(self, event: WorkflowEvent, conn: sqlite3.Connection | None = None) -> None:
        with TransactionScope(self, conn) as c:
            self._insert_workflow_event(c, event)

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

    def list_workflow_events(
        self, execution_id: str | None = None, conn: sqlite3.Connection | None = None
    ) -> list[WorkflowEvent]:
        c = conn if conn is not None else self.get_connection()
        try:
            if execution_id is None:
                rows = c.execute("SELECT * FROM workflow_events ORDER BY sequence ASC").fetchall()
            else:
                rows = c.execute(
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
            if conn is None and self._conn_str != ":memory:":
                c.close()

    # --- Phase A2 Persistent Queue & Job Operations ---
    def _row_to_job(self, row: sqlite3.Row) -> JobRecord:
        payload = json.loads(row["payload"]) if row["payload"] else {}
        result_payload = json.loads(row["result_payload"]) if row["result_payload"] else None
        return JobRecord(
            job_id=row["job_id"],
            job_type=row["job_type"],
            payload=payload,
            status=JobStatus(row["status"]),
            priority=row["priority"],
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            lease_token=row["lease_token"],
            lease_expires_at=row["lease_expires_at"],
            worker_id=row["worker_id"],
            idempotency_key=row["idempotency_key"],
            cancellation_requested=bool(row["cancellation_requested"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_heartbeat_at=row["last_heartbeat_at"],
            completed_at=row["completed_at"],
            error_message=row["error_message"],
            result_payload=result_payload,
        )

    def submit_job(
        self,
        job_type: str,
        payload: dict[str, Any],
        priority: int = 100,
        max_attempts: int = 3,
        idempotency_key: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> JobRecord:
        """Submit a job to the persistent queue.

        If idempotency_key is provided and a job with that key already exists,
        returns the existing JobRecord without creating a duplicate.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        with TransactionScope(self, conn) as c:
            if idempotency_key:
                existing = self.get_job_by_idempotency_key(idempotency_key, conn=c)
                if existing is not None:
                    return existing

            job_id = str(uuid.uuid4())
            payload_str = json.dumps(payload, ensure_ascii=False, default=str)
            c.execute(
                """
                INSERT INTO jobs (
                    job_id, job_type, payload, status, priority, attempts,
                    max_attempts, lease_token, lease_expires_at, worker_id,
                    idempotency_key, cancellation_requested, created_at,
                    updated_at, last_heartbeat_at, completed_at, error_message,
                    result_payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, 0, ?, ?, NULL, NULL, NULL, NULL)
                """,
                (
                    job_id,
                    job_type,
                    payload_str,
                    JobStatus.QUEUED.value,
                    priority,
                    0,
                    max_attempts,
                    idempotency_key,
                    now_iso,
                    now_iso,
                ),
            )
            return JobRecord(
                job_id=job_id,
                job_type=job_type,
                payload=payload,
                status=JobStatus.QUEUED,
                priority=priority,
                attempts=0,
                max_attempts=max_attempts,
                lease_token=None,
                lease_expires_at=None,
                worker_id=None,
                idempotency_key=idempotency_key,
                cancellation_requested=False,
                created_at=now_iso,
                updated_at=now_iso,
                last_heartbeat_at=None,
                completed_at=None,
                error_message=None,
                result_payload=None,
            )

    def get_job(self, job_id: str, conn: sqlite3.Connection | None = None) -> JobRecord | None:
        c = conn if conn is not None else self.get_connection()
        try:
            row = c.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if row is None:
                return None
            return self._row_to_job(row)
        finally:
            if conn is None and self._conn_str != ":memory:":
                c.close()

    def get_job_by_idempotency_key(
        self, idempotency_key: str, conn: sqlite3.Connection | None = None
    ) -> JobRecord | None:
        c = conn if conn is not None else self.get_connection()
        try:
            row = c.execute("SELECT * FROM jobs WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
            if row is None:
                return None
            return self._row_to_job(row)
        finally:
            if conn is None and self._conn_str != ":memory:":
                c.close()

    def claim_next_job(
        self,
        worker_id: str,
        supported_types: list[str] | None = None,
        lease_duration_seconds: int = 60,
        conn: sqlite3.Connection | None = None,
    ) -> JobRecord | None:
        """Atomically claim the next eligible job.

        1. Sweeps expired running jobs:
           - If attempts >= max_attempts: marks as 'failed'.
           - If attempts < max_attempts: re-queues them.
        2. Finds highest-priority (lowest number), oldest queued job that is not cancelled.
        3. Updates status to 'running', increments attempts, generates fresh lease token and expiration.
        4. Inserts an attempt row into job_runs.
        All within an immediate transaction.
        """
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        lease_expires = (now + timedelta(seconds=lease_duration_seconds)).isoformat()

        with TransactionScope(self, conn) as c:
            # 1. Stale recovery sweeper
            stale_rows = c.execute(
                """
                SELECT job_id, attempts, max_attempts
                FROM jobs
                WHERE status = 'running' AND lease_expires_at <= ?
                """,
                (now_iso,),
            ).fetchall()

            for row in stale_rows:
                jid = row["job_id"]
                att = row["attempts"]
                max_att = row["max_attempts"]
                if att >= max_att:
                    c.execute(
                        """
                        UPDATE jobs
                        SET status = 'failed',
                            lease_token = NULL,
                            lease_expires_at = NULL,
                            error_message = ?,
                            updated_at = ?
                        WHERE job_id = ?
                        """,
                        (f"Lease expired after {att} attempts (max {max_att})", now_iso, jid),
                    )
                    c.execute(
                        """
                        UPDATE job_runs
                        SET ended_at = ?,
                            final_status = 'failed',
                            error_message = ?
                        WHERE job_id = ? AND ended_at IS NULL
                        """,
                        (now_iso, f"Lease expired after {att} attempts", jid),
                    )
                else:
                    c.execute(
                        """
                        UPDATE jobs
                        SET status = 'queued',
                            lease_token = NULL,
                            lease_expires_at = NULL,
                            worker_id = NULL,
                            updated_at = ?
                        WHERE job_id = ?
                        """,
                        (now_iso, jid),
                    )
                    c.execute(
                        """
                        UPDATE job_runs
                        SET ended_at = ?,
                            final_status = 'expired',
                            error_message = 'Lease expired; requeued'
                        WHERE job_id = ? AND ended_at IS NULL
                        """,
                        (now_iso, jid),
                    )

            # 2. Find eligible queued candidate
            query = """
                SELECT * FROM jobs
                WHERE status = 'queued' AND cancellation_requested = 0
            """
            params: list[Any] = []
            if supported_types:
                placeholders = ",".join("?" for _ in supported_types)
                query += f" AND job_type IN ({placeholders})"
                params.extend(supported_types)

            query += " ORDER BY priority ASC, created_at ASC LIMIT 1"

            candidate = c.execute(query, tuple(params)).fetchone()
            if candidate is None:
                return None

            job_id = candidate["job_id"]
            new_attempts = candidate["attempts"] + 1
            fresh_lease_token = str(uuid.uuid4())

            # 3. Optimistic atomic update
            update_cur = c.execute(
                """
                UPDATE jobs
                SET status = 'running',
                    attempts = ?,
                    lease_token = ?,
                    lease_expires_at = ?,
                    worker_id = ?,
                    last_heartbeat_at = ?,
                    updated_at = ?
                WHERE job_id = ? AND status = 'queued' AND cancellation_requested = 0
                """,
                (
                    new_attempts,
                    fresh_lease_token,
                    lease_expires,
                    worker_id,
                    now_iso,
                    now_iso,
                    job_id,
                ),
            )

            if update_cur.rowcount != 1:
                return None

            # 4. Insert job_run
            run_id = str(uuid.uuid4())
            c.execute(
                """
                INSERT INTO job_runs (
                    run_id, job_id, attempt_number, worker_id, started_at,
                    ended_at, final_status, error_message
                ) VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL)
                """,
                (run_id, job_id, new_attempts, worker_id, now_iso),
            )

            updated_row = c.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            return self._row_to_job(updated_row)

    def heartbeat_job(
        self,
        job_id: str,
        worker_id: str,
        lease_token: str,
        extend_seconds: int = 60,
        conn: sqlite3.Connection | None = None,
    ) -> bool:
        """Extend lease expiration for a currently running job.

        Requires active lease (lease_expires_at > now_iso), matching worker_id, and matching lease token.
        Returns False if the lease has expired, the token is invalid, or the worker is wrong.
        """
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        new_expires = (now + timedelta(seconds=extend_seconds)).isoformat()

        with TransactionScope(self, conn) as c:
            cur = c.execute(
                """
                UPDATE jobs
                SET lease_expires_at = ?,
                    last_heartbeat_at = ?,
                    updated_at = ?
                WHERE job_id = ?
                  AND worker_id = ?
                  AND lease_token = ?
                  AND status = 'running'
                  AND lease_expires_at > ?
                """,
                (new_expires, now_iso, now_iso, job_id, worker_id, lease_token, now_iso),
            )
            return cur.rowcount == 1

    def complete_job(
        self,
        job_id: str,
        worker_id: str,
        lease_token: str,
        result_payload: dict[str, Any] | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> bool:
        """Mark a running job as completed with its final result payload.

        Fencing enforces matching worker_id, matching lease token, and active (unexpired) lease.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        res_str = (
            json.dumps(result_payload, ensure_ascii=False, default=str)
            if result_payload is not None
            else None
        )

        with TransactionScope(self, conn) as c:
            cur = c.execute(
                """
                UPDATE jobs
                SET status = 'completed',
                    lease_token = NULL,
                    lease_expires_at = NULL,
                    completed_at = ?,
                    updated_at = ?,
                    result_payload = ?
                WHERE job_id = ?
                  AND worker_id = ?
                  AND lease_token = ?
                  AND status = 'running'
                  AND lease_expires_at > ?
                """,
                (now_iso, now_iso, res_str, job_id, worker_id, lease_token, now_iso),
            )
            if cur.rowcount != 1:
                return False

            c.execute(
                """
                UPDATE job_runs
                SET ended_at = ?,
                    final_status = 'completed'
                WHERE job_id = ? AND worker_id = ? AND ended_at IS NULL
                """,
                (now_iso, job_id, worker_id),
            )
            return True

    def fail_job(
        self,
        job_id: str,
        worker_id: str,
        lease_token: str,
        error_message: str,
        conn: sqlite3.Connection | None = None,
    ) -> bool:
        """Mark a running job as failed with error details.

        Fencing enforces matching worker_id, matching lease token, and active (unexpired) lease.
        """
        now_iso = datetime.now(timezone.utc).isoformat()

        with TransactionScope(self, conn) as c:
            cur = c.execute(
                """
                UPDATE jobs
                SET status = 'failed',
                    lease_token = NULL,
                    lease_expires_at = NULL,
                    error_message = ?,
                    updated_at = ?
                WHERE job_id = ?
                  AND worker_id = ?
                  AND lease_token = ?
                  AND status = 'running'
                  AND lease_expires_at > ?
                """,
                (error_message, now_iso, job_id, worker_id, lease_token, now_iso),
            )
            if cur.rowcount != 1:
                return False

            c.execute(
                """
                UPDATE job_runs
                SET ended_at = ?,
                    final_status = 'failed',
                    error_message = ?
                WHERE job_id = ? AND worker_id = ? AND ended_at IS NULL
                """,
                (now_iso, error_message, job_id, worker_id),
            )
            return True

    def cancel_job(
        self,
        job_id: str,
        conn: sqlite3.Connection | None = None,
    ) -> bool:
        """Cancel a job.

        If queued: transitions immediately to 'cancelled'.
        If running: flags cancellation_requested=1 for cooperative worker cancellation.
        Returns False if job is already in terminal state or not found.
        """
        now_iso = datetime.now(timezone.utc).isoformat()

        with TransactionScope(self, conn) as c:
            row = c.execute("SELECT status FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if row is None:
                return False

            status = row["status"]
            if status == JobStatus.QUEUED.value:
                c.execute(
                    """
                    UPDATE jobs
                    SET status = 'cancelled',
                        cancellation_requested = 1,
                        updated_at = ?
                    WHERE job_id = ? AND status = 'queued'
                    """,
                    (now_iso, job_id),
                )
                return True
            elif status == JobStatus.RUNNING.value:
                c.execute(
                    """
                    UPDATE jobs
                    SET cancellation_requested = 1,
                        updated_at = ?
                    WHERE job_id = ? AND status = 'running'
                    """,
                    (now_iso, job_id),
                )
                return True
            else:
                return False

    def list_jobs(
        self,
        status: JobStatus | str | None = None,
        limit: int = 100,
        offset: int = 0,
        conn: sqlite3.Connection | None = None,
    ) -> list[JobRecord]:
        c = conn if conn is not None else self.get_connection()
        try:
            if status is not None:
                st = status.value if isinstance(status, JobStatus) else str(status)
                rows = c.execute(
                    "SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (st, limit, offset),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
            return [self._row_to_job(r) for r in rows]
        finally:
            if conn is None and self._conn_str != ":memory:":
                c.close()

    def get_job_runs(
        self,
        job_id: str,
        conn: sqlite3.Connection | None = None,
    ) -> list[JobRunRecord]:
        c = conn if conn is not None else self.get_connection()
        try:
            rows = c.execute(
                "SELECT * FROM job_runs WHERE job_id = ? ORDER BY attempt_number ASC",
                (job_id,),
            ).fetchall()
            return [
                JobRunRecord(
                    run_id=r["run_id"],
                    job_id=r["job_id"],
                    attempt_number=r["attempt_number"],
                    worker_id=r["worker_id"],
                    started_at=r["started_at"],
                    ended_at=r["ended_at"],
                    final_status=r["final_status"],
                    error_message=r["error_message"],
                )
                for r in rows
            ]
        finally:
            if conn is None and self._conn_str != ":memory:":
                c.close()

    def save_approval_record(
        self,
        approval: ApprovalRecord,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        """Persist human approval or rejection record with strict binding validation."""
        if approval.decision not in (ApprovalDecision.APPROVE, ApprovalDecision.REJECT):
            raise ValueError(
                f"Invalid approval decision '{approval.decision}'. Decision must be 'APPROVE' or 'REJECT'."
            )

        if not approval.has_complete_binding:
            missing: list[str] = []
            if not (approval.draft_id and str(approval.draft_id).strip()):
                missing.append("draft_id")
            if not (approval.prompt_version and str(approval.prompt_version).strip()):
                missing.append("prompt_version")
            if not (approval.claims_fingerprint and str(approval.claims_fingerprint).strip()):
                missing.append("claims_fingerprint")
            if not (approval.content_sha256 and str(approval.content_sha256).strip()):
                missing.append("content_sha256")
            if approval.job_attempt is None or approval.job_attempt < 1:
                missing.append("job_attempt")
            raise ValueError(
                f"New approval record rejected: missing or incomplete binding data: {', '.join(missing)}. "
                "New approvals must strictly bind to the exact draft and content being approved."
            )

        with TransactionScope(self, conn) as c:
            # Enforce target draft exists in content_drafts
            draft_row = c.execute(
                "SELECT id FROM content_drafts WHERE id = ? AND prompt_version = ?",
                (approval.draft_id, approval.prompt_version),
            ).fetchone()
            if draft_row is None:
                raise ValueError(
                    f"Referenced draft '{approval.draft_id}' version '{approval.prompt_version}' does not exist in content_drafts."
                )

            # Enforce at most one authoritative approval per job
            if approval.decision == ApprovalDecision.APPROVE:
                existing_approve = c.execute(
                    "SELECT approval_id FROM approval_records WHERE job_id = ? AND decision = 'APPROVE'",
                    (approval.job_id,),
                ).fetchone()
                if existing_approve is not None:
                    raise ValueError(
                        f"Duplicate authoritative approval rejected: job '{approval.job_id}' already has an approved record '{existing_approve['approval_id']}'."
                    )

            c.execute(
                """
                INSERT INTO approval_records (
                    approval_id, job_id, decision, reviewer, notes, reviewed_at,
                    draft_id, prompt_version, claims_fingerprint, content_sha256, job_attempt
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    approval.approval_id,
                    approval.job_id,
                    approval.decision,
                    approval.reviewer,
                    approval.notes,
                    approval.reviewed_at,
                    approval.draft_id,
                    approval.prompt_version,
                    approval.claims_fingerprint,
                    approval.content_sha256,
                    approval.job_attempt,
                ),
            )

    def get_approval_records(
        self,
        job_id: str,
        conn: sqlite3.Connection | None = None,
    ) -> list[ApprovalRecord]:
        c = conn if conn is not None else self.get_connection()
        try:
            rows = c.execute(
                "SELECT * FROM approval_records WHERE job_id = ? ORDER BY reviewed_at ASC",
                (job_id,),
            ).fetchall()
            records: list[ApprovalRecord] = []
            for r in rows:
                col_keys = r.keys() if hasattr(r, "keys") else []
                records.append(
                    ApprovalRecord(
                        approval_id=r["approval_id"],
                        job_id=r["job_id"],
                        decision=r["decision"],
                        reviewer=r["reviewer"],
                        notes=r["notes"],
                        reviewed_at=r["reviewed_at"],
                        draft_id=r["draft_id"] if "draft_id" in col_keys else None,
                        prompt_version=r["prompt_version"] if "prompt_version" in col_keys else None,
                        claims_fingerprint=r["claims_fingerprint"] if "claims_fingerprint" in col_keys else None,
                        content_sha256=r["content_sha256"] if "content_sha256" in col_keys else None,
                        job_attempt=r["job_attempt"] if "job_attempt" in col_keys else None,
                    )
                )
            return records
        finally:
            if conn is None and self._conn_str != ":memory:":
                c.close()

    def get_authoritative_approval(
        self,
        job_id: str,
        conn: sqlite3.Connection | None = None,
    ) -> ApprovalRecord | None:
        """Return the authoritative approval (decision == 'APPROVE') for a job, if one exists."""
        records = self.get_approval_records(job_id, conn=conn)
        approvals = [r for r in records if r.decision == ApprovalDecision.APPROVE]
        return approvals[0] if approvals else None

    def can_authorize_export(
        self,
        job_id: str,
        expected_draft_id: str,
        expected_prompt_version: str,
        expected_content_sha256: str | None = None,
        expected_claims_fingerprint: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> bool:
        """Verify whether an authoritative approval exists and is strictly bound to the requested content.

        Returns False if no approval exists, if decision != 'APPROVE', if binding data is missing/legacy,
        or if any binding field does not match expected values.
        """
        approval = self.get_authoritative_approval(job_id, conn=conn)
        if approval is None:
            return False
        return approval.is_valid_for_export(
            draft_id=expected_draft_id,
            prompt_version=expected_prompt_version,
            content_sha256=expected_content_sha256,
            claims_fingerprint=expected_claims_fingerprint,
        )

    def create_safe_database_backup(
        self,
        backup_dir: Path | str,
        backup_name: str | None = None,
    ) -> Path:
        """Create a safe, verified online backup using SQLite's backup API.

        Guarantees:
        1. Works safely with active SQLite WAL mode (no torn pages or file lock conflicts).
        2. Validates PRAGMA integrity_check == 'ok' before finalizing.
        3. Writes to a temporary staging file before atomically replacing/moving to the final destination.
        4. Cleans up temporary artifacts on failure.
        """
        dest_dir = Path(backup_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        if backup_name is None:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            backup_name = f"affiliate_factory_backup_{ts}.db"

        final_path = dest_dir / backup_name
        temp_path = dest_dir / f"{backup_name}.tmp_{uuid.uuid4().hex[:8]}"

        src_conn = self.get_connection()
        try:
            dst_conn = sqlite3.connect(str(temp_path), timeout=10.0)
            try:
                src_conn.backup(dst_conn, pages=-1)
                row = dst_conn.execute("PRAGMA integrity_check").fetchone()
                if not row or str(row[0]).lower() != "ok":
                    check_res = row[0] if row else "unknown"
                    raise RuntimeError(f"Database backup integrity check failed: {check_res}")
            finally:
                dst_conn.close()

            temp_path.replace(final_path)
            return final_path
        except Exception:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            raise
        finally:
            if self._conn_str != ":memory:":
                src_conn.close()


def create_safe_database_backup(
    db: Database,
    backup_dir: Path | str,
    backup_name: str | None = None,
) -> Path:
    """Module-level helper to create a safe online database backup."""
    return db.create_safe_database_backup(backup_dir, backup_name)
