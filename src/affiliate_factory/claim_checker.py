"""Claim Checker Module (Rule-Based).

Evaluates a list of claims. If source_ref is missing or empty, marks verification_status
as UNVERIFIED. If valid source_ref exists, marks as SOURCED.
Emits audit events and persists claims to SQLite.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from affiliate_factory.db import Database
from affiliate_factory.models import Claim, Event


def check_claims(
    db: Database,
    claims: list[Claim],
    run_id: str | None = None,
) -> list[Claim]:
    """Evaluate verification status of claims based on presence of source_ref.

    Emits start and finish events.
    """
    effective_run_id = run_id or str(uuid.uuid4())
    ref_draft = claims[0].draft_id if claims else "none"

    start_event = Event(
        id=str(uuid.uuid4()),
        ts=datetime.now(timezone.utc),
        run_id=effective_run_id,
        module="claim_checker",
        action="check_claims",
        status="started",
        ref_type="draft_id",
        ref_id=ref_draft,
        note=f"Starting verification of {len(claims)} claims.",
    )
    db.append_event(start_event)

    updated_claims: list[Claim] = []
    for c in claims:
        # Check source_ref presence
        if not c.source_ref or not c.source_ref.strip():
            status = "UNVERIFIED"
        else:
            status = "SOURCED"

        evaluated = Claim(
            id=c.id,
            draft_id=c.draft_id,
            text=c.text,
            source_ref=c.source_ref,
            verification_status=status,
        )
        updated_claims.append(evaluated)

    db.save_claims(updated_claims)

    finish_event = Event(
        id=str(uuid.uuid4()),
        ts=datetime.now(timezone.utc),
        run_id=effective_run_id,
        module="claim_checker",
        action="check_claims",
        status="succeeded",
        ref_type="draft_id",
        ref_id=ref_draft,
        note=f"Completed verification of {len(updated_claims)} claims.",
    )
    db.append_event(finish_event)

    return updated_claims
