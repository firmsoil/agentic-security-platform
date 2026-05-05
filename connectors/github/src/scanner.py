"""Multi-stack repository scanner — dispatches by detected stack.

The dispatcher detects the stack from manifest files and delegates to the
appropriate per-stack scanner. Each stack returns the same ``ScanResult``
shape, so the writer and downstream consumers don't care which stack
produced it.

Two entry points:

- ``scan_repository(...)`` — synchronous, manifest-only. The original
  API; preserved for sync callers (tests, dry-run CLI, profile-driven
  workflows that don't need LLM extraction).
- ``scan_repository_with_llm(...)`` — async, runs the manifest scanner
  then layers ``scan_with_llm`` on top, merging LLM-extracted nodes
  into the manifest result. Manifest IDs always win on collisions.
  Returns the same ``ScanResult`` plus the LLM ``ScanReport`` carried
  in ``ScanResult.metadata``.

For backward compatibility, ``ScanResult`` is re-exported here — older
code imported it from ``connectors.github.src.scanner``.
"""

from __future__ import annotations

import dataclasses
import logging
from copy import deepcopy
from pathlib import Path
from typing import Any

from connectors.github.src.detect import UnknownStackError, detect_stack
from connectors.github.src.types import ScanResult

log = logging.getLogger(__name__)

__all__ = [
    "ScanResult",
    "UnknownStackError",
    "scan_repository",
    "scan_repository_with_llm",
]


def scan_repository(
    repo_path: Path,
    *,
    repo_url: str | None = None,
    stack: str | None = None,
) -> ScanResult:
    """Scan a local repository checkout.

    ``stack`` overrides the detector — useful for monorepos where the
    heuristic picks the wrong language (e.g. a Python backend with a
    React frontend that has a top-level package.json).
    """
    chosen = stack or detect_stack(repo_path)

    # Lazy import each stack so installing the package doesn't pay the
    # import cost for stacks the caller never uses, and so a typo in one
    # stack scanner doesn't break the others.
    if chosen == "python":
        from connectors.github.src.stacks.python import scan as scan_python
        return scan_python(repo_path, repo_url=repo_url)
    if chosen == "java":
        from connectors.github.src.stacks.java import scan as scan_java
        return scan_java(repo_path, repo_url=repo_url)
    if chosen == "node":
        from connectors.github.src.stacks.node import scan as scan_node
        return scan_node(repo_path, repo_url=repo_url)

    msg = f"Unknown stack: {chosen!r}"
    raise UnknownStackError(msg)


# ---------------------------------------------------------------------------
# LLM-augmented entry point
# ---------------------------------------------------------------------------


async def scan_repository_with_llm(
    repo_path: Path,
    *,
    adapter: Any,                     # connectors.github.src.llm.protocol.StructuredExtractor
    prompts_dir: Path,
    repo_url: str | None = None,
    stack: str | None = None,
    max_tokens: int = 200_000,
    use_cache: bool = True,
) -> ScanResult:
    """Run the manifest scan, then layer the LLM scanner on top.

    The merge rule is **manifest wins**: if the LLM scanner emits a node
    whose ID collides with a manifest-emitted node, the manifest version
    is kept (it's deterministic; the LLM may have hallucinated or simply
    duplicated). Collisions are logged so the user sees the rejected
    LLM nodes.

    The LLM scanner's ``ScanReport`` is attached to the returned
    ``ScanResult.metadata`` under the ``llm_scan`` key, so callers can
    surface telemetry (token spend, rejection counts) without having to
    re-thread it through their plumbing.
    """
    # Lazy imports so the manifest-only ``scan_repository`` keeps working
    # even when the LLM SDKs and prompts directory aren't present.
    from connectors.github.src.llm.orchestrator import scan_with_llm

    # ---- Phase 1: manifest pass ------------------------------------------
    manifest = scan_repository(repo_path, repo_url=repo_url, stack=stack)
    chosen_stack = manifest.stack

    # ---- Phase 2: LLM pass ------------------------------------------------
    accepted, llm_report = await scan_with_llm(
        repo_path,
        adapter=adapter,
        stack=chosen_stack,
        prompts_dir=prompts_dir,
        max_tokens=max_tokens,
        use_cache=use_cache,
    )

    # ---- Phase 3: merge ---------------------------------------------------
    merged_nodes, llm_id_collisions = _merge_nodes(
        manifest_nodes=manifest.nodes,
        llm_nodes=accepted,
    )

    metadata = {
        "llm_scan": {
            "adapter": adapter.name,
            "model_name": adapter.model_name,
            "report": _serialize_report(llm_report),
            "id_collisions_dropped": llm_id_collisions,
        },
    }

    return dataclasses.replace(
        manifest,
        nodes=merged_nodes,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Merge helpers
# ---------------------------------------------------------------------------


def _merge_nodes(
    *,
    manifest_nodes: list[dict[str, Any]],
    llm_nodes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Combine manifest + LLM nodes, dropping LLM collisions and grounding.

    Returns ``(merged_nodes, dropped_llm_ids)``.

    ``grounding`` blocks on LLM nodes are stripped from the top-level node
    dict but are preserved under ``properties._llm_grounding`` so the
    audit trail survives into the graph (writer accepts arbitrary
    properties, and ``_`` prefix keeps the field out of normal queries).
    """
    manifest_ids = {n["id"] for n in manifest_nodes}
    merged: list[dict[str, Any]] = list(manifest_nodes)
    dropped: list[str] = []

    for node in llm_nodes:
        node_id = node["id"]
        if node_id in manifest_ids:
            log.info(
                "Dropping LLM node %s — collides with manifest node "
                "(manifest wins)",
                node_id,
            )
            dropped.append(node_id)
            continue
        merged.append(_strip_grounding(node))

    return merged, dropped


def _strip_grounding(node: dict[str, Any]) -> dict[str, Any]:
    """Flatten the top-level ``grounding`` block into ``properties._llm_grounding_*``
    scalar fields.

    Keeps the audit trail visible to graph queries that opt into it
    (the underscore prefix marks it as out-of-normal-flow metadata)
    while removing it from the top-level shape that the writer iterates
    over for the ontology-typed graph write.

    Neo4j only accepts primitive types and arrays of primitives as
    property values — nested maps are rejected with TypeError. So
    instead of storing the grounding dict whole, we flatten each field
    into its own scalar property (``_llm_grounding_file_path``,
    ``_llm_grounding_line_start``, etc.). Cypher can query these
    naturally; the prefix keeps them out of normal node-property views.
    """
    out = deepcopy(node)
    grounding = out.pop("grounding", None)
    if grounding is not None:
        props = out.setdefault("properties", {})
        for key, value in grounding.items():
            props[f"_llm_grounding_{key}"] = value
    return out


def _serialize_report(report: Any) -> dict[str, Any]:
    """Render the LLM ScanReport dataclass to a plain dict for JSON."""
    return {
        "files_walked": report.files_walked,
        "extract_calls": report.extract_calls,
        "verify_calls": report.verify_calls,
        "candidates_extracted": report.candidates_extracted,
        "candidates_rejected_at_orchestrator": (
            report.candidates_rejected_at_orchestrator
        ),
        "candidates_rejected_at_verifier": (
            report.candidates_rejected_at_verifier
        ),
        "candidates_accepted": report.candidates_accepted,
        "input_tokens": report.input_tokens,
        "output_tokens": report.output_tokens,
        "total_tokens": report.total_tokens,
        "cache_hit": report.cache_hit,
        "aborted_reason": report.aborted_reason,
        "rejection_log": report.rejection_log,
    }
