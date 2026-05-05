"""Node repository scanner — manifest-only.

Emits ``Repository``, ``Container``, ``Artifact[]`` and inferred ``Model``
nodes from ``package.json``. Source extraction lands with the LLM scanner
in week 2.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from connectors.github.src.common import (
    artifact_node,
    container_node,
    depends_on_edge,
    model_node,
    repository_node,
)
from connectors.github.src.stacks.node.parsers import parse_package_json
from connectors.github.src.stacks.node.sdk_model_map import SDK_MODEL_MAP
from connectors.github.src.types import ScanResult

log = logging.getLogger(__name__)


def scan(repo_path: Path, *, repo_url: str | None = None) -> ScanResult:
    """Scan a local Node/TypeScript repository checkout."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    repo_node = repository_node(repo_path, repo_url=repo_url)
    nodes.append(repo_node)
    nodes.append(container_node(repo_path))

    pkg_path = repo_path / "package.json"
    if not pkg_path.is_file():
        log.info("No package.json found at %s", pkg_path)
        return ScanResult(
            nodes=nodes,
            edges=edges,
            repo_path=str(repo_path),
            scanned_at=datetime.now(timezone.utc).isoformat(),
            stack="node",
        )

    deps = parse_package_json(pkg_path)
    for dep in deps:
        name = dep["name"]
        art = artifact_node(name, version=dep.get("version", ""))
        nodes.append(art)
        edges.append(depends_on_edge(repo_node["id"], art["id"]))

        if name in SDK_MODEL_MAP:
            nodes.append(model_node(SDK_MODEL_MAP[name]))

    return ScanResult(
        nodes=nodes,
        edges=edges,
        repo_path=str(repo_path),
        scanned_at=datetime.now(timezone.utc).isoformat(),
        stack="node",
    )
