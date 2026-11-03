"""Deterministic specialist agents for Phase 3.3.

These agents operate only on caller-provided, curated data. They do not browse,
scrape, call paid APIs, or treat model output as independent evidence.
"""

from __future__ import annotations

import re
from pathlib import Path

from affiliate_factory.agent import BaseAgent
from affiliate_factory.agent_context import ExecutionContext
from affiliate_factory.agent_contracts import AgentMetadata
from affiliate_factory.agent_registry import AgentRegistry
from affiliate_factory.analytics import calculate_performance_summary
from affiliate_factory.compliance import check_compliance
from affiliate_factory.exporter import export_content_pack
from affiliate_factory.intake import intake_product
from affiliate_factory.models import Claim, ContentDraft
from affiliate_factory.review import approve_draft, review_claim
from affiliate_factory.specialist_contracts import (
    AnalyticsInput,
    AnalyticsItem,
    AnalyticsOutput,
    AnalyticsRates,
    ComplianceInput,
    ComplianceOutput,
    ContentWriterInput,
    ContentWriterOutput,
    FactCheckFinding,
    FactCheckerInput,
    FactCheckerOutput,
    HumanApprovalInput,
    HumanApprovalOutput,
    ResearchFact,
    ResearchInput,
    ResearchOutput,
    SpecialistExportInput,
    SpecialistExportOutput,
)
from affiliate_factory.workflow_contracts import WorkflowDefinition, WorkflowStep


def _normalize(value: str) -> str:
    return " ".join(value.lower().split())


class ResearchAgent(BaseAgent[ResearchInput, ResearchOutput]):
    input_model = ResearchInput
    output_model = ResearchOutput
    metadata = AgentMetadata(
        agent_id="specialist.research",
        name="Product Research Agent",
        version="1.0.0",
        description="Processes manually curated product research without external browsing.",
        capabilities=["product-research", "provenance", "manual-research"],
    )

    def execute(self, input_data: ResearchInput, context: ExecutionContext) -> ResearchOutput:
        ingested_product, _ = intake_product(context.db, input_data.product)
        evidence_by_id = {item.evidence_id: item for item in input_data.evidence}
        facts: list[ResearchFact] = []
        unsupported_claims: list[str] = []
        for fact in input_data.facts:
            linked = [evidence_by_id[item] for item in fact.evidence_ids if item in evidence_by_id]
            statuses = [item.status for item in linked]
            if not fact.evidence_ids:
                classification = "UNSUPPORTED"
                unsupported_claims.append(fact.text)
            elif len(linked) != len(fact.evidence_ids):
                classification = "MISSING"
            elif statuses and all(status == "VERIFIED" for status in statuses):
                classification = "SUPPORTED"
            else:
                classification = "MISSING"
            facts.append(
                ResearchFact(
                    fact_id=fact.fact_id,
                    text=fact.text,
                    evidence_ids=fact.evidence_ids,
                    classification=classification,
                    evidence_statuses=statuses,
                )
            )

        missing = list(input_data.missing_information)
        if not input_data.target_audience:
            missing.append("target_audience")
        if not input_data.customer_problems:
            missing.append("customer_problems")
        if not input_data.facts:
            missing.append("verified_product_facts")
        if not input_data.evidence:
            missing.append("source_evidence")

        return ResearchOutput(
            product=ingested_product,
            target_audience=input_data.target_audience,
            customer_problems=list(dict.fromkeys(input_data.customer_problems)),
            facts=facts,
            evidence=input_data.evidence,
            unsupported_claims=list(dict.fromkeys(unsupported_claims)),
            missing_information=list(dict.fromkeys(missing)),
            provenance_note=(
                "Input manual/curated; agent tidak melakukan browsing, scraping, atau verifikasi eksternal. "
                "Status evidence dipertahankan apa adanya."
            ),
        )


class ContentWriterAgent(BaseAgent[ContentWriterInput, ContentWriterOutput]):
    input_model = ContentWriterInput
    output_model = ContentWriterOutput
    metadata = AgentMetadata(
        agent_id="specialist.content-writer",
        name="Content Writer Agent",
        version="1.0.0",
        description="Creates deterministic original affiliate content from research evidence.",
        capabilities=["content-writing", "hooks", "affiliate-copy"],
    )

    def execute(self, input_data: ContentWriterInput, context: ExecutionContext) -> ContentWriterOutput:
        supported_facts = [fact for fact in input_data.research.facts if fact.classification == "SUPPORTED"]
        problems = input_data.research.customer_problems
        problem = problems[0] if problems else "Kebutuhan produk belum dirumuskan"
        hook = f"Masih mencari solusi untuk {problem.lower()}?"
        if supported_facts:
            benefit_text = " ".join(f"{fact.text}." for fact in supported_facts)
        else:
            benefit_text = "Belum ada fakta produk terverifikasi yang dapat digunakan dalam naskah."
        script = f"{hook} {benefit_text} Periksa detail produk dan sesuaikan dengan kebutuhanmu."
        claims = [
            Claim(
                id=f"{input_data.draft_id}_claim_{index + 1}",
                draft_id=input_data.draft_id,
                prompt_version="v1.0",
                text=fact.text,
                source_ref=(
                    next(
                        (
                            evidence.source_ref
                            for evidence in input_data.research.evidence
                            if evidence.evidence_id in fact.evidence_ids and evidence.source_ref
                        ),
                        None,
                    )
                ),
                verification_status="UNVERIFIED",
            )
            for index, fact in enumerate(supported_facts)
        ]
        draft = ContentDraft(
            id=input_data.draft_id,
            product_id=input_data.research.product.id,
            angle=input_data.angle or "Evidence-led",
            hook=hook,
            script=script,
            caption=f"{benefit_text} #ShopeeAffiliate #KontenAI",
            cta="Lihat detail produk sebelum mengambil keputusan.",
            disclosure_text="#ShopeeAffiliate #KontenAI",
            status="draft",
            prompt_version="v1.0",
        )
        # Persist only the draft and claim records. Approval remains a later
        # explicit human action through the existing review gate.
        context.db.upsert_draft(draft)
        context.db.save_claims(claims)
        return ContentWriterOutput(
            product_id=input_data.research.product.id,
            platform=input_data.platform,
            content_format=input_data.content_format,
            draft=draft,
            claims=claims,
            claim_ids=[claim.id for claim in claims],
            used_fact_ids=[fact.fact_id for fact in supported_facts],
            generation_note="Deterministic original draft; no seller/creator media was copied.",
        )


class FactCheckerAgent(BaseAgent[FactCheckerInput, FactCheckerOutput]):
    input_model = FactCheckerInput
    output_model = FactCheckerOutput
    metadata = AgentMetadata(
        agent_id="specialist.fact-checker",
        name="Fact Checker Agent",
        version="1.0.0",
        description="Matches generated claims against supplied research evidence only.",
        capabilities=["fact-checking", "claim-classification", "evidence-matching"],
    )

    def execute(self, input_data: FactCheckerInput, context: ExecutionContext) -> FactCheckerOutput:
        evidence_by_id = {item.evidence_id: item for item in input_data.research.evidence}
        facts_by_text = {_normalize(fact.text): fact for fact in input_data.research.facts}
        findings: list[FactCheckFinding] = []
        for claim in input_data.claims:
            normalized_claim = _normalize(claim.text)
            fact = facts_by_text.get(normalized_claim)
            if fact is None:
                classification = "UNSUPPORTED"
                rationale = "Klaim tidak ditemukan pada research facts yang diberikan."
                evidence_ids: list[str] = []
            else:
                evidence_ids = list(fact.evidence_ids)
                linked = [evidence_by_id[item] for item in evidence_ids if item in evidence_by_id]
                if claim.source_ref and not any(item.source_ref == claim.source_ref for item in linked):
                    classification = "CONTRADICTED"
                    rationale = "Rujukan klaim tidak cocok dengan provenance evidence yang tersedia."
                elif fact.classification == "UNSUPPORTED":
                    classification = "UNSUPPORTED"
                    rationale = "Research fact ditandai unsupported dan tidak boleh dipromosikan sebagai fakta."
                elif fact.classification == "CONTRADICTED":
                    classification = "CONTRADICTED"
                    rationale = "Research fact ditandai contradicted."
                elif fact.classification == "SUPPORTED" and linked and all(item.status == "VERIFIED" for item in linked):
                    classification = "SUPPORTED"
                    rationale = "Teks klaim cocok persis dengan fact yang memiliki evidence VERIFIED."
                else:
                    classification = "NEEDS_MANUAL_VERIFICATION"
                    rationale = "Kecocokan ada, tetapi evidence belum berstatus VERIFIED oleh manusia."
            findings.append(
                FactCheckFinding(
                    claim_id=claim.id,
                    claim_text=claim.text,
                    classification=classification,
                    evidence_ids=evidence_ids,
                    source_refs=[
                        item.source_ref
                        for item in (evidence_by_id[evidence_id] for evidence_id in evidence_ids if evidence_id in evidence_by_id)
                        if item.source_ref
                    ],
                    rationale=rationale,
                )
            )
        return FactCheckerOutput(
            draft_id=input_data.draft.id,
            findings=findings,
            supported_count=sum(item.classification == "SUPPORTED" for item in findings),
            unsupported_count=sum(item.classification in {"UNSUPPORTED", "CONTRADICTED"} for item in findings),
            manual_verification_count=sum(
                item.classification == "NEEDS_MANUAL_VERIFICATION" for item in findings
            ),
            note="Klasifikasi deterministik; hasil AI/manual tidak diperlakukan sebagai bukti independen.",
        )


class ComplianceAgent(BaseAgent[ComplianceInput, ComplianceOutput]):
    input_model = ComplianceInput
    output_model = ComplianceOutput
    metadata = AgentMetadata(
        agent_id="specialist.compliance",
        name="Compliance Agent",
        version="1.0.0",
        description="Reuses the existing fail-closed deterministic compliance engine.",
        capabilities=["compliance", "disclosure", "policy-checking"],
    )

    def execute(self, input_data: ComplianceInput, context: ExecutionContext) -> ComplianceOutput:
        report = check_compliance(
            db=context.db,
            draft=input_data.draft,
            product=input_data.product,
            config_path=input_data.config_path,
        )
        next_status = "waiting_approval" if report.passed else "rejected"
        context.db.update_draft_status(input_data.draft.id, input_data.draft.prompt_version, next_status)
        blocking = [item.message for item in report.findings if item.severity == "ERROR"]
        return ComplianceOutput(
            draft_id=input_data.draft.id,
            report=report,
            passed=report.passed,
            blocking_findings=blocking,
        )


class HumanApprovalGateAgent(BaseAgent[HumanApprovalInput, HumanApprovalOutput]):
    input_model = HumanApprovalInput
    output_model = HumanApprovalOutput
    metadata = AgentMetadata(
        agent_id="specialist.human-approval-gate",
        name="Human Approval Gate",
        version="1.0.0",
        description="Creates an explicit approval pause and never approves automatically.",
        capabilities=["human-approval", "review-gate"],
    )

    def execute(self, input_data: HumanApprovalInput, context: ExecutionContext) -> HumanApprovalOutput:
        if not input_data.compliance_passed:
            raise ValueError("Human approval cannot be requested for a compliance-failed draft")
        return HumanApprovalOutput(
            draft_id=input_data.draft_id,
            status="WAITING_APPROVAL",
            claim_ids=input_data.claim_ids,
            note="Menunggu keputusan manusia eksplisit APPROVE atau REJECT.",
        )


class ExportAgent(BaseAgent[SpecialistExportInput, SpecialistExportOutput]):
    input_model = SpecialistExportInput
    output_model = SpecialistExportOutput
    metadata = AgentMetadata(
        agent_id="specialist.export",
        name="Approved Content Export Agent",
        version="1.0.0",
        description="Applies explicit human claim decisions and delegates to the existing safe exporter.",
        capabilities=["manual-export", "approved-content-export"],
    )

    def execute(self, input_data: SpecialistExportInput, context: ExecutionContext) -> SpecialistExportOutput:
        for claim_id in input_data.human_verified_claim_ids:
            review_claim(
                context.db,
                claim_id,
                "VERIFIED",
                reviewer_note=input_data.reviewer_note,
                expected_prompt_version=input_data.prompt_version,
            )
        approve_draft(
            context.db,
            input_data.draft_id,
            prompt_version=input_data.prompt_version,
            reviewer_note=input_data.reviewer_note,
        )
        export_path = export_content_pack(
            context.db,
            input_data.draft_id,
            prompt_version=input_data.prompt_version,
            base_output_dir=Path(input_data.output_dir),
        )
        return SpecialistExportOutput(
            draft_id=input_data.draft_id,
            export_path=str(export_path),
            exported_files=sorted(item.name for item in export_path.iterdir() if item.is_file()),
            human_approval_required=True,
        )


class AnalyticsAgent(BaseAgent[AnalyticsInput, AnalyticsOutput]):
    input_model = AnalyticsInput
    output_model = AnalyticsOutput
    metadata = AgentMetadata(
        agent_id="specialist.analytics",
        name="Analytics Agent",
        version="1.0.0",
        description="Summarizes supplied performance snapshots without inventing missing metrics.",
        capabilities=["analytics", "performance-summary", "conversion-metrics"],
    )

    def execute(self, input_data: AnalyticsInput, context: ExecutionContext) -> AnalyticsOutput:
        records = [
            record
            for record in input_data.records
            if input_data.platform is None or record.platform == input_data.platform
        ]
        summary = calculate_performance_summary(records)
        notes: list[str] = []
        if not records:
            notes.append("Tidak ada snapshot performa yang tersedia untuk filter ini.")
        if summary.views_unknown_count:
            notes.append(f"{summary.views_unknown_count} item tidak memiliki views terukur.")
        if summary.clicks_unknown_count:
            notes.append(f"{summary.clicks_unknown_count} item tidak memiliki clicks terukur.")
        if summary.orders_unknown_count:
            notes.append(f"{summary.orders_unknown_count} item tidak memiliki orders terukur.")
        recommendations = [
            "Gunakan data sebagai observasi deskriptif; korelasi tidak membuktikan kausalitas."
        ]
        if summary.aggregate_rates.ctr is None:
            recommendations.append("Tambahkan views dan clicks lengkap sebelum menilai CTR.")
        if summary.aggregate_rates.click_to_order is None:
            recommendations.append("Tambahkan clicks dan orders lengkap sebelum menilai conversion.")
        return AnalyticsOutput(
            platform=input_data.platform,
            total_content_items=summary.total_content_items,
            total_snapshots=summary.total_snapshots,
            total_views=summary.total_views,
            total_clicks=summary.total_clicks,
            total_orders=summary.total_orders,
            total_commission_idr=summary.total_commission_idr,
            aggregate_rates=AnalyticsRates(
                ctr=summary.aggregate_rates.ctr,
                click_to_order=summary.aggregate_rates.click_to_order,
                commission_per_order=summary.aggregate_rates.commission_per_order,
                commission_per_click=summary.aggregate_rates.commission_per_click,
            ),
            items=[
                AnalyticsItem(
                    content_id=item.content_id,
                    platform=item.platform,
                    snapshot_count=item.snapshot_count,
                    views=item.views,
                    clicks=item.clicks,
                    orders=item.orders,
                    commission_idr=item.commission_idr,
                    rates=AnalyticsRates(
                        ctr=item.rates.ctr,
                        click_to_order=item.rates.click_to_order,
                        commission_per_order=item.rates.commission_per_order,
                        commission_per_click=item.rates.commission_per_click,
                    ),
                )
                for item in summary.items
            ],
            missing_data_notes=notes,
            recommendations=recommendations,
        )


def build_specialist_registry() -> AgentRegistry:
    """Return a registry containing deterministic Phase 3.3 agents."""
    registry = AgentRegistry()
    for agent in (
        ResearchAgent(),
        ContentWriterAgent(),
        FactCheckerAgent(),
        ComplianceAgent(),
        HumanApprovalGateAgent(),
        ExportAgent(),
        AnalyticsAgent(),
    ):
        registry.register(agent)
    return registry


def build_content_workflow(config_path: str = "config/compliance_rules.json") -> WorkflowDefinition:
    """Create Research → Writer → Fact Check → Compliance → Approval → Export."""
    return WorkflowDefinition(
        workflow_id="affiliate.content-generation",
        name="Affiliate Content Generation",
        description="Evidence-led content workflow with deterministic checks and human approval.",
        version="1.0.0",
        steps=[
            WorkflowStep(
                step_id="research",
                agent_id="specialist.research",
                input_mapping={
                    "product": "input.product",
                    "target_audience": "input.target_audience",
                    "customer_problems": "input.customer_problems",
                    "facts": "input.facts",
                    "evidence": "input.evidence",
                },
            ),
            WorkflowStep(
                step_id="writer",
                agent_id="specialist.content-writer",
                dependencies=["research"],
                input_data={"angle": None},
                input_mapping={
                    "draft_id": "input.draft_id",
                    "research": "steps.research.output",
                    "platform": "input.platform",
                    "content_format": "input.content_format",
                },
            ),
            WorkflowStep(
                step_id="fact-check",
                agent_id="specialist.fact-checker",
                dependencies=["writer"],
                input_mapping={
                    "research": "steps.research.output",
                    "draft": "steps.writer.output.draft",
                    "claims": "steps.writer.output.claims",
                },
            ),
            WorkflowStep(
                step_id="compliance",
                agent_id="specialist.compliance",
                dependencies=["fact-check"],
                input_data={"config_path": config_path},
                input_mapping={
                    "product": "steps.research.output.product",
                    "draft": "steps.writer.output.draft",
                },
            ),
            WorkflowStep(
                step_id="approval",
                agent_id="specialist.human-approval-gate",
                dependencies=["compliance"],
                requires_approval=True,
                input_mapping={
                    "draft_id": "steps.writer.output.draft.id",
                    "compliance_passed": "steps.compliance.output.passed",
                    "claim_ids": "steps.writer.output.claim_ids",
                },
            ),
            WorkflowStep(
                step_id="export",
                agent_id="specialist.export",
                dependencies=["approval"],
                input_mapping={
                    "draft_id": "steps.writer.output.draft.id",
                    "prompt_version": "steps.writer.output.draft.prompt_version",
                    "output_dir": "input.output_dir",
                    "approval_decision": "workflow.approval_decision",
                    "human_verified_claim_ids": "workflow.human_verified_claim_ids",
                    "reviewer_note": "workflow.reviewer_note",
                },
            ),
        ],
    )
