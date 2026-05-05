"""Liveness and readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    version: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    from asp_api import __version__

    return HealthResponse(status="ok", version=__version__)


@router.get("/ready", response_model=HealthResponse)
async def ready() -> HealthResponse:
    # v0.1: readiness == liveness. Once we depend on Neo4j at startup,
    # this will verify_connectivity before returning ok.
    from asp_api import __version__

    return HealthResponse(status="ok", version=__version__)
