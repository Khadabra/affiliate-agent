"""Sequential Pipeline Orchestrator.

Calls modular steps (Intake, Compliance, Claim Checker) in sequence,
updates ContentDraft lifecycle status, and STOPS at 'waiting_approval'.
NO MODULE IS PERMITTED TO SELF-APPROVE.
All state is persisted in SQLite with audit events.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from affiliate_factory.claim_checker import check_claims
from affiliate_factory.compliance import check_compliance
from affiliate_factory.db import Database
from affiliate_factory.intake import intake_product
from affiliate_factory.models import (
    Claim,
    ComplianceReport,
    ContentDraft,
    Event,
    Product,
)


class OrchestrationResult:
    """Encapsulates the result of an orchestration run."""

    def __init__(
        self,
        run_id: str,
        product: Product,
        draft: ContentDraft,
        compliance_report: ComplianceReport,
        claims: list[Claim],
    ) -> None:
        self.run_id = run_id
        self.product = product
        self.draft = draft
        self.compliance_report = compliance_report
        self.claims = claims


def run_pipeline(
    db: Database,
    product: Product,
    draft: ContentDraft,
    claims: list[Claim] | None = None,
    config_path: Path | str = Path("config") / "compliance_rules.json",
    run_id: str | None = None,
) -> OrchestrationResult:
    """Execute sequential pipeline on product and draft.

    Enforces that pipeline halts at 'waiting_approval' when compliant.
    Self-approval is strictly forbidden.
    """
    effective_run_id = run_id or str(uuid.uuid4())

    # 1. Orchestrator Start Event
    db.append_event(
        Event(
            id=str(uuid.uuid4()),
            ts=datetime.now(timezone.utc),
            run_id=effective_run_id,
            module="orchestrator",
            action="run_pipeline",
            status="started",
            ref_type="draft_id",
            ref_id=draft.id,
            note=f"Starting sequential pipeline run for draft {draft.id}",
        )
    )

    # 2. Intake Product (idempotent: does not duplicate on existing URL)
    ingested_product, _ = intake_product(db, product, run_id=effective_run_id)

    # 3. Upsert Draft Initial State
    db.upsert_draft(draft)

    # 4. Compliance Check
    comp_report = check_compliance(
        db=db,
        draft=draft,
        product=ingested_product,
        config_path=config_path,
        run_id=effective_run_id,
    )

    # 5. Claim Check
    evaluated_claims: list[Claim] = []
    if claims:
        evaluated_claims = check_claims(db, claims, run_id=effective_run_id)

    # 6. Determine Next State
    # Note: If compliant, draft transitions to 'waiting_approval' and STOPS.
    # No module or agent may transition it to 'approved'.
    if comp_report.passed:
        final_status = "waiting_approval"
    else:
        final_status = "rejected"

    db.update_draft_status(draft.id, draft.prompt_version, final_status)
    draft.status = final_status

    # 7. Orchestrator Finish Event
    db.append_event(
        Event(
            id=str(uuid.uuid4()),
            ts=datetime.now(timezone.utc),
            run_id=effective_run_id,
            module="orchestrator",
            action="run_pipeline",
            status="waiting_approval" if comp_report.passed else "failed",
            ref_type="draft_id",
            ref_id=draft.id,
            note=f"Pipeline stopped at {final_status}. Human decision required.",
        )
    )

    return OrchestrationResult(
        run_id=effective_run_id,
        product=ingested_product,
        draft=draft,
        compliance_report=comp_report,
        claims=evaluated_claims,
    )
