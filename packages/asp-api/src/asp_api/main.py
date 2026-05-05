"""FastAPI application factory.

The app is intentionally small in v0.1. It does three things:
  1. Load the ontology at startup (fails fast if bundled YAML is broken).
  2. Expose health and ontology endpoints — useful immediately.
  3. Expose stub security endpoints that return well-typed empty payloads —
     so the frontend contract is stable before detection logic lands.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from asp_api import __version__
from asp_api.config import get_settings
from asp_api.middleware.tenant import TenantBindingMiddleware
from asp_api.routers import health, ontology, security
from asp_core.graph import load_ontology

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    # Load ontology once at startup and stash on app.state.
    app.state.ontology = load_ontology(settings.asp_ontology_version)
    app.state.settings = settings
    yield
    # Nothing to tear down in v0.1.


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Agentic Security Platform",
        description="Graph-native, agentic security for AI-native applications",
        version=__version__,
        lifespan=lifespan,
    )
    # Middleware execution order in Starlette is LIFO: the last add_middleware
    # call is the outermost wrapper. We want CORS to be outermost so preflight
    # OPTIONS requests don't trip the tenant binding. Therefore tenant first,
    # CORS last.
    app.add_middleware(TenantBindingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(ontology.router, prefix="/api")
    app.include_router(security.router, prefix="/api/security")
    return app


app = create_app()
