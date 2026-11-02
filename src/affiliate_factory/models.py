"""Pydantic data contracts for AI Affiliate Content Factory.

Strict typing and minimal schemas for product intake, content drafting,
claims, compliance, performance recording, and event logging.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Product(BaseModel):
    """Product entity for affiliate marketing."""
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    url: str
    price: float | None = None
    price_observed_at: datetime | None = None
    source: Literal["manual", "official_api", "other"] = "manual"
    notes: str | None = None

    @field_validator("price")
    @classmethod
    def validate_price(cls, v: float | None) -> float | None:
        if v is not None and v < 0:
            raise ValueError("Price must be non-negative")
        return v

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("Product URL must start with http:// or https://")
        return v


class ContentDraft(BaseModel):
    """Draft content created for a product."""
    model_config = ConfigDict(extra="forbid")

    id: str
    product_id: str
    angle: str
    hook: str
    script: str
    caption: str
    cta: str
    disclosure_text: str
    status: Literal["draft", "checked", "waiting_approval", "approved", "posted", "measured", "rejected"] = "draft"
    prompt_version: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Claim(BaseModel):
    """Specific factual or promotional claim extracted from draft."""
    model_config = ConfigDict(extra="forbid")

    id: str
    draft_id: str
    prompt_version: str | None = None
    text: str
    source_ref: str | None = None
    verification_status: Literal["UNVERIFIED", "SOURCED", "VERIFIED", "REJECTED"] = "UNVERIFIED"


class ComplianceFinding(BaseModel):
    """Specific finding from a compliance check."""
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    severity: Literal["ERROR", "WARNING", "INFO"]
    message: str


class ComplianceReport(BaseModel):
    """Result of compliance rule evaluation on a ContentDraft."""
    model_config = ConfigDict(extra="forbid")

    draft_id: str
    prompt_version: str = "v1.0"
    passed: bool
    findings: list[ComplianceFinding] = Field(default_factory=list)


class PerformanceRecord(BaseModel):
    """Observed performance metrics for posted content.

    Unknown metrics MUST remain None (representing unknown/unmeasured),
    never defaulted to 0.
    """
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    content_id: str
    platform: str
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    views: int | None = None
    clicks: int | None = None
    orders: int | None = None
    commission_idr: float | None = None
    data_source: Literal["manual", "official_api"] = "manual"

    @field_validator("views", "clicks", "orders")
    @classmethod
    def validate_non_negative_int(cls, v: int | None, info) -> int | None:
        if v is not None and v < 0:
            raise ValueError(f"{info.field_name.capitalize()} must be non-negative")
        return v

    @field_validator("observed_at")
    @classmethod
    def validate_and_normalize_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)

    @field_validator("commission_idr")
    @classmethod
    def validate_non_negative_commission(cls, v: float | None) -> float | None:
        if v is not None:
            if math.isnan(v) or math.isinf(v):
                raise ValueError("Commission must be a finite number, not NaN or Infinity")
            if v < 0:
                raise ValueError("Commission must be non-negative")
        return v

    @field_validator("content_id", "platform")
    @classmethod
    def validate_non_empty_str(cls, v: str, info) -> str:
        if not v or not v.strip():
            raise ValueError(f"{info.field_name} must be a non-empty string")
        return v.strip()


class Event(BaseModel):
    """Append-only audit log entry for module execution."""
    model_config = ConfigDict(extra="forbid")

    id: str
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    run_id: str
    module: str
    action: str
    status: Literal["started", "succeeded", "failed", "waiting_approval"]
    ref_type: str
    ref_id: str
    note: str | None = None

class PerformanceSnapshotState(BaseModel):
    """Immutable state representation of a performance snapshot at a point in time."""
    model_config = ConfigDict(extra="forbid")

    id: str
    content_id: str
    platform: str
    observed_at: str
    views: int | None = None
    clicks: int | None = None
    orders: int | None = None
    commission_idr: float | None = None
    data_source: str


class PerformanceCorrectionPayload(BaseModel):
    """Structured audit payload for performance record corrections."""
    model_config = ConfigDict(extra="forbid")

    record_id: str
    reason: str
    before: PerformanceSnapshotState
    after: PerformanceSnapshotState
class AnglePerformanceMetrics(BaseModel):
    """Aggregated performance metrics for a specific content angle."""
    model_config = ConfigDict(extra="forbid")

    angle: str
    total_contents: int
    total_snapshots: int
    total_views: int | None = None
    total_clicks: int | None = None
    total_orders: int | None = None
    total_commission_idr: float | None = None
    views_known_count: int = 0
    views_unknown_count: int = 0
    clicks_known_count: int = 0
    clicks_unknown_count: int = 0
    orders_known_count: int = 0
    orders_unknown_count: int = 0
    commission_known_count: int = 0
    commission_unknown_count: int = 0
    ctr_cohort_count: int = 0
    ctr_views_cohort: int = 0
    ctr_clicks_cohort: int = 0
    ctr: float | None = None
    cr_cohort_count: int = 0
    cr_clicks_cohort: int = 0
    cr_orders_cohort: int = 0
    click_to_order: float | None = None
    confidence_label: Literal["BUKTI CUKUP", "BUKTI TERBATAS", "TIDAK ADA DATA"]
    data_quality_note: str


class AngleRankItem(BaseModel):
    """Ranked angle item with positional rank and metrics."""
    model_config = ConfigDict(extra="forbid")

    rank: int | None = None  # None for unranked (e.g. no performance data)
    metrics: AnglePerformanceMetrics


class UnmappedContentItem(BaseModel):
    """Details of a content item that could not be mapped to an angle."""
    model_config = ConfigDict(extra="forbid")

    content_id: str
    platform: str
    latest_snapshot_id: str | None = None
    reason: str  # e.g. "draft_not_found", "ambiguous_prompt_version"


class AngleRankReport(BaseModel):
    """Full ranking report across angles for a platform or filter window."""
    model_config = ConfigDict(extra="forbid")

    platform: str | None = None
    product_id: str | None = None
    min_samples: int
    sort_by: str
    total_independent_contents: int
    mapped_contents_count: int
    unmapped_contents_count: int
    ranked_angles: list[AngleRankItem] = Field(default_factory=list)
    unranked_angles: list[AngleRankItem] = Field(default_factory=list)
    unmapped_items: list[UnmappedContentItem] = Field(default_factory=list)
    is_cross_platform: bool = False


class CopywritingRecommendation(BaseModel):
    """Actionable recommendation for an angle or copywriting strategy."""
    model_config = ConfigDict(extra="forbid")

    category: Literal[
        "promote_tested_angle",
        "explore_insufficient_data",
        "funnel_gap_high_ctr_low_cr",
        "untested_angle",
        "data_hygiene",
    ]
    angle: str | None = None
    headline: str
    observation: str
    actionable_advice: str
    hypothesis_text_suggestions: list[str] = Field(default_factory=list)
    evidence_strength: Literal["BUKTI CUKUP", "BUKTI TERBATAS", "TIDAK ADA DATA"]


class CopywritingAdviceReport(BaseModel):
    """Complete copywriting advisory report generated from an AngleRankReport."""
    model_config = ConfigDict(extra="forbid")

    platform: str | None = None
    recommendations: list[CopywritingRecommendation] = Field(default_factory=list)
    disclaimers: list[str] = Field(default_factory=list)
