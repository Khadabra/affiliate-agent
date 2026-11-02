"""Human Review Gate Module.

Implements safe, deterministic review semantics for ContentDraft entities and individual Claims.
Enforces that approval can ONLY occur from 'waiting_approval' when compliance passed and every claim
has been explicitly reviewed by a human. Records all review decisions in the append-only event log.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from affiliate_factory.db import Database
from affiliate_factory.models import Claim, ContentDraft, Event


class ReviewError(Exception):
    """Raised when a review operation violates safety constraints or invalid state transitions."""
    pass


def review_claim(
    db: Database,
    claim_id: str,
    status: Literal["VERIFIED", "REJECTED"],
    reviewer_note: str | None = None,
    run_id: str | None = None,
) -> Claim:
    """Explicitly review an individual claim, setting status to VERIFIED or REJECTED.

    Emits an audit event.
    """
    effective_run_id = run_id or str(uuid.uuid4())
    if status not in ("VERIFIED", "REJECTED"):
        raise ReviewError(f"Invalid claim review status: '{status}'. Must be 'VERIFIED' or 'REJECTED'.")

    claim = db.get_claim(claim_id)
    if not claim:
        raise ReviewError(f"Claim with ID '{claim_id}' not found.")

    updated = db.update_claim_status(claim_id, status)
    if not updated:
        raise ReviewError(f"Failed to update claim '{claim_id}'.")

    # Record audit event
    db.append_event(
        Event(
            id=str(uuid.uuid4()),
            ts=datetime.now(timezone.utc),
            run_id=effective_run_id,
            module="review",
            action="review_claim",
            status="succeeded",
            ref_type="claim_id",
            ref_id=claim_id,
            note=f"Claim reviewed by human: {status}. Note: {reviewer_note.strip() if reviewer_note else 'None'}",
        )
    )

    claim.verification_status = status
    return claim


def approve_draft(
    db: Database,
    draft_id: str,
    prompt_version: str = "v1.0",
    reviewer_note: str | None = None,
    run_id: str | None = None,
) -> ContentDraft:
    """Approve a ContentDraft currently in 'waiting_approval'.

    Strict requirements:
    1. Draft must exist and currently be in 'waiting_approval' (if already 'approved', returns idempotently).
    2. Compliance report must exist, must have passed == True, and no ERROR findings.
    3. Every claim associated with the draft must be explicitly VERIFIED. SOURCED, UNVERIFIED, or REJECTED
       claims strictly block approval.
    """
    effective_run_id = run_id or str(uuid.uuid4())
    draft = db.get_draft(draft_id, prompt_version)
    if not draft:
        raise ReviewError(f"Draft '{draft_id}' (version {prompt_version}) not found in database.")

    # Idempotent re-approval check
    if draft.status == "approved":
        return draft

    if draft.status == "rejected":
        raise ReviewError(
            f"Cannot approve draft '{draft_id}' because it has been REJECTED. "
            f"Create a revised prompt version instead."
        )

    if draft.status != "waiting_approval":
        raise ReviewError(
            f"Cannot approve draft '{draft_id}' with status '{draft.status}'. "
            f"Only drafts in 'waiting_approval' may be approved."
        )

    # Compliance Gate
    comp_report = db.get_compliance_report(draft_id, prompt_version)
    if not comp_report:
        raise ReviewError(
            f"Cannot approve draft '{draft_id}': compliance report is missing. "
            f"Run pipeline first."
        )
    if not comp_report.passed or any(f.severity == "ERROR" for f in comp_report.findings):
        blocking_errors = [f.message for f in comp_report.findings if f.severity == "ERROR"]
        raise ReviewError(
            f"Cannot approve draft '{draft_id}': compliance evaluation failed. "
            f"Blocking findings: {blocking_errors}"
        )

    # Claims Gate: Every claim must be explicitly human-reviewed as VERIFIED
    claims = db.get_claims_for_draft(draft_id)
    if claims:
        unverified = [c for c in claims if c.verification_status == "UNVERIFIED"]
        if unverified:
            details = [f"{c.id}: '{c.text}'" for c in unverified]
            raise ReviewError(
                f"Cannot approve draft '{draft_id}': contains UNVERIFIED claim(s) lacking evidence: {details}. "
                f"Evidence must be provided or claims removed."
            )

        rejected_claims = [c for c in claims if c.verification_status == "REJECTED"]
        if rejected_claims:
            details = [f"{c.id}: '{c.text}'" for c in rejected_claims]
            raise ReviewError(
                f"Cannot approve draft '{draft_id}': contains REJECTED claim(s): {details}."
            )

        sourced_unreviewed = [c for c in claims if c.verification_status == "SOURCED"]
        if sourced_unreviewed:
            details = [f"{c.id}: '{c.text}' (Source: {c.source_ref})" for c in sourced_unreviewed]
            raise ReviewError(
                f"Cannot approve draft '{draft_id}': contains SOURCED claim(s) that have not been explicitly "
                f"human-verified: {details}. The human reviewer must inspect the source and run "
                f"'review claim --claim-id <id> --status VERIFIED'."
            )

    # Transition status
    db.update_draft_status(draft_id, prompt_version, "approved")
    draft.status = "approved"

    # Record audit event
    db.append_event(
        Event(
            id=str(uuid.uuid4()),
            ts=datetime.now(timezone.utc),
            run_id=effective_run_id,
            module="review",
            action="human_approve",
            status="succeeded",
            ref_type="draft_id",
            ref_id=draft_id,
            note=f"Draft approved by human reviewer. Note: {reviewer_note.strip() if reviewer_note else 'None'}",
        )
    )

    return draft


def reject_draft(
    db: Database,
    draft_id: str,
    reason: str,
    prompt_version: str = "v1.0",
    run_id: str | None = None,
) -> ContentDraft:
    """Reject a ContentDraft in 'waiting_approval', recording a mandatory non-empty reason.

    Emits an audit event.
    """
    effective_run_id = run_id or str(uuid.uuid4())
    if not reason or not reason.strip():
        raise ReviewError("A non-empty reason is required to reject a draft.")

    draft = db.get_draft(draft_id, prompt_version)
    if not draft:
        raise ReviewError(f"Draft '{draft_id}' (version {prompt_version}) not found in database.")

    # Idempotent re-rejection check
    if draft.status == "rejected":
        return draft

    if draft.status == "approved":
        raise ReviewError(
            f"Cannot reject draft '{draft_id}' because it has already been APPROVED. "
            f"Approved drafts cannot be retroactively rejected without audit override."
        )

    if draft.status != "waiting_approval":
        raise ReviewError(
            f"Cannot reject draft '{draft_id}' with status '{draft.status}'. "
            f"Only drafts in 'waiting_approval' may be rejected."
        )

    # Transition status
    db.update_draft_status(draft_id, prompt_version, "rejected")
    draft.status = "rejected"

    # Record audit event
    db.append_event(
        Event(
            id=str(uuid.uuid4()),
            ts=datetime.now(timezone.utc),
            run_id=effective_run_id,
            module="review",
            action="human_reject",
            status="succeeded",
            ref_type="draft_id",
            ref_id=draft_id,
            note=f"Draft rejected by human reviewer. Reason: {reason.strip()}",
        )
    )

    return draft
