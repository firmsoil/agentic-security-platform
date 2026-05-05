"""Python repository scanner — orchestrates Python parsers into a ScanResult.

The scanner is deterministic for a given filesystem state. It does not
access the network or the graph database. Attack-potential edges
(``PROMPT_INJECTABLE_INTO``, etc.) are seeded by ``scripts/seed_graph.py``
from a target profile, not derived here.
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
from connectors.github.src.stacks.python.parsers import (
    parse_corpus,
    parse_memory_store,
    parse_prompt_template,
    parse_requirements,
    parse_tool_schemas,
)
from connectors.github.src.stacks.python.sdk_model_map import SDK_MODEL_MAP
from connectors.github.src.types import ScanResult

log = logging.getLogger(__name__)


def scan(repo_path: Path, *, repo_url: str | None = None) -> ScanResult:
    """Scan a local Python repository checkout."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    repo_node = repository_node(repo_path, repo_url=repo_url)
    nodes.append(repo_node)
    nodes.append(container_node(repo_path))

    # ---- requirements.txt → dependencies + Model inference ----
    req_path = repo_path / "requirements.txt"
    if req_path.exists():
        deps = parse_requirements(req_path)
        for dep in deps:
            dep_name = dep["name"]
            art = artifact_node(dep_name, version=dep.get("specifier", ""))
            nodes.append(art)
            edges.append(depends_on_edge(repo_node["id"], art["id"]))
            if dep_name in SDK_MODEL_MAP:
                nodes.append(model_node(SDK_MODEL_MAP[dep_name]))
    else:
        log.info("No requirements.txt found at %s", req_path)

    # ---- tools.py → Tool nodes ----
    tools_path = repo_path / "tools.py"
    if tools_path.exists():
        nodes.extend(parse_tool_schemas(tools_path))
    else:
        log.info("No tools.py found at %s", tools_path)

    # ---- model.py → PromptTemplate node ----
    model_path = repo_path / "model.py"
    if model_path.exists():
        pt_node = parse_prompt_template(model_path)
        if pt_node:
            nodes.append(pt_node)
    else:
        log.info("No model.py found at %s", model_path)

    # ---- corpus/ → RAGIndex + File nodes ----
    corpus_dir = repo_path / "corpus"
    if corpus_dir.is_dir():
        rag_node, file_nodes = parse_corpus(corpus_dir)
        nodes.append(rag_node)
        nodes.extend(file_nodes)
        for fn in file_nodes:
            edges.append({
                "edge_type": "CONTAINS",
                "source_type": "RAGIndex",
                "source_id": rag_node["id"],
                "target_type": "File",
                "target_id": fn["id"],
                "properties": {},
            })
    else:
        log.info("No corpus/ directory found at %s", corpus_dir)

    # ---- memory.py → MemoryStore node ----
    memory_path = repo_path / "memory.py"
    if memory_path.exists():
        mem_node = parse_memory_store(memory_path)
        if mem_node:
            nodes.append(mem_node)
    else:
        log.info("No memory.py found at %s", memory_path)

    return ScanResult(
        nodes=nodes,
        edges=edges,
        repo_path=str(repo_path),
        scanned_at=datetime.now(timezone.utc).isoformat(),
        stack="python",
    )
