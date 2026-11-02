"""Compliance Checking Module.

Evaluates ContentDraft and Product against configurable rules from config/compliance_rules.json.
Emits audit events and records ComplianceReport.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from affiliate_factory.db import Database
from affiliate_factory.models import (
    ComplianceFinding,
    ComplianceReport,
    ContentDraft,
    Event,
    Product,
)

DEFAULT_CONFIG_PATH = Path("config") / "compliance_rules.json"


def load_compliance_rules(config_path: Path | str = DEFAULT_CONFIG_PATH) -> list[dict]:
    path = Path(config_path)
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("rules", [])


def check_compliance(
    db: Database,
    draft: ContentDraft,
    product: Product | None = None,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    run_id: str | None = None,
) -> ComplianceReport:
    """Run compliance checks on ContentDraft against rules configuration.

    Emits start and finish events.
    """
    effective_run_id = run_id or str(uuid.uuid4())
    start_event = Event(
        id=str(uuid.uuid4()),
        ts=datetime.now(timezone.utc),
        run_id=effective_run_id,
        module="compliance",
        action="check_compliance",
        status="started",
        ref_type="draft_id",
        ref_id=draft.id,
        note=f"Starting compliance evaluation for draft {draft.id}",
    )
    db.append_event(start_event)

    rules = load_compliance_rules(config_path)
    findings: list[ComplianceFinding] = []

    combined_text = f"{draft.hook} {draft.script} {draft.caption} {draft.cta} {draft.disclosure_text}".lower()

    for rule in rules:
        rule_id = rule.get("rule_id", "UNKNOWN_RULE")
        severity = rule.get("severity", "ERROR")
        check_type = rule.get("check_type")

        if check_type == "mandatory_text":
            keywords = [k.lower() for k in rule.get("required_keywords", [])]
            # Check disclosure_text specifically or combined text
            disclosure_content = f"{draft.disclosure_text} {draft.caption}".lower()
            if not any(k in disclosure_content for k in keywords):
                findings.append(
                    ComplianceFinding(
                        rule_id=rule_id,
                        severity=severity,
                        message=f"Konten wajib mencantumkan disclosure afiliasi yang sah (contoh: {keywords[:2]}).",
                    )
                )

        elif check_type == "mandatory_ai_label":
            keywords = [k.lower() for k in rule.get("required_keywords", [])]
            # If draft indicates it was produced with an AI prompt_version
            if draft.prompt_version and draft.prompt_version.lower() != "manual":
                if not any(k in combined_text for k in keywords):
                    findings.append(
                        ComplianceFinding(
                            rule_id=rule_id,
                            severity=severity,
                            message="Konten yang dibuat/diedit dengan AI wajib menyertakan label AI.",
                        )
                    )

        elif check_type == "prohibited_terms":
            prohibited = [p.lower() for p in rule.get("prohibited_terms", [])]
            for term in prohibited:
                if term in combined_text:
                    findings.append(
                        ComplianceFinding(
                            rule_id=rule_id,
                            severity=severity,
                            message=f"Ditemukan klaim terlarang '{term}'. {rule.get('reason', '')}",
                        )
                    )

        elif check_type == "prohibited_categories":
            prohibited = [p.lower() for p in rule.get("prohibited_terms", [])]
            prod_text = f"{product.name if product else ''} {product.notes if product else ''} {combined_text}".lower()
            for term in prohibited:
                if term in prod_text:
                    findings.append(
                        ComplianceFinding(
                            rule_id=rule_id,
                            severity=severity,
                            message=f"Produk/konten terindikasi masuk kategori terlarang '{term}'.",
                        )
                    )

        elif check_type == "price_date_required":
            if product and product.price is not None:
                if product.price_observed_at is None:
                    findings.append(
                        ComplianceFinding(
                            rule_id=rule_id,
                            severity=severity,
                            message="Harga produk wajib memiliki tanggal observasi (price_observed_at).",
                        )
                    )

    has_errors = any(f.severity == "ERROR" for f in findings)
    passed = not has_errors

    report = ComplianceReport(
        draft_id=draft.id,
        prompt_version=draft.prompt_version,
        passed=passed,
        findings=findings,
    )
    db.save_compliance_report(report)

    finish_event = Event(
        id=str(uuid.uuid4()),
        ts=datetime.now(timezone.utc),
        run_id=effective_run_id,
        module="compliance",
        action="check_compliance",
        status="succeeded" if passed else "failed",
        ref_type="draft_id",
        ref_id=draft.id,
        note=f"Compliance check finished. Passed: {passed}. Findings count: {len(findings)}",
    )
    db.append_event(finish_event)

    return report

