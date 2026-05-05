"""Stack-neutral helpers used by every stack scanner.

Anything that emits a node which doesn't depend on language conventions
lives here — Repository node, Container node, Artifact node construction
from a (name, version) pair.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def repository_node(repo_path: Path, *, repo_url: str | None = None) -> dict[str, Any]:
    """Build the ``Repository`` node for a repo checkout.

    The ID is derived from the directory name, matching what target
    profiles in ``targets/`` expect. ``repo_url`` overrides the placeholder
    when the connector knows the real GitHub URL (e.g. when invoked with
    ``--repo-url``).
    """
    repo_name = repo_path.name
    return {
        "node_type": "Repository",
        "id": f"Repository:{repo_name}",
        "properties": {
            "url": repo_url or f"https://github.com/org/{repo_name}",
            "default_branch": "main",
            "visibility": "public" if repo_url else "private",
        },
    }


def container_node(repo_path: Path) -> dict[str, Any]:
    """Build the ``Container`` node for a repo checkout.

    The Container is the runtime surface — INVOKES_MODEL targets the
    container, not the repo. The image tag is best-effort; runtime
    digests get filled in by an OTel ingest path that hasn't shipped
    yet.
    """
    repo_name = repo_path.name
    return {
        "node_type": "Container",
        "id": f"Container:{repo_name}",
        "properties": {
            "image": f"{repo_name}:latest",
            "image_digest": "",
            "started_at": "",
        },
    }


def artifact_node(name: str, *, version: str = "", digest: str = "") -> dict[str, Any]:
    """Build an ``Artifact`` node for a single dependency."""
    return {
        "node_type": "Artifact",
        "id": f"Artifact:{name}",
        "properties": {
            "name": name,
            "version": version,
            "digest": digest,
        },
    }


def depends_on_edge(repo_node_id: str, artifact_node_id: str) -> dict[str, Any]:
    """Build the ``DEPENDS_ON`` edge from a Repository to one Artifact."""
    return {
        "edge_type": "DEPENDS_ON",
        "source_type": "Repository",
        "source_id": repo_node_id,
        "target_type": "Artifact",
        "target_id": artifact_node_id,
        "properties": {},
    }


def model_node(spec: dict[str, Any]) -> dict[str, Any]:
    """Build a ``Model`` node from an SDK→Model map entry.

    ``spec`` is the value from a per-stack SDK map — it must contain
    ``provider`` and ``name`` at minimum.
    """
    return {
        "node_type": "Model",
        "id": f"Model:{spec['provider']}:{spec['name']}",
        "properties": dict(spec),
    }
