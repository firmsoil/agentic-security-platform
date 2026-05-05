"""Golden fixture format + normalization + diff for the determinism story.

Per the launch roadmap and ADR-0005, the platform's reproducibility
claim is *"re-runs against the same commit produce the same graph."*
Golden fixtures are the proof: a recorded scan result, committed to
the repo, that any later re-run must match byte-for-byte after a
defined normalization.

Normalization strips fields that vary across runs even when the inputs
are unchanged:

- Absolute paths (``repo_path``) — varies by user / CI agent.
- ``scanned_at`` timestamp — varies by run.
- LLM scan token counters and ``rejection_log`` text — vary by adapter
  bookkeeping precision.
- ``properties.description`` and ``grounding.evidence`` /
  ``grounding.confidence`` on LLM-extracted nodes — model-narrated,
  not strictly deterministic across invocations even with the cache
  on (the cache makes them deterministic *for a given commit*, but
  re-recording a golden against a new model + prompt version may
  legitimately update them).

Fields the normalizer preserves are the load-bearing ones for the
launch claim: node IDs, node types, edge structure, structural
grounding fields (file_path, file_sha256, line_start, line_end), the
manifest-derived properties.

A normalized fresh scan must equal the normalized golden. Anything
else is a failure — either the source repo changed (legitimate;
re-record), the scanner changed (legitimate if intentional; bump
SCANNER_VERSION + re-record), or there's a determinism bug (the
launch blocker we want to surface loud).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

GOLDEN_SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


# Top-level scan fields that are always carried into the golden, in this
# order so the JSON file diffs are stable across re-records.
_KEEP_SCAN_FIELDS = ("stack", "node_count", "edge_count", "nodes", "edges")

# Per-node properties keys that vary across LLM runs and should be
# replaced with a placeholder during normalization.
_VOLATILE_PROPERTY_KEYS = frozenset({"description"})

# Per-grounding fields that vary across LLM runs.
_VOLATILE_GROUNDING_FIELDS = frozenset({"evidence", "confidence"})

# Sentinel value used in normalized output. Visible in committed JSON so
# reviewers immediately see which fields are model-narrated.
_VOLATILE_PLACEHOLDER = "__VOLATILE__"


def normalize_scan_result(scan: dict[str, Any]) -> dict[str, Any]:
    """Return a determinism-safe view of a ScanResult dict.

    Input is the dict shape produced by ``ScanResult.to_json()`` (after
    ``json.loads``). Output drops or replaces any field that legitimately
    varies across runs.
    """
    nodes = sorted(
        (_normalize_node(n) for n in scan.get("nodes", [])),
        key=lambda n: n["id"],
    )
    edges = sorted(
        (_normalize_edge(e) for e in scan.get("edges", [])),
        key=_edge_sort_key,
    )
    return {
        "stack": scan.get("stack", ""),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": nodes,
        "edges": edges,
    }


def _normalize_node(node: dict[str, Any]) -> dict[str, Any]:
    out = {
        "node_type": node["node_type"],
        "id": node["id"],
        "properties": _normalize_properties(node.get("properties", {})),
    }
    return out


def _normalize_properties(props: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in sorted(props):
        if key in _VOLATILE_PROPERTY_KEYS:
            value = props[key]
            # Empty string stays empty (the static parser's "" is
            # deterministic; only LLM-narrated descriptions need
            # placeholdering).
            out[key] = _VOLATILE_PLACEHOLDER if value else ""
        elif key.startswith("_llm_grounding_"):
            # Flattened grounding fields (Neo4j only accepts primitive
            # property values, so the writer flattens the grounding
            # block into individual scalar fields prefixed
            # ``_llm_grounding_*``). Volatile model-narrated fields
            # (``evidence``, ``confidence``) get placeholdered;
            # structural fields (``file_path``, ``line_start``, etc.)
            # are preserved.
            suffix = key[len("_llm_grounding_"):]
            if suffix in _VOLATILE_GROUNDING_FIELDS:
                out[key] = _VOLATILE_PLACEHOLDER
            else:
                out[key] = props[key]
        else:
            out[key] = props[key]
    return out


def _normalize_edge(edge: dict[str, Any]) -> dict[str, Any]:
    return {
        "edge_type": edge["edge_type"],
        "source_type": edge["source_type"],
        "source_id": edge["source_id"],
        "target_type": edge["target_type"],
        "target_id": edge["target_id"],
        "properties": dict(sorted((edge.get("properties") or {}).items())),
    }


def _edge_sort_key(edge: dict[str, Any]) -> tuple[str, str, str]:
    return (edge["source_id"], edge["target_id"], edge["edge_type"])


# ---------------------------------------------------------------------------
# Golden file format
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Golden:
    """One recorded golden fixture."""

    schema_version: int
    repo_path: str            # relative to repo root
    enable_llm: bool
    adapter_name: str | None
    model_name: str | None
    prompts_dir: str | None
    cache_key: dict[str, Any] | None  # only when enable_llm is True
    normalized_scan: dict[str, Any]


def render_golden_json(g: Golden) -> str:
    """Render a Golden to canonical JSON for committing."""
    payload = {
        "schema_version": g.schema_version,
        "repo_path": g.repo_path,
        "enable_llm": g.enable_llm,
        "adapter_name": g.adapter_name,
        "model_name": g.model_name,
        "prompts_dir": g.prompts_dir,
        "cache_key": g.cache_key,
        "normalized_scan": g.normalized_scan,
    }
    # sort_keys=True at the top level keeps the file diff-stable; the
    # normalized_scan inner contents already sort-stable from
    # ``normalize_scan_result``.
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def parse_golden_json(text: str) -> Golden:
    data = json.loads(text)
    if data.get("schema_version") != GOLDEN_SCHEMA_VERSION:
        msg = (
            f"Unsupported golden schema_version: "
            f"{data.get('schema_version')!r} (expected {GOLDEN_SCHEMA_VERSION})"
        )
        raise ValueError(msg)
    return Golden(
        schema_version=data["schema_version"],
        repo_path=data["repo_path"],
        enable_llm=data.get("enable_llm", False),
        adapter_name=data.get("adapter_name"),
        model_name=data.get("model_name"),
        prompts_dir=data.get("prompts_dir"),
        cache_key=data.get("cache_key"),
        normalized_scan=data["normalized_scan"],
    )


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------


@dataclass
class GoldenDiff:
    """Result of comparing a fresh scan against a golden."""

    matched: bool
    differences: list[str]

    def format_report(self) -> str:
        if self.matched:
            return "Golden match. ✓"
        out = ["Golden mismatch:"]
        for d in self.differences:
            out.append(f"  - {d}")
        return "\n".join(out)


def compare_against_golden(
    *,
    golden: Golden,
    fresh_scan: dict[str, Any],
) -> GoldenDiff:
    """Compare a fresh ``scan_result.to_json()``-shaped dict against a Golden.

    Both sides go through ``normalize_scan_result`` before comparison.
    """
    normalized_fresh = normalize_scan_result(fresh_scan)
    differences = _diff_normalized(
        golden.normalized_scan, normalized_fresh,
    )
    return GoldenDiff(
        matched=not differences,
        differences=differences,
    )


def _diff_normalized(
    a: dict[str, Any],
    b: dict[str, Any],
    path: str = "",
) -> list[str]:
    """Produce a list of human-readable difference descriptions."""
    differences: list[str] = []
    if a == b:
        return differences

    if a.get("stack") != b.get("stack"):
        differences.append(
            f"stack: golden={a.get('stack')!r} fresh={b.get('stack')!r}"
        )

    a_node_ids = {n["id"] for n in a.get("nodes", [])}
    b_node_ids = {n["id"] for n in b.get("nodes", [])}
    only_a = a_node_ids - b_node_ids
    only_b = b_node_ids - a_node_ids
    for nid in sorted(only_a):
        differences.append(f"node missing in fresh: {nid}")
    for nid in sorted(only_b):
        differences.append(f"node added in fresh:   {nid}")

    a_by_id = {n["id"]: n for n in a.get("nodes", [])}
    b_by_id = {n["id"]: n for n in b.get("nodes", [])}
    for nid in sorted(a_node_ids & b_node_ids):
        if a_by_id[nid] != b_by_id[nid]:
            differences.append(
                f"node {nid} differs: "
                f"golden={json.dumps(a_by_id[nid], sort_keys=True)} "
                f"fresh={json.dumps(b_by_id[nid], sort_keys=True)}"
            )

    a_edges = {(e["source_id"], e["target_id"], e["edge_type"]): e
               for e in a.get("edges", [])}
    b_edges = {(e["source_id"], e["target_id"], e["edge_type"]): e
               for e in b.get("edges", [])}
    only_a_e = set(a_edges) - set(b_edges)
    only_b_e = set(b_edges) - set(a_edges)
    for k in sorted(only_a_e):
        differences.append(f"edge missing in fresh: {k}")
    for k in sorted(only_b_e):
        differences.append(f"edge added in fresh:   {k}")

    return differences
