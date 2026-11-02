"""Product Intake Module.

Accepts manual product input, enforces unique product URL constraint,
and records price observation timestamp. Emits audit events.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from affiliate_factory.db import Database
from affiliate_factory.models import Event, Product


class IntakeError(Exception):
    """Raised when product intake encounters a business logic violation."""
    pass


def intake_product(
    db: Database,
    product: Product,
    run_id: str | None = None,
) -> tuple[Product, bool]:
    """Ingest a product into SQLite database.

    Returns:
        tuple[Product, bool]: (The product record, True if newly created, False if already existed).

    Emits append-only events for start and finish.
    """
    effective_run_id = run_id or str(uuid.uuid4())
    start_event = Event(
        id=str(uuid.uuid4()),
        ts=datetime.now(timezone.utc),
        run_id=effective_run_id,
        module="intake",
        action="intake_product",
        status="started",
        ref_type="product_url",
        ref_id=product.url,
        note=f"Starting intake for product: {product.name}",
    )
    db.append_event(start_event)

    existing = db.get_product_by_url(product.url)
    if existing:
        fail_event = Event(
            id=str(uuid.uuid4()),
            ts=datetime.now(timezone.utc),
            run_id=effective_run_id,
            module="intake",
            action="intake_product",
            status="succeeded",
            ref_type="product_id",
            ref_id=existing.id,
            note="Duplicate URL rejected; returning existing product record.",
        )
        db.append_event(fail_event)
        return existing, False

    # Insert new product
    inserted = db.insert_product(product)
    if not inserted:
        # Race condition or integrity conflict
        db.append_event(
            Event(
                id=str(uuid.uuid4()),
                ts=datetime.now(timezone.utc),
                run_id=effective_run_id,
                module="intake",
                action="intake_product",
                status="failed",
                ref_type="product_url",
                ref_id=product.url,
                note="Integrity error inserting product into database.",
            )
        )
        existing_after_race = db.get_product_by_url(product.url)
        if existing_after_race:
            return existing_after_race, False
        raise IntakeError(f"Failed to insert product with URL {product.url}")

    success_event = Event(
        id=str(uuid.uuid4()),
        ts=datetime.now(timezone.utc),
        run_id=effective_run_id,
        module="intake",
        action="intake_product",
        status="succeeded",
        ref_type="product_id",
        ref_id=product.id,
        note="Successfully inserted new product record.",
    )
    db.append_event(success_event)
    return product, True

