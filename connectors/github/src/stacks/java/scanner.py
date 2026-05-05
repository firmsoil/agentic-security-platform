"""Java repository scanner — manifest-only.

Emits ``Repository``, ``Container``, ``Artifact[]`` and inferred ``Model``
nodes. Source-AST work for ``Tool`` / ``PromptTemplate`` / ``RAGIndex`` /
``MemoryStore`` is the LLM scanner's job (week 2).

Picks up either ``pom.xml`` (Maven) or ``build.gradle[.kts]`` (Gradle).
If both are present — as in some hybrid migrations — both are parsed and
their dependency lists are unioned by ``(group, artifactId)``.
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
from connectors.github.src.stacks.java.parsers import parse_gradle, parse_pom
from connectors.github.src.stacks.java.sdk_model_map import SDK_MODEL_MAP
from connectors.github.src.types import ScanResult

log = logging.getLogger(__name__)

_GRADLE_FILES = ("build.gradle", "build.gradle.kts")


def scan(repo_path: Path, *, repo_url: str | None = None) -> ScanResult:
    """Scan a local Java repository checkout."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    repo_node = repository_node(repo_path, repo_url=repo_url)
    nodes.append(repo_node)
    nodes.append(container_node(repo_path))

    deps: list[dict[str, str]] = []
    pom_path = repo_path / "pom.xml"
    if pom_path.is_file():
        deps.extend(parse_pom(pom_path))

    for gradle_name in _GRADLE_FILES:
        gradle_path = repo_path / gradle_name
        if gradle_path.is_file():
            deps.extend(parse_gradle(gradle_path))

    if not deps:
        log.info("No Java manifest dependencies found at %s", repo_path)

    # Deduplicate by artifactId — the most specific identifier in
    # SDK_MODEL_MAP. Group is preserved on the Artifact node.
    seen: set[str] = set()
    for dep in deps:
        name = dep["name"]
        if name in seen:
            continue
        seen.add(name)

        art = artifact_node(name, version=dep.get("version", ""))
        # Stash the groupId in properties so downstream consumers can
        # disambiguate same-named artifacts across Maven groups.
        art["properties"]["group"] = dep.get("group", "")
        nodes.append(art)
        edges.append(depends_on_edge(repo_node["id"], art["id"]))

        # SDK→Model match: the key may be the bare artifactId or the
        # full ``group:artifact`` coordinate.
        coord = f"{dep.get('group', '')}:{name}"
        for sdk_key, model_spec in SDK_MODEL_MAP.items():
            if sdk_key == name or sdk_key in coord:
                nodes.append(model_node(model_spec))
                break

    return ScanResult(
        nodes=nodes,
        edges=edges,
        repo_path=str(repo_path),
        scanned_at=datetime.now(timezone.utc).isoformat(),
        stack="java",
    )
