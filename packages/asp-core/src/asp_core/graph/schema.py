"""Security Graph schema — typed node and edge model definitions.

The concrete ontology lives in `ontology/v1/*.yaml`. This module provides the
Python types used to load, validate, and query it.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


class NodeCategory(StrEnum):
    """Top-level groupings of node types. Matches the architecture diagram's
    foundational AI-application layers, plus security-specific categories."""

    INFRASTRUCTURE = "infrastructure"
    IDENTITY = "identity"
    CODE = "code"
    DATA = "data"
    AI = "ai"                   # AI-specific: Model, Prompt, Tool, RAG, ...
    SECURITY = "security"       # Vulnerability, Finding, Policy, Incident, ...
    EVENT = "event"             # TraceSpan, Alert, AuditLogEntry, ...


class EdgeCategory(StrEnum):
    """Groupings of edge types."""

    STRUCTURAL = "structural"   # RUNS_IN, DEPLOYED_TO, DEPENDS_ON, OWNED_BY
    IDENTITY = "identity"       # ASSUMES, HAS_PERMISSION, AUTHENTICATES_AS
    DATA_FLOW = "data_flow"     # READS, WRITES, PROCESSES, CONTAINS
    AI = "ai"                   # INVOKES_MODEL, USES_PROMPT, CALLS_TOOL, ...
    SECURITY = "security"       # VULNERABLE_TO, VIOLATES, EXPLOITS, ...


class FrameworkMapping(BaseModel):
    """A mapping from an ontology element to an external framework control.

    Example:
        framework="OWASP_AGENTIC_TOP_10_2026", identifier="ASI-06",
        title="Memory & Context Poisoning"
    """

    framework: str = Field(..., description="Framework identifier, e.g. MITRE_ATLAS")
    identifier: str = Field(..., description="Control identifier within the framework")
    title: str | None = None
    url: str | None = None


class NodeType(BaseModel):
    """Definition of a single node type in the ontology."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(..., description="Node type name, e.g. 'Model' or 'Prompt'")
    category: NodeCategory
    description: str
    # Schema of properties this node type is expected to carry.
    # Not enforced at query time — this is documentation and validation hints.
    properties: dict[str, str] = Field(default_factory=dict)
    mappings: list[FrameworkMapping] = Field(default_factory=list)


class EdgeType(BaseModel):
    """Definition of a single edge type in the ontology."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(..., description="Edge type name, e.g. 'INVOKES_MODEL'")
    category: EdgeCategory
    description: str
    # Directional constraint: which node types can be the source/target.
    # Using lists lets us model polymorphism (e.g. READS can go from many sources to many targets).
    source_types: list[str] = Field(default_factory=list)
    target_types: list[str] = Field(default_factory=list)
    properties: dict[str, str] = Field(default_factory=dict)
    mappings: list[FrameworkMapping] = Field(default_factory=list)


class Ontology(BaseModel):
    """A versioned ontology bundle — nodes + edges + mappings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = Field(..., description="Semver. Breaking changes bump major.")
    nodes: list[NodeType]
    edges: list[EdgeType]

    def node_by_name(self, name: str) -> NodeType | None:
        for n in self.nodes:
            if n.name == name:
                return n
        return None

    def edge_by_name(self, name: str) -> EdgeType | None:
        for e in self.edges:
            if e.name == name:
                return e
        return None


def load_ontology(version: str = "v1") -> Ontology:
    """Load the bundled ontology of the given version.

    Versions are directories under `graph/ontology/`. Each contains:
      - nodes.yaml
      - edges.yaml
      - mappings/*.yaml  (owasp_llm.yaml, owasp_agentic.yaml, mitre_atlas.yaml, ...)
    """
    base = Path(__file__).parent / "ontology" / version
    if not base.is_dir():
        msg = f"Ontology version not found: {version} (expected at {base})"
        raise FileNotFoundError(msg)

    nodes_raw = yaml.safe_load((base / "nodes.yaml").read_text())
    edges_raw = yaml.safe_load((base / "edges.yaml").read_text())
    mappings = _load_mappings(base / "mappings")

    nodes = [_merge_node_mappings(n, mappings) for n in nodes_raw["nodes"]]
    edges = [_merge_edge_mappings(e, mappings) for e in edges_raw["edges"]]

    return Ontology(version=nodes_raw["version"], nodes=nodes, edges=edges)


def _load_mappings(mappings_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """Load all mapping YAMLs and return a dict keyed by (kind, name).

    Kind is 'node' or 'edge'; name is the node/edge type name.
    Each entry in the list is a raw mapping dict.
    """
    index: dict[str, list[dict[str, Any]]] = {}
    if not mappings_dir.is_dir():
        return index
    for path in sorted(mappings_dir.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text()) or {}
        for entry in raw.get("mappings", []):
            kind = entry["applies_to"]["kind"]  # "node" | "edge"
            name = entry["applies_to"]["name"]
            key = f"{kind}::{name}"
            index.setdefault(key, []).append(
                {
                    "framework": raw["framework"],
                    "identifier": entry["identifier"],
                    "title": entry.get("title"),
                    "url": entry.get("url"),
                }
            )
    return index


def _merge_node_mappings(
    raw: dict[str, Any], mappings: dict[str, list[dict[str, Any]]]
) -> NodeType:
    key = f"node::{raw['name']}"
    raw.setdefault("mappings", [])
    raw["mappings"].extend(mappings.get(key, []))
    return NodeType.model_validate(raw)


def _merge_edge_mappings(
    raw: dict[str, Any], mappings: dict[str, list[dict[str, Any]]]
) -> EdgeType:
    key = f"edge::{raw['name']}"
    raw.setdefault("mappings", [])
    raw["mappings"].extend(mappings.get(key, []))
    return EdgeType.model_validate(raw)
