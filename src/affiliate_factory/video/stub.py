"""Deferred Video Assembly Module Slot.

This module is a placeholder for future media assembly (FFmpeg libx264).
Currently deferred. Contains empty contracts only.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class VideoRenderRequest(BaseModel):
    """Empty contract placeholder for video render requests."""
    model_config = ConfigDict(extra="forbid")

    draft_id: str
    audio_path: str | None = None
    media_assets: list[str] = []


class VideoRenderResult(BaseModel):
    """Empty contract placeholder for video render results."""
    model_config = ConfigDict(extra="forbid")

    draft_id: str
    output_path: str | None = None
    status: str = "DEFERRED"


def render_video_stub(request: VideoRenderRequest) -> VideoRenderResult:
    """Stub function. Rendering is deferred in Phase 1."""
    raise NotImplementedError("Video assembly is DEFERRED in Phase 1.")
