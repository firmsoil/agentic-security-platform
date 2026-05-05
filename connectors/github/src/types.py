"""Shared types for the multi-stack GitHub connector.

The connector dispatches by stack (Python, Java, Node) but every stack's
scanner returns the same ``ScanResult`` shape, which the writer then
upserts into the graph. Keeping this type stack-neutral is what lets the
seed/API/frontend stay stack-agnostic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ScanResult:
    """The complete set of nodes and structural edges extracted from a repo."""

    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    repo_path: str = ""
    scanned_at: str = ""
    stack: str = ""  # 'python' | 'java' | 'node' — populated by the dispatcher
    # Optional ride-along metadata. Populated by ``scan_repository_with_llm``
    # to surface the LLM scanner's ``ScanReport`` alongside the merged
    # nodes; absent for manifest-only scans. Backwards-compatible default.
    metadata: dict[str, Any] | None = None

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON for ``--dry-run`` output and test assertions."""
        payload = {
            "repo_path": self.repo_path,
            "stack": self.stack,
            "scanned_at": self.scanned_at,
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "nodes": self.nodes,
            "edges": self.edges,
        }
        if self.metadata is not None:
            payload["metadata"] = self.metadata
        return json.dumps(payload, indent=indent, default=str)
