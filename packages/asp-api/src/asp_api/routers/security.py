"""Security endpoints.

Attack paths are now read live from the seeded graph. Incidents and policy
remain lightweight contracts until their deeper implementations land.
"""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from asp_adapters.graph import Neo4jConfig, Neo4jGraphStore
from asp_api.middleware.tenant import get_tenant_id
from asp_core.graph import (
    AttackPath,
    Ontology,
    find_memory_poisoning_paths,
    find_prompt_injection_paths,
    find_tool_abuse_paths,
)

router = APIRouter(tags=["security"])
log = logging.getLogger(__name__)


class Incident(BaseModel):
    id: str
    tenant_id: str
    opened_at: datetime
    severity: Literal["critical", "high", "medium", "low"]
    status: Literal["open", "investigating", "contained", "closed"]
    title: str
    contributing_findings: list[str] = []


class PolicyEvaluation(BaseModel):
    tenant_id: str
    risk_score: float = Field(ge=0.0, le=10.0)
    passed: bool
    violations: list[str] = []


@router.get("/attack-paths", response_model=list[AttackPath])
async def list_attack_paths(
    request: Request,
    tenant_id: str = Depends(get_tenant_id),
) -> list[AttackPath]:
    settings = request.app.state.settings
    ontology: Ontology = request.app.state.ontology
    store = Neo4jGraphStore(
        config=Neo4jConfig(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            database=settings.neo4j_database,
        ),
        ontology=ontology,
    )
    try:
        await store.connect()
        prompt_injection_paths = await find_prompt_injection_paths(
            store,
            ontology=ontology,
            tenant_id=tenant_id,
        )
        tool_abuse_paths = await find_tool_abuse_paths(
            store,
            ontology=ontology,
            tenant_id=tenant_id,
        )
        memory_poisoning_paths = await find_memory_poisoning_paths(
            store,
            ontology=ontology,
            tenant_id=tenant_id,
        )
    except Exception:  # noqa: BLE001
        log.exception("Failed to query attack paths for tenant %s", tenant_id)
        return []
    finally:
        await store.close()

    merged: dict[str, AttackPath] = {}
    for path in (
        *prompt_injection_paths,
        *tool_abuse_paths,
        *memory_poisoning_paths,
    ):
        merged[path.id] = path
    return sorted(merged.values(), key=lambda path: (-path.score, path.title, path.id))


@router.get("/incidents", response_model=list[Incident])
async def list_incidents(
    tenant_id: str = Depends(get_tenant_id),
) -> list[Incident]:
    _ = tenant_id
    return []


@router.get("/policy", response_model=PolicyEvaluation)
async def evaluate_policy(
    tenant_id: str = Depends(get_tenant_id),
) -> PolicyEvaluation:
    # v0.1: vacuous pass (no rules loaded yet).
    return PolicyEvaluation(
        tenant_id=tenant_id,
        risk_score=0.0,
        passed=True,
        violations=[],
    )
