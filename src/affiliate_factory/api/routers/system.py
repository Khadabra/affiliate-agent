"""System and telemetry endpoints for Phase 3.5.1."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, status

from affiliate_factory.api.config import APISettings
from affiliate_factory.api.dependencies import get_database, get_settings, get_telemetry_service
from affiliate_factory.api.telemetry import SystemTelemetry, TelemetryService
from affiliate_factory.db import Database

router = APIRouter(tags=["System"])


@router.get("/health", status_code=status.HTTP_200_OK)
def get_health(
    db: Database = Depends(get_database),
) -> dict[str, Any]:
    """Check API server health and database connectivity."""
    db_status = "connected"
    journal_mode = "unknown"
    try:
        journal_mode = db.get_journal_mode()
    except Exception as e:
        db_status = f"error: {e}"

    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": db_status,
        "journal_mode": journal_mode,
    }


@router.get("/api/v1/system/info", status_code=status.HTTP_200_OK)
def get_system_info(
    settings: APISettings = Depends(get_settings),
    db: Database = Depends(get_database),
) -> dict[str, Any]:
    """Basic application info and operational status."""
    return {
        "app_name": settings.app_name,
        "version": settings.version,
        "environment": "local",
        "host": settings.host,
        "port": settings.port,
        "database_journal_mode": db.get_journal_mode(),
        "worker_status": "idle_not_started",
        "api_cost_policy": "zero_mandatory_cost",
    }


@router.get("/api/v1/system/resources", response_model=SystemTelemetry)
def get_system_resources(
    telemetry: TelemetryService = Depends(get_telemetry_service),
) -> SystemTelemetry:
    """Hardware telemetry (CPU, RAM, GPU/VRAM, Disk) for the Resource Manager."""
    return telemetry.get_telemetry()
