"""Ontology introspection endpoints.

The ontology is the platform's public schema. Exposing it over HTTP lets
frontend code discover node/edge types dynamically, and lets other teams'
agents discover what the Security Graph can answer.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from asp_core.graph import Ontology

router = APIRouter(prefix="/ontology", tags=["ontology"])


@router.get("", response_model=Ontology)
async def get_ontology(request: Request) -> Ontology:
    return request.app.state.ontology


@router.get("/nodes")
async def list_node_types(request: Request) -> list[dict[str, str]]:
    """Lightweight list useful for UI filters."""
    ontology: Ontology = request.app.state.ontology
    return [
        {"name": n.name, "category": n.category.value, "description": n.description}
        for n in ontology.nodes
    ]


@router.get("/edges")
async def list_edge_types(request: Request) -> list[dict[str, str]]:
    ontology: Ontology = request.app.state.ontology
    return [
        {"name": e.name, "category": e.category.value, "description": e.description}
        for e in ontology.edges
    ]
