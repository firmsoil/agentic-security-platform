"""Canonical attack-path queries over the Security Graph.

This module stays in ``asp-core`` by depending only on an abstract graph
reader protocol. Infrastructure details (Neo4j connectivity, pooling, auth)
remain in ``asp-adapters``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from hashlib import sha1
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from asp_core.graph.schema import FrameworkMapping, NodeCategory, Ontology


class GraphReader(Protocol):
    """Minimal read protocol implemented by graph adapters."""

    async def run_cypher(
        self,
        cypher: str,
        *,
        tenant_id: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]: ...


class AttackPathNode(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    tenant_id: str
    node_type: str
    category: NodeCategory
    name: str
    properties: dict[str, Any] = Field(default_factory=dict)


class AttackPathEdge(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    tenant_id: str
    edge_type: str
    source_id: str
    target_id: str
    properties: dict[str, Any] = Field(default_factory=dict)


class AttackPath(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    tenant_id: str
    kind: str
    title: str
    score: float = Field(ge=0.0, le=10.0)
    length: int
    nodes: list[str]
    findings: list[str] = Field(default_factory=list)
    first_seen: datetime | None = None
    mappings: list[FrameworkMapping] = Field(default_factory=list)
    graph_nodes: list[AttackPathNode] = Field(default_factory=list)
    graph_edges: list[AttackPathEdge] = Field(default_factory=list)


_PROMPT_INJECTION_QUERY = """
MATCH path = (source)-[pi:PROMPT_INJECTABLE_INTO]->(prompt:Prompt)<-[uses:USES_PROMPT]-(model:Model)-[call:CALLS_TOOL]->(tool:Tool)-[reads:READS]->(store)-[classified:CLASSIFIED_AS]->(dc:DataClassification)
WHERE source.tenant_id = $tenant_id
  AND prompt.tenant_id = $tenant_id
  AND model.tenant_id = $tenant_id
  AND tool.tenant_id = $tenant_id
  AND store.tenant_id = $tenant_id
  AND dc.tenant_id = $tenant_id
  AND dc.level = $classification_level
RETURN $kind AS kind, $title AS title,
       [n IN nodes(path) | {
         id: n.id,
         tenant_id: n.tenant_id,
         node_type: head(labels(n)),
         properties: properties(n)
       }] AS graph_nodes,
       [r IN relationships(path) | {
         id: type(r) + ':' + startNode(r).id + ':' + endNode(r).id,
         tenant_id: r.tenant_id,
         edge_type: type(r),
         source_id: startNode(r).id,
         target_id: endNode(r).id,
         properties: properties(r)
       }] AS graph_edges
"""

_TOOL_ABUSE_QUERY = """
MATCH path = (source)-[pi:PROMPT_INJECTABLE_INTO]->(prompt:Prompt)<-[uses:USES_PROMPT]-(model:Model)<-[tib:TOOL_INVOKABLE_BY]-(tool:Tool)-[reads:READS]->(store)-[classified:CLASSIFIED_AS]->(dc:DataClassification)
WHERE source.tenant_id = $tenant_id
  AND prompt.tenant_id = $tenant_id
  AND model.tenant_id = $tenant_id
  AND tool.tenant_id = $tenant_id
  AND store.tenant_id = $tenant_id
  AND dc.tenant_id = $tenant_id
  AND dc.level = $classification_level
RETURN $kind AS kind, $title AS title,
       [n IN nodes(path) | {
         id: n.id,
         tenant_id: n.tenant_id,
         node_type: head(labels(n)),
         properties: properties(n)
       }] AS graph_nodes,
       [r IN relationships(path) | {
         id: type(r) + ':' + startNode(r).id + ':' + endNode(r).id,
         tenant_id: r.tenant_id,
         edge_type: type(r),
         source_id: startNode(r).id,
         target_id: endNode(r).id,
         properties: properties(r)
       }] AS graph_edges
"""

_MEMORY_POISONING_QUERY = """
MATCH path = (source)-[mp:MEMORY_POISONABLE_BY]->(memory:MemoryStore)-[pi:PROMPT_INJECTABLE_INTO]->(prompt:Prompt)<-[uses:USES_PROMPT]-(model:Model)<-[tib:TOOL_INVOKABLE_BY]-(tool:Tool)-[reads:READS]->(store)-[classified:CLASSIFIED_AS]->(dc:DataClassification)
WHERE source.tenant_id = $tenant_id
  AND memory.tenant_id = $tenant_id
  AND prompt.tenant_id = $tenant_id
  AND model.tenant_id = $tenant_id
  AND tool.tenant_id = $tenant_id
  AND store.tenant_id = $tenant_id
  AND dc.tenant_id = $tenant_id
  AND dc.level = $classification_level
RETURN $kind AS kind, $title AS title,
       [n IN nodes(path) | {
         id: n.id,
         tenant_id: n.tenant_id,
         node_type: head(labels(n)),
         properties: properties(n)
       }] AS graph_nodes,
       [r IN relationships(path) | {
         id: type(r) + ':' + startNode(r).id + ':' + endNode(r).id,
         tenant_id: r.tenant_id,
         edge_type: type(r),
         source_id: startNode(r).id,
         target_id: endNode(r).id,
         properties: properties(r)
       }] AS graph_edges
"""


async def find_prompt_injection_paths(
    graph: GraphReader,
    *,
    ontology: Ontology,
    tenant_id: str,
    classification_level: str = "regulated",
) -> list[AttackPath]:
    rows = await graph.run_cypher(
        _PROMPT_INJECTION_QUERY,
        tenant_id=tenant_id,
        params={
            "classification_level": classification_level,
            "kind": "prompt_injection",
            "title": "Prompt injection reaches regulated data",
        },
    )
    return _materialize_rows(rows, ontology=ontology, tenant_id=tenant_id)


async def find_tool_abuse_paths(
    graph: GraphReader,
    *,
    ontology: Ontology,
    tenant_id: str,
    classification_level: str = "regulated",
) -> list[AttackPath]:
    rows = await graph.run_cypher(
        _TOOL_ABUSE_QUERY,
        tenant_id=tenant_id,
        params={
            "classification_level": classification_level,
            "kind": "tool_abuse",
            "title": "Model-invokable tool can read regulated data",
        },
    )
    return _materialize_rows(rows, ontology=ontology, tenant_id=tenant_id)


async def find_memory_poisoning_paths(
    graph: GraphReader,
    *,
    ontology: Ontology,
    tenant_id: str,
    classification_level: str = "regulated",
) -> list[AttackPath]:
    rows = await graph.run_cypher(
        _MEMORY_POISONING_QUERY,
        tenant_id=tenant_id,
        params={
            "classification_level": classification_level,
            "kind": "memory_poisoning",
            "title": "Poisoned memory can drive data exfiltration",
        },
    )
    return _materialize_rows(rows, ontology=ontology, tenant_id=tenant_id)


def _materialize_rows(
    rows: Sequence[dict[str, Any]],
    *,
    ontology: Ontology,
    tenant_id: str,
) -> list[AttackPath]:
    paths: list[AttackPath] = []
    seen_ids: set[str] = set()
    for row in rows:
        raw_nodes = row.get("graph_nodes")
        raw_edges = row.get("graph_edges")
        if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
            continue
        attack_path = _materialize_path(
            ontology=ontology,
            tenant_id=tenant_id,
            kind=str(row.get("kind", "attack_path")),
            title=str(row.get("title", "Attack path")),
            raw_nodes=raw_nodes,
            raw_edges=raw_edges,
        )
        if attack_path.id in seen_ids:
            continue
        seen_ids.add(attack_path.id)
        paths.append(attack_path)
    return sorted(paths, key=lambda path: (-path.score, path.title, path.id))


def _materialize_path(
    *,
    ontology: Ontology,
    tenant_id: str,
    kind: str,
    title: str,
    raw_nodes: Sequence[dict[str, Any]],
    raw_edges: Sequence[dict[str, Any]],
) -> AttackPath:
    graph_nodes = [_node_from_projection(node, ontology=ontology) for node in raw_nodes]
    graph_edges = [_edge_from_projection(rel, tenant_id=tenant_id) for rel in raw_edges]
    node_ids = [node.id for node in graph_nodes]
    path_hash = sha1("|".join([kind, *node_ids]).encode("utf-8")).hexdigest()[:12]
    mappings = _resolve_mappings(
        ontology=ontology,
        node_types=[node.node_type for node in graph_nodes],
        edge_types=[edge.edge_type for edge in graph_edges],
    )
    score = _score_path(graph_nodes, graph_edges, mappings)
    findings = _build_findings(graph_nodes, graph_edges, mappings)
    return AttackPath(
        id=f"AttackPath:{kind}:{path_hash}",
        tenant_id=tenant_id,
        kind=kind,
        title=title,
        score=score,
        length=len(graph_edges),
        nodes=node_ids,
        findings=findings,
        mappings=mappings,
        graph_nodes=graph_nodes,
        graph_edges=graph_edges,
    )


def _node_from_projection(raw_node: dict[str, Any], *, ontology: Ontology) -> AttackPathNode:
    node_type = str(raw_node.get("node_type", "Unknown"))
    node_def = ontology.node_by_name(node_type)
    props = dict(raw_node.get("properties", {}))
    return AttackPathNode(
        id=str(raw_node.get("id", props.get("id", node_type))),
        tenant_id=str(raw_node.get("tenant_id", props.get("tenant_id", "default"))),
        node_type=node_type,
        category=node_def.category if node_def is not None else NodeCategory.SECURITY,
        name=_display_name(node_type, props),
        properties=props,
    )


def _edge_from_projection(raw_edge: dict[str, Any], *, tenant_id: str) -> AttackPathEdge:
    props = dict(raw_edge.get("properties", {}))
    return AttackPathEdge(
        id=str(raw_edge.get("id", "edge")),
        tenant_id=str(raw_edge.get("tenant_id", props.get("tenant_id", tenant_id))),
        edge_type=str(raw_edge.get("edge_type", "RELATED_TO")),
        source_id=str(raw_edge.get("source_id", "unknown")),
        target_id=str(raw_edge.get("target_id", "unknown")),
        properties=props,
    )


def _display_name(node_type: str, props: dict[str, Any]) -> str:
    for key in ("name", "level", "path", "reference", "provider"):
        value = props.get(key)
        if isinstance(value, str) and value:
            return value
    raw_id = props.get("id")
    if isinstance(raw_id, str) and ":" in raw_id:
        return raw_id.split(":", 1)[1]
    return str(raw_id or node_type)


def _resolve_mappings(
    *,
    ontology: Ontology,
    node_types: Sequence[str],
    edge_types: Sequence[str],
) -> list[FrameworkMapping]:
    merged: dict[tuple[str, str], FrameworkMapping] = {}
    for node_type in node_types:
        node_def = ontology.node_by_name(node_type)
        if node_def is None:
            continue
        for mapping in node_def.mappings:
            merged[(mapping.framework, mapping.identifier)] = mapping
    for edge_type in edge_types:
        edge_def = ontology.edge_by_name(edge_type)
        if edge_def is None:
            continue
        for mapping in edge_def.mappings:
            merged[(mapping.framework, mapping.identifier)] = mapping
    return sorted(
        merged.values(),
        key=lambda mapping: (mapping.framework, mapping.identifier, mapping.title or ""),
    )


def _score_path(
    nodes: Sequence[AttackPathNode],
    edges: Sequence[AttackPathEdge],
    mappings: Sequence[FrameworkMapping],
) -> float:
    score = 4.0
    if any(node.node_type == "DataClassification" and node.properties.get("level") == "regulated" for node in nodes):
        score += 2.5
    if any(edge.edge_type == "TOOL_INVOKABLE_BY" and edge.properties.get("requires_human_approval") is False for edge in edges):
        score += 1.5
    score += min(len(mappings) * 0.25, 1.5)
    score += min(len(edges) * 0.15, 0.5)
    return round(min(score, 10.0), 1)


def _build_findings(
    nodes: Sequence[AttackPathNode],
    edges: Sequence[AttackPathEdge],
    mappings: Sequence[FrameworkMapping],
) -> list[str]:
    findings: list[str] = []
    if any(edge.edge_type == "PROMPT_INJECTABLE_INTO" for edge in edges):
        findings.append("Untrusted content can influence model behavior.")
    if any(edge.edge_type == "TOOL_INVOKABLE_BY" for edge in edges):
        findings.append("A model-invokable tool is reachable on the attack path.")
    if any(edge.edge_type == "MEMORY_POISONABLE_BY" for edge in edges):
        findings.append("Shared memory can be poisoned across requests.")
    regulated_targets = [
        node.name
        for node in nodes
        if node.node_type == "DataClassification" and node.properties.get("level") == "regulated"
    ]
    if regulated_targets:
        findings.append("The path reaches regulated data handling surfaces.")
    findings.extend(
        f"{mapping.identifier} — {mapping.title}"
        for mapping in mappings
        if mapping.framework == "OWASP_AGENTIC_TOP_10_2026" and mapping.title is not None
    )
    deduped: list[str] = []
    seen: set[str] = set()
    for finding in findings:
        if finding in seen:
            continue
        seen.add(finding)
        deduped.append(finding)
    return deduped
