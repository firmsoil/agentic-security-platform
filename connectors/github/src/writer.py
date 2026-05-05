"""Writer — bridges ScanResult to Neo4jGraphStore.

Thin async layer that iterates a ``ScanResult`` and calls
``store.upsert_node`` / ``store.upsert_edge`` for each element.

This module is the only place in the connector that touches the graph.
The parsers and scanner are pure functions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from asp_adapters.graph.neo4j import Neo4jGraphStore

from connectors.github.src.scanner import ScanResult

log = logging.getLogger(__name__)


@dataclass
class WriteReport:
    """Summary of a write operation."""

    nodes_written: int = 0
    edges_written: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0

    def summary(self) -> str:
        status = "OK" if self.ok else f"ERRORS ({len(self.errors)})"
        return (
            f"WriteReport: {self.nodes_written} nodes, "
            f"{self.edges_written} edges — {status}"
        )


async def write_scan_result(
    store: Neo4jGraphStore,
    tenant_id: str,
    result: ScanResult,
) -> WriteReport:
    """Upsert all nodes and edges from a ScanResult into the graph.

    Uses ``MERGE`` semantics (via ``upsert_*``) so repeated runs are
    idempotent.  Errors on individual items are captured in the report
    rather than aborting the whole write.
    """
    report = WriteReport()

    # Phase 1: nodes.
    for node in result.nodes:
        try:
            await store.upsert_node(
                tenant_id=tenant_id,
                node_type=node["node_type"],
                node_id=node["id"],
                properties=dict(node.get("properties", {})),
            )
            report.nodes_written += 1
        except Exception as exc:  # noqa: BLE001
            msg = f"Failed to upsert node {node.get('id', '?')}: {exc}"
            log.error(msg)
            report.errors.append(msg)

    # Phase 2: edges (after all nodes exist).
    for edge in result.edges:
        try:
            await store.upsert_edge(
                tenant_id=tenant_id,
                edge_type=edge["edge_type"],
                source_type=edge["source_type"],
                source_id=edge["source_id"],
                target_type=edge["target_type"],
                target_id=edge["target_id"],
                properties=edge.get("properties"),
            )
            report.edges_written += 1
        except Exception as exc:  # noqa: BLE001
            msg = f"Failed to upsert edge {edge.get('edge_type', '?')}: {exc}"
            log.error(msg)
            report.errors.append(msg)

    return report
