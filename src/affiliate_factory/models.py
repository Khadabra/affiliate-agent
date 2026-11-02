"""Pydantic data contracts for AI Affiliate Content Factory.

Strict typing and minimal schemas for product intake, content drafting,
claims, compliance, performance recording, and event logging.
"""

from __future__ import annotations

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

    @field_validator("commission_idr")
    @classmethod
    def validate_non_negative_commission(cls, v: float | None) -> float | None:
        if v is not None and v < 0:
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

