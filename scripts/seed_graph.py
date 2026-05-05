"""Seed script — adds attack-potential edges the connector can't statically infer.

The GitHub connector produces nodes (Repository, Container, Model, Tool,
PromptTemplate, RAGIndex, File, MemoryStore) and structural edges (DEPENDS_ON,
CONTAINS).

This script adds the *security-semantic* edges that encode how those
components interact at runtime — the edges the Red Agent will traverse to
discover attack paths.

The shape of those edges is target-specific: which RAG index is unsanitized,
which tool is over-privileged, which memory store is poisonable. Because
those are per-target judgment calls, the seed is **driven by a target
profile YAML** under ``targets/``, not module-level constants.

Usage::

    # Dry-run (default) — print resolved edges as JSON, no graph writes.
    python3 scripts/seed_graph.py --target targets/vulnerable-rag-app.yaml

    # Live mode — write to Neo4j.
    python3 scripts/seed_graph.py \\
        --target targets/vulnerable-rag-app.yaml \\
        --neo4j-uri bolt://localhost:7687 \\
        --neo4j-user neo4j \\
        --neo4j-password changeme

The script is **idempotent** — it uses MERGE semantics via ``upsert_edge``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Profile model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NodeRef:
    """A reference to a node — either connector-derived or synthetic."""

    alias: str
    node_id: str
    node_type: str
    properties: dict[str, Any] = field(default_factory=dict)
    synthetic: bool = False


@dataclass(frozen=True)
class SeedEdge:
    """A single edge to seed into the graph."""

    edge_type: str
    source_type: str
    source_id: str
    target_type: str
    target_id: str
    properties: dict[str, Any]
    rationale: str  # Human-readable explanation; not stored in graph.


@dataclass(frozen=True)
class SeedNode:
    """A single node to seed into the graph (synthetic only)."""

    node_type: str
    node_id: str
    properties: dict[str, Any]
    rationale: str


@dataclass(frozen=True)
class TargetProfile:
    """A loaded target profile — the seed's per-target source of truth."""

    name: str
    repo_url: str
    nodes_by_alias: dict[str, NodeRef]
    edges: list[SeedEdge]

    @classmethod
    def load(cls, path: Path) -> "TargetProfile":
        """Load and validate a target profile YAML."""
        if not path.exists():
            msg = f"Target profile not found: {path}"
            raise FileNotFoundError(msg)
        data = yaml.safe_load(path.read_text())
        if not isinstance(data, dict):
            msg = f"Target profile must be a YAML mapping: {path}"
            raise ValueError(msg)

        name = data.get("name")
        if not name:
            msg = f"Target profile missing required field 'name': {path}"
            raise ValueError(msg)
        repo_url = data.get("repo_url", "")

        # ---- Resolve all node aliases (expected + synthetic) ----
        nodes_by_alias: dict[str, NodeRef] = {}
        for alias, spec in (data.get("expected_nodes") or {}).items():
            _require_alias_unique(alias, nodes_by_alias, path)
            nodes_by_alias[alias] = NodeRef(
                alias=alias,
                node_id=_required(spec, "id", f"expected_nodes.{alias}", path),
                node_type=_required(spec, "node_type", f"expected_nodes.{alias}", path),
                properties={},
                synthetic=False,
            )
        for alias, spec in (data.get("synthetic_nodes") or {}).items():
            _require_alias_unique(alias, nodes_by_alias, path)
            nodes_by_alias[alias] = NodeRef(
                alias=alias,
                node_id=_required(spec, "id", f"synthetic_nodes.{alias}", path),
                node_type=_required(spec, "node_type", f"synthetic_nodes.{alias}", path),
                properties=dict(spec.get("properties") or {}),
                synthetic=True,
            )

        # ---- Resolve edges, expanding source/target aliases ----
        edges: list[SeedEdge] = []
        raw_edges = data.get("edges") or []
        if not isinstance(raw_edges, list):
            msg = f"Target profile 'edges' must be a list: {path}"
            raise ValueError(msg)
        for idx, edge_spec in enumerate(raw_edges):
            edge_type = _required(edge_spec, "type", f"edges[{idx}]", path)
            src_alias = _required(edge_spec, "source", f"edges[{idx}]", path)
            tgt_alias = _required(edge_spec, "target", f"edges[{idx}]", path)
            src = _resolve_alias(src_alias, nodes_by_alias, f"edges[{idx}].source", path)
            tgt = _resolve_alias(tgt_alias, nodes_by_alias, f"edges[{idx}].target", path)
            edges.append(SeedEdge(
                edge_type=edge_type,
                source_type=src.node_type,
                source_id=src.node_id,
                target_type=tgt.node_type,
                target_id=tgt.node_id,
                properties=dict(edge_spec.get("properties") or {}),
                rationale=str(edge_spec.get("rationale") or "").strip(),
            ))

        return cls(
            name=name,
            repo_url=repo_url,
            nodes_by_alias=nodes_by_alias,
            edges=edges,
        )

    # ---- Convenience accessors ----

    def synthetic_nodes(self) -> list[SeedNode]:
        """Return SeedNode objects for nodes the seed itself should create."""
        out: list[SeedNode] = []
        for ref in self.nodes_by_alias.values():
            if not ref.synthetic:
                continue
            out.append(SeedNode(
                node_type=ref.node_type,
                node_id=ref.node_id,
                properties=dict(ref.properties),
                rationale=f"Synthetic node materialized from profile alias '{ref.alias}'.",
            ))
        return out

    def expected_nodes(self) -> list[NodeRef]:
        """Return refs to nodes the connector is expected to have produced."""
        return [n for n in self.nodes_by_alias.values() if not n.synthetic]


def _required(spec: Any, key: str, where: str, path: Path) -> Any:
    if not isinstance(spec, dict) or key not in spec or spec[key] in (None, ""):
        msg = f"Target profile {path}: '{where}' missing required '{key}'"
        raise ValueError(msg)
    return spec[key]


def _require_alias_unique(alias: str, existing: dict[str, NodeRef], path: Path) -> None:
    if alias in existing:
        msg = f"Target profile {path}: alias '{alias}' defined twice"
        raise ValueError(msg)


def _resolve_alias(
    alias: str,
    nodes_by_alias: dict[str, NodeRef],
    where: str,
    path: Path,
) -> NodeRef:
    if alias not in nodes_by_alias:
        known = sorted(nodes_by_alias.keys())
        msg = (
            f"Target profile {path}: '{where}' references unknown alias "
            f"'{alias}'. Known aliases: {known}"
        )
        raise ValueError(msg)
    return nodes_by_alias[alias]


# ---------------------------------------------------------------------------
# Pre-flight verification
# ---------------------------------------------------------------------------


async def verify_expected_nodes(
    store: Any,
    tenant_id: str,
    expected: list[NodeRef],
) -> list[str]:
    """Confirm each connector-derived node already exists in the graph.

    Returns a list of missing node IDs — empty if everything is present.
    """
    missing: list[str] = []
    for ref in expected:
        rows = await store.run_cypher(
            "MATCH (n {tenant_id: $tenant_id, id: $node_id}) "
            "RETURN n.id AS id LIMIT 1",
            tenant_id=tenant_id,
            params={"node_id": ref.node_id},
        )
        if not rows:
            missing.append(ref.node_id)
    return missing


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="seed-graph",
        description=(
            "Seed attack-potential edges for a target profile. "
            "Profiles live under targets/ and declare which connector-"
            "derived nodes the seed should wire together."
        ),
    )
    p.add_argument(
        "--target",
        type=Path,
        required=True,
        help="Path to a target profile YAML (e.g. targets/vulnerable-rag-app.yaml).",
    )
    p.add_argument(
        "--neo4j-uri",
        type=str,
        default=None,
        help="Neo4j bolt URI. If omitted, runs in dry-run mode.",
    )
    p.add_argument("--neo4j-user", type=str, default="neo4j")
    p.add_argument("--neo4j-password", type=str, default="changeme")
    p.add_argument("--neo4j-database", type=str, default="neo4j")
    p.add_argument("--tenant-id", type=str, default="default")
    p.add_argument(
        "--skip-verify",
        action="store_true",
        default=False,
        help=(
            "Skip the pre-flight check that confirms each expected_nodes "
            "ID already exists in Neo4j. Use only when you're certain the "
            "connector ran first."
        ),
    )
    p.add_argument("--dry-run", action="store_true", default=False)
    p.add_argument("-v", "--verbose", action="store_true", default=False)
    return p


async def _seed_live(args: argparse.Namespace, profile: TargetProfile) -> int:
    from asp_adapters.graph.neo4j import Neo4jConfig, Neo4jGraphStore
    from asp_core.graph import load_ontology

    ontology = load_ontology("v1")
    config = Neo4jConfig(
        uri=args.neo4j_uri,
        user=args.neo4j_user,
        password=args.neo4j_password,
        database=args.neo4j_database,
    )
    store = Neo4jGraphStore(config=config, ontology=ontology)

    try:
        await store.connect()

        # ---- Pre-flight: confirm the connector ran ----
        if not args.skip_verify:
            expected = profile.expected_nodes()
            missing = await verify_expected_nodes(store, args.tenant_id, expected)
            if missing:
                print(
                    f"ERROR: {len(missing)} of {len(expected)} expected nodes "
                    f"are missing from Neo4j (tenant_id={args.tenant_id!r}):",
                    file=sys.stderr,
                )
                for node_id in missing:
                    print(f"  - {node_id}", file=sys.stderr)
                print(
                    "\nThe GitHub connector hasn't produced these nodes for "
                    f"target '{profile.name}'. Run the connector first:\n"
                    f"  python3 -m connectors.github.src --repo-path <clone> "
                    f"--neo4j-uri {args.neo4j_uri} ...\n"
                    "Or pass --skip-verify if you know what you're doing.",
                    file=sys.stderr,
                )
                return 2

        nodes = profile.synthetic_nodes()
        edges = profile.edges
        errors: list[str] = []

        for node in nodes:
            try:
                await store.upsert_node(
                    tenant_id=args.tenant_id,
                    node_type=node.node_type,
                    node_id=node.node_id,
                    properties=dict(node.properties),
                )
                log.info("Seeded node: %s", node.node_id)
            except Exception as exc:  # noqa: BLE001
                msg = f"Failed node: {node.node_type} {node.node_id}: {exc}"
                log.error(msg)
                errors.append(msg)

        for edge in edges:
            try:
                await store.upsert_edge(
                    tenant_id=args.tenant_id,
                    edge_type=edge.edge_type,
                    source_type=edge.source_type,
                    source_id=edge.source_id,
                    target_type=edge.target_type,
                    target_id=edge.target_id,
                    properties=dict(edge.properties),
                )
                log.info(
                    "Seeded: %s  %s → %s",
                    edge.edge_type, edge.source_id, edge.target_id,
                )
            except Exception as exc:  # noqa: BLE001
                msg = f"Failed: {edge.edge_type} {edge.source_id} → {edge.target_id}: {exc}"
                log.error(msg)
                errors.append(msg)

        expected_writes = len(nodes) + len(edges)
        print(
            f"Seeded {expected_writes - len(errors)}/{expected_writes} "
            f"graph elements for target '{profile.name}'."
        )
        if errors:
            for e in errors:
                print(f"  ERROR: {e}", file=sys.stderr)
            return 1
        return 0
    finally:
        await store.close()


def main() -> int:
    args = _build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-8s %(name)s: %(message)s",
    )

    try:
        profile = TargetProfile.load(args.target)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    is_dry_run = args.dry_run or args.neo4j_uri is None

    if is_dry_run:
        nodes = profile.synthetic_nodes()
        edges = profile.edges
        output = {
            "target": profile.name,
            "repo_url": profile.repo_url,
            "synthetic_nodes": [
                {
                    "node_type": n.node_type,
                    "id": n.node_id,
                    "properties": n.properties,
                    "rationale": n.rationale,
                }
                for n in nodes
            ],
            "edges": [
                {
                    "edge_type": e.edge_type,
                    "source": f"{e.source_type}({e.source_id})",
                    "target": f"{e.target_type}({e.target_id})",
                    "properties": e.properties,
                    "rationale": e.rationale,
                }
                for e in edges
            ],
        }
        print(json.dumps(output, indent=2, default=str))
        print(
            f"\nTarget: {profile.name}\n"
            f"{len(nodes)} synthetic nodes and {len(edges)} edges defined "
            "(dry-run — no writes).",
            file=sys.stderr,
        )
        return 0

    return asyncio.run(_seed_live(args, profile))


# ---------------------------------------------------------------------------
# Backward-compatible accessors used by scripts/tests/test_seed.py.
# These load the bundled profile so the test suite keeps working without
# being forced through CLI plumbing.
# ---------------------------------------------------------------------------


def _bundled_profile() -> TargetProfile:
    """Return the vulnerable-rag-app profile shipped under targets/."""
    repo_root = Path(__file__).resolve().parents[1]
    return TargetProfile.load(repo_root / "targets" / "vulnerable-rag-app.yaml")


def get_vulnerable_rag_app_edges() -> list[SeedEdge]:
    return _bundled_profile().edges


def get_vulnerable_rag_app_nodes() -> list[SeedNode]:
    return _bundled_profile().synthetic_nodes()


if __name__ == "__main__":
    sys.exit(main())
