"""Typed contracts shared by the deterministic Phase 3.3 specialist agents."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from affiliate_factory.models import Claim, ComplianceReport, ContentDraft, PerformanceRecord, Product


EvidenceStatus = Literal["VERIFIED", "DOCUMENTATION_ONLY", "NOT_VERIFIED", "MANUAL_INPUT"]
FactClassification = Literal["SUPPORTED", "UNSUPPORTED", "CONTRADICTED", "MISSING"]
FactCheckClassification = Literal[
    "SUPPORTED",
    "UNSUPPORTED",
    "CONTRADICTED",
    "NEEDS_MANUAL_VERIFICATION",
]


def _clean_text(value: str) -> str:
    if not value.strip():
        raise ValueError("Text values must not be empty")
    return value.strip()


class ResearchEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    source_ref: str | None = None
    quote: str
    status: EvidenceStatus

    _validate_evidence_id = field_validator("evidence_id", mode="before")(_clean_text)
    _validate_quote = field_validator("quote", mode="before")(_clean_text)


class ResearchFactInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_id: str
    text: str
    evidence_ids: list[str] = Field(default_factory=list)

    _validate_fact_id = field_validator("fact_id", mode="before")(_clean_text)
    _validate_text = field_validator("text", mode="before")(_clean_text)


class ResearchFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_id: str
    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    classification: FactClassification
    evidence_statuses: list[EvidenceStatus] = Field(default_factory=list)


class ResearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product: Product
    target_audience: str | None = None
    customer_problems: list[str] = Field(default_factory=list)
    facts: list[ResearchFactInput] = Field(default_factory=list)
    evidence: list[ResearchEvidence] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)

    @field_validator("target_audience")
    @classmethod
    def validate_target_audience(cls, value: str | None) -> str | None:
        return value.strip() if value is not None and value.strip() else None

    @field_validator("customer_problems", "missing_information")
    @classmethod
    def clean_lists(cls, values: list[str]) -> list[str]:
        return [value.strip() for value in values if value.strip()]


class ResearchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product: Product
    target_audience: str | None = None
    customer_problems: list[str] = Field(default_factory=list)
    facts: list[ResearchFact] = Field(default_factory=list)
    evidence: list[ResearchEvidence] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    provenance_note: str


class ContentWriterInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str
    research: ResearchOutput
    platform: Literal["TikTok", "Instagram"]
    content_format: Literal["short_video", "reel", "carousel"] = "short_video"
    angle: str | None = None


class ContentWriterOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str
    platform: Literal["TikTok", "Instagram"]
    content_format: Literal["short_video", "reel", "carousel"]
    draft: ContentDraft
    claims: list[Claim] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    used_fact_ids: list[str] = Field(default_factory=list)
    generation_note: str


class FactCheckerInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    research: ResearchOutput
    draft: ContentDraft
    claims: list[Claim] = Field(default_factory=list)


class FactCheckFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    claim_text: str
    classification: FactCheckClassification
    evidence_ids: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    rationale: str


class FactCheckerOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str
    findings: list[FactCheckFinding] = Field(default_factory=list)
    supported_count: int = 0
    unsupported_count: int = 0
    manual_verification_count: int = 0
    note: str


class ComplianceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product: Product
    draft: ContentDraft
    config_path: str = "config/compliance_rules.json"


class ComplianceOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str
    report: ComplianceReport
    passed: bool
    blocking_findings: list[str] = Field(default_factory=list)


class HumanApprovalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str
    compliance_passed: bool
    claim_ids: list[str] = Field(default_factory=list)


class HumanApprovalOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str
    status: Literal["WAITING_APPROVAL"]
    required_action: Literal["APPROVE", "REJECT"] = "APPROVE"
    claim_ids: list[str] = Field(default_factory=list)
    note: str


class SpecialistExportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str
    prompt_version: str = "v1.0"
    output_dir: str
    approval_decision: Literal["APPROVE"]
    human_verified_claim_ids: list[str] = Field(default_factory=list)
    reviewer_note: str | None = None


class SpecialistExportOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str
    export_path: str
    exported_files: list[str] = Field(default_factory=list)
    human_approval_required: bool = True


class AnalyticsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    records: list[PerformanceRecord] = Field(default_factory=list)
    platform: str | None = None


class AnalyticsRates(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ctr: float | None = None
    click_to_order: float | None = None
    commission_per_order: float | None = None
    commission_per_click: float | None = None


class AnalyticsItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_id: str
    platform: str
    snapshot_count: int
    views: int | None = None
    clicks: int | None = None
    orders: int | None = None
    commission_idr: float | None = None
    rates: AnalyticsRates


class AnalyticsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: str | None = None
    total_content_items: int
    total_snapshots: int
    total_views: int | None = None
    total_clicks: int | None = None
    total_orders: int | None = None
    total_commission_idr: float | None = None
    aggregate_rates: AnalyticsRates
    items: list[AnalyticsItem] = Field(default_factory=list)
    missing_data_notes: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
