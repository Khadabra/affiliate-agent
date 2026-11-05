"""Dependency injection providers for FastAPI."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from affiliate_factory.api.config import APISettings, get_api_settings
from affiliate_factory.api.telemetry import TelemetryService
from affiliate_factory.db import Database


@lru_cache(maxsize=1)
def get_settings() -> APISettings:
    """Return cached API settings."""
    return get_api_settings()


@lru_cache(maxsize=1)
def get_database() -> Database:
    """Return database instance initialized with settings."""
    settings = get_settings()
    return Database(settings.db_path)


@lru_cache(maxsize=1)
def get_telemetry_service() -> TelemetryService:
    """Return cached telemetry service."""
    settings = get_settings()
    return TelemetryService(
        target_path=settings.db_path.parent,
        cache_ttl_seconds=settings.telemetry_cache_seconds,
    )
