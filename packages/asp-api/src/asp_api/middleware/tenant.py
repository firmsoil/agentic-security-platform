"""Tenant binding for the API surface.

Per ADR-0003, every request that touches the graph carries a tenant
context. In v0.1, the tenant comes from an ``X-Tenant-ID`` header. From
Phase 2 onward, JWT claims will replace the header.

The middleware runs before any router. It:

1. Reads ``X-Tenant-ID`` from the request, defaulting to ``"default"``
   for compatibility with single-tenant deployments where the header is
   typically not set by clients.
2. Validates the tenant identifier with the same character class the
   Neo4j adapter enforces. If the header is malformed, the request is
   rejected with 400 before any handler runs.
3. Stashes the validated tenant on ``request.state.tenant_id``.

Routers receive the tenant via the ``Depends(get_tenant_id)`` dependency.
There is no path by which a router can run without a tenant binding —
the dependency raises if the middleware did not set one.

Implementation note: ``BaseHTTPMiddleware.dispatch`` cannot rely on
FastAPI's HTTPException handler — exceptions raised here get wrapped as
500s. We return a JSONResponse directly for the malformed-header case.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.responses import Response

# Same pattern as the Neo4j adapter's _validate_tenant_id. Kept in sync
# deliberately — see ADR-0003 for the rationale (predictable identifiers
# in audit logs, OPA decisions, OTel traces).
_TENANT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

TENANT_HEADER = "X-Tenant-ID"
DEFAULT_TENANT_ID = "default"


class TenantBindingMiddleware(BaseHTTPMiddleware):
    """Binds a tenant_id to every request before routers run."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        raw = request.headers.get(TENANT_HEADER, DEFAULT_TENANT_ID)
        if not _TENANT_RE.match(raw):
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "detail": (
                        f"Invalid {TENANT_HEADER}: must match "
                        "^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$"
                    )
                },
            )
        request.state.tenant_id = raw
        return await call_next(request)


def get_tenant_id(request: Request) -> str:
    """FastAPI dependency that returns the tenant bound by the middleware.

    Raises 500 if called from a route the middleware did not cover. That
    should be impossible in practice — the middleware is registered
    globally — but the explicit raise turns "silently runs without a
    tenant" into "fails loudly" if the middleware is ever misconfigured.
    """
    tenant_id: str | None = getattr(request.state, "tenant_id", None)
    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Tenant binding missing — TenantBindingMiddleware not configured?",
        )
    return tenant_id
