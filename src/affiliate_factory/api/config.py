"""API configuration settings."""

from __future__ import annotations

import os
from pathlib import Path
from pydantic import BaseModel, Field


class APISettings(BaseModel):
    """Local-only API server configuration."""

    app_name: str = "AI Affiliate Content Factory"
    version: str = "1.0.0"
    host: str = Field(default="127.0.0.1", description="Strict local binding")
    port: int = Field(default=8000, description="Server port")
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:4173",
            "http://localhost:4173",
        ],
        description="Allowed local frontend origins",
    )
    db_path: Path = Field(
        default_factory=lambda: Path("data") / "affiliate_factory.db"
    )
    telemetry_cache_seconds: float = 1.5


def get_api_settings() -> APISettings:
    """Load settings with optional environment overrides."""
    db_env = os.environ.get("AFFILIATE_DB_PATH")
    port_env = os.environ.get("AFFILIATE_API_PORT")

    db_path = Path(db_env) if db_env else Path("data") / "affiliate_factory.db"
    port = int(port_env) if port_env and port_env.isdigit() else 8000

    return APISettings(
        host="127.0.0.1",  # Non-negotiable local invariant
        port=port,
        db_path=db_path,
    )
