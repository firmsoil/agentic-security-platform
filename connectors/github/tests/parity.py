"""Parity-diff logic for the LLM scanner vs the Python static scanner.

Pure functions — no I/O, no LLM, no Neo4j. The pytest entry points and
the ad-hoc runner script both consume this module so the diff semantics
stay consistent.

Parity definition (from the launch roadmap):

- **Strict, required:** the set of node IDs the LLM scanner accepts must
  equal the set the static scanner produces, restricted to the four
  LLM-scope node types (``Tool``, ``PromptTemplate``, ``RAGIndex``,
  ``MemoryStore``). Same node_type per ID.

- **Loose, informational:** for matched IDs, every property the static
  scanner emits should be present in the LLM scanner output with the
  same value. Property additions on the LLM side are allowed (the LLM
  may emit a richer ``description`` than the static parser's empty
  string, for example). Property *deletions* are reported as warnings
  but don't fail the test — some static-scanner properties (e.g. the
  PromptTemplate ``checksum``) aren't natural for an LLM to compute.

The launch claim is *"ID + node_type parity, with property diffs
audit-able"* — not byte-for-byte property equality. ADR-0005 is
explicit that the LLM scanner is a classifier under grounding, not a
property-extraction oracle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

LLM_SCOPE_NODE_TYPES: frozenset[str] = frozenset({
    "Tool", "PromptTemplate", "RAGIndex", "MemoryStore",
})


# ---------------------------------------------------------------------------
# Diff result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PropertyDiff:
    """One property-level disagreement between static and LLM nodes."""

    node_id: str
    key: str
    static_value: Any
    llm_value: Any  # Sentinel _MISSING when LLM didn't emit the key.

    @property
    def is_missing(self) -> bool:
        return self.llm_value is _MISSING

    def format(self) -> str:
        if self.is_missing:
            return (
                f"  {self.node_id}.{self.key}: "
                f"static={self.static_value!r}, llm=<missing>"
            )
        return (
            f"  {self.node_id}.{self.key}: "
            f"static={self.static_value!r}, llm={self.llm_value!r}"
        )


@dataclass
class ParityReport:
    """Structured diff report consumed by the test and the runner."""

    static_ids: set[str] = field(default_factory=set)
    llm_ids: set[str] = field(default_factory=set)
    missing_in_llm: set[str] = field(default_factory=set)
    extra_in_llm: set[str] = field(default_factory=set)
    node_type_mismatches: list[tuple[str, str, str]] = field(default_factory=list)
    property_diffs: list[PropertyDiff] = field(default_factory=list)

    @property
    def is_strict_match(self) -> bool:
        """True when ID set + node_type agree. Property diffs do not affect this."""
        return (
            not self.missing_in_llm
            and not self.extra_in_llm
            and not self.node_type_mismatches
        )

    @property
    def match_count(self) -> int:
        """Number of static-scanner IDs the LLM scanner reproduced."""
        return len(self.static_ids - self.missing_in_llm)

    @property
    def match_ratio(self) -> float:
        """Fraction of static-scanner IDs the LLM scanner reproduced.

        1.0 means strict-match (every static ID also produced by the LLM).
        Used by the parity test's threshold mode for adversarial parity
        targets where strict-match is unreliable due to LLM
        non-determinism on non-canonical patterns. See ADR-0005's
        calibration-history paragraph in docs/llm-scanner.md for the
        bundled vulnerable-rag-app's specific edge cases.
        """
        if not self.static_ids:
            return 1.0
        return self.match_count / len(self.static_ids)

    def meets_threshold(self, min_ratio: float) -> bool:
        """True iff match_ratio >= min_ratio AND no node_type mismatches.

        Extra IDs in the LLM scan don't fail the threshold (the LLM may
        legitimately find tools the static scanner missed); only missing
        IDs and type mismatches do.
        """
        return self.match_ratio >= min_ratio and not self.node_type_mismatches

    def format_report(self) -> str:
        lines: list[str] = []
        lines.append(
            f"Parity: {len(self.static_ids - self.missing_in_llm)} of "
            f"{len(self.static_ids)} static-scanner nodes matched."
        )
        if self.missing_in_llm:
            lines.append(
                f"\nIDs the static scanner produced but the LLM did not "
                f"({len(self.missing_in_llm)}):"
            )
            for node_id in sorted(self.missing_in_llm):
                lines.append(f"  - {node_id}")
        if self.extra_in_llm:
            lines.append(
                f"\nIDs the LLM produced that the static scanner did not "
                f"({len(self.extra_in_llm)}):"
            )
            for node_id in sorted(self.extra_in_llm):
                lines.append(f"  + {node_id}")
        if self.node_type_mismatches:
            lines.append(
                f"\nID matched but node_type disagrees "
                f"({len(self.node_type_mismatches)}):"
            )
            for node_id, static_type, llm_type in self.node_type_mismatches:
                lines.append(
                    f"  ! {node_id}: static={static_type}, llm={llm_type}"
                )
        if self.property_diffs:
            lines.append(
                f"\nProperty diffs (informational, do not fail parity) "
                f"({len(self.property_diffs)}):"
            )
            for diff in self.property_diffs:
                lines.append(diff.format())
        if self.is_strict_match and not self.property_diffs:
            lines.append("\nByte-equal property match. ✓")
        elif self.is_strict_match:
            lines.append(
                "\nStrict ID parity ✓ — property diffs are audit-only."
            )
        return "\n".join(lines)


# Sentinel for "key not present in LLM properties." Using object()
# rather than None so a legitimate static value of None doesn't collide.
_MISSING = object()


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------


def filter_to_llm_scope(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Restrict a node list to the four ontology types the LLM scanner emits."""
    return [n for n in nodes if n.get("node_type") in LLM_SCOPE_NODE_TYPES]


def compute_parity_diff(
    static_nodes: list[dict[str, Any]],
    llm_nodes: list[dict[str, Any]],
) -> ParityReport:
    """Return a ParityReport diffing static vs LLM scanner output.

    Both inputs should already be filtered to the four LLM-scope node
    types. The function defensively re-filters to be safe.
    """
    static_filtered = filter_to_llm_scope(static_nodes)
    llm_filtered = filter_to_llm_scope(llm_nodes)

    static_by_id = {n["id"]: n for n in static_filtered}
    llm_by_id = {n["id"]: n for n in llm_filtered}

    report = ParityReport(
        static_ids=set(static_by_id),
        llm_ids=set(llm_by_id),
    )
    report.missing_in_llm = set(static_by_id) - set(llm_by_id)
    report.extra_in_llm = set(llm_by_id) - set(static_by_id)

    # Node-type and property checks for matched IDs only.
    for node_id in sorted(set(static_by_id) & set(llm_by_id)):
        s = static_by_id[node_id]
        l = llm_by_id[node_id]

        if s["node_type"] != l["node_type"]:
            report.node_type_mismatches.append((
                node_id, s["node_type"], l["node_type"],
            ))

        s_props = s.get("properties", {})
        l_props = l.get("properties", {})
        for key, s_value in s_props.items():
            l_value = l_props.get(key, _MISSING)
            if l_value is _MISSING:
                report.property_diffs.append(PropertyDiff(
                    node_id=node_id, key=key,
                    static_value=s_value, llm_value=_MISSING,
                ))
            elif _values_disagree(key, s_value, l_value):
                report.property_diffs.append(PropertyDiff(
                    node_id=node_id, key=key,
                    static_value=s_value, llm_value=l_value,
                ))

    return report


def _values_disagree(key: str, static: Any, llm: Any) -> bool:
    """Return True if the two values disagree in a meaningful way.

    Tolerates: an empty static description vs a richer LLM description
    (the LLM is allowed to be more informative than the static parser's
    empty default). Strict on everything else.
    """
    if key == "description" and static == "" and isinstance(llm, str) and llm:
        return False
    return static != llm
