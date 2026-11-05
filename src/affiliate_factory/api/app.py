"""FastAPI application factory for AI Affiliate Content Factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from affiliate_factory.api.config import APISettings, get_api_settings
from affiliate_factory.api.dependencies import get_database, get_telemetry_service
from affiliate_factory.api.routers import system

logger = logging.getLogger("affiliate_factory.api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application startup and shutdown lifecycle management."""
    settings: APISettings = getattr(app.state, "settings", get_api_settings())
    logger.info("Starting Affiliate Factory API Server on %s:%d", settings.host, settings.port)

    # Initialize database schema and verify WAL mode
    db = get_database()
    journal_mode = db.get_journal_mode()
    logger.info("Database initialized at %s with journal_mode=%s", settings.db_path, journal_mode)

    # Prime telemetry service
    telemetry = get_telemetry_service()
    initial_sample = telemetry.get_telemetry()
    logger.info(
        "Telemetry primed: CPU=%s cores, RAM=%s GB total, GPU=%s (available=%s)",
        initial_sample.cpu.logical_cores,
        initial_sample.memory.total_gb,
        initial_sample.gpu.name,
        initial_sample.gpu.available,
    )

    yield

    logger.info("Shutting down Affiliate Factory API Server")


def create_app(settings: APISettings | None = None) -> FastAPI:
    """Create and configure a local-only FastAPI application instance."""
    app_settings = settings or get_api_settings()

    app = FastAPI(
        title=app_settings.app_name,
        version=app_settings.version,
        description="Local Web Application Backend for AI Affiliate Content Factory",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.state.settings = app_settings

    # Strict local CORS policy
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    # Global error handler for unhandled exceptions
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled error on %s: %s", request.url.path, exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error": "InternalServerError",
                "message": "An unexpected server error occurred.",
                "path": request.url.path,
            },
        )

    # Register Routers
    app.include_router(system.router)

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    settings = get_api_settings()
    uvicorn.run(
        "affiliate_factory.api.app:app",
        host="127.0.0.1",  # Strict local binding
        port=settings.port,
        reload=False,
    )
