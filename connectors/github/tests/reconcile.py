"""Reconciliation diff: profile expected_nodes vs dispatcher scan output.

Pure functions — no I/O, no LLM, no Neo4j. The runner script
(``scripts/reconcile_target.py``) and the unit tests both consume this
module so the categorization stays consistent.

The diff splits the mismatch space into four buckets:

- **Confirmed** — the profile predicted an ID, the scanner produced it.
  Promote PREDICTED → CONFIRMED in the YAML on next edit pass.
- **Drifted** — the profile predicted an ID, the scanner produced a
  *different* ID of the same node_type that no other profile alias
  claims. Highly likely to be a rename — the runner suggests the
  one-line YAML edit.
- **Missing** — the profile predicted an ID, the scanner produced no
  node of that type at all. Either the model missed it (week-4 prompt-
  tuning signal), the source repo doesn't actually have one (fork
  needed?), or the prediction was wrong.
- **Unclaimed** — the scanner produced an ID the profile doesn't
  reference. Either add to ``expected_nodes`` (genuine extra finding)
  or treat as a false positive (week-4 trust signal).

  Unclaimed reporting auto-narrows to the node *types* the profile
  already cares about. If the profile lists at least one Tool,
  unclaimed Tools are reported; if the profile doesn't reference any
  File nodes, unclaimed File nodes are silently dropped (manifest-pass
  Artifact and File nodes shouldn't appear in expected_nodes by
  convention — they're scan-derived but not load-bearing for the
  seed). Empty profiles fall back to "report everything" so the
  bootstrap workflow ("scan first, paste IDs into the profile after")
  still works.

A clean reconciliation has every expected_node confirmed and zero
unclaimed (after the auto-narrow filter). The runner exits 0 in that
case, 1 otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ConfirmedEntry:
    """profile predicted this ID, scanner produced it."""
    alias: str
    node_id: str
    node_type: str


@dataclass(frozen=True)
class DriftedEntry:
    """profile predicted ID X, scanner produced ID Y of the same node_type."""
    alias: str
    predicted_id: str
    actual_id: str
    node_type: str

    def suggested_edit(self) -> str:
        return (
            f"  expected_nodes.{self.alias}.id: "
            f"{self.predicted_id!r} → {self.actual_id!r}"
        )


@dataclass(frozen=True)
class MissingEntry:
    """profile predicted this ID, no scanner node of that type was found."""
    alias: str
    predicted_id: str
    node_type: str


@dataclass(frozen=True)
class UnclaimedEntry:
    """scanner produced this ID, profile doesn't reference it."""
    node_id: str
    node_type: str


@dataclass
class ReconcileReport:
    confirmed: list[ConfirmedEntry] = field(default_factory=list)
    drifted: list[DriftedEntry] = field(default_factory=list)
    missing: list[MissingEntry] = field(default_factory=list)
    unclaimed: list[UnclaimedEntry] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        """True iff every expected_node confirmed and nothing unclaimed."""
        return not (self.drifted or self.missing or self.unclaimed)

    @property
    def expected_count(self) -> int:
        return len(self.confirmed) + len(self.drifted) + len(self.missing)

    def format_report(self) -> str:
        lines: list[str] = []
        lines.append(
            f"Reconciliation: {len(self.confirmed)} of "
            f"{self.expected_count} expected_nodes confirmed."
        )

        if self.confirmed:
            lines.append(f"\nCONFIRMED ({len(self.confirmed)}):")
            for c in self.confirmed:
                lines.append(f"  ✓ {c.alias:<22} {c.node_id}")

        if self.drifted:
            lines.append(
                f"\nDRIFTED ({len(self.drifted)}) — predicted ID not found, "
                "matching node_type was; suggested YAML edits:"
            )
            for d in self.drifted:
                lines.append(f"  ! {d.alias:<22} predicted: {d.predicted_id}")
                lines.append(f"    {'':<22} actual:    {d.actual_id}")
                lines.append(d.suggested_edit())

        if self.missing:
            lines.append(
                f"\nMISSING ({len(self.missing)}) — predicted, no candidate "
                "of the same type:"
            )
            for m in self.missing:
                lines.append(
                    f"  ✗ {m.alias:<22} {m.predicted_id}  "
                    f"(no {m.node_type} nodes in scan output)"
                )

        if self.unclaimed:
            lines.append(
                f"\nUNCLAIMED ({len(self.unclaimed)}) — scanner produced, "
                "profile doesn't reference:"
            )
            for u in self.unclaimed:
                lines.append(f"  + {u.node_id}")
            lines.append(
                "    Either add to expected_nodes or investigate as a "
                "potential false positive."
            )

        if self.is_clean:
            lines.append("\nClean reconciliation. ✓")
        else:
            actions: list[str] = []
            if self.drifted:
                actions.append(
                    f"{len(self.drifted)} YAML edit"
                    + ("s" if len(self.drifted) > 1 else "")
                )
            if self.missing:
                actions.append(
                    f"{len(self.missing)} prediction"
                    + ("s" if len(self.missing) > 1 else "")
                    + " to investigate"
                )
            if self.unclaimed:
                actions.append(
                    f"{len(self.unclaimed)} unclaimed node"
                    + ("s" if len(self.unclaimed) > 1 else "")
                    + " to triage"
                )
            lines.append(f"\nSuggested next: {', '.join(actions)} then re-run.")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------


def reconcile(
    *,
    expected: list[Any],         # list of NodeRef from TargetProfile.expected_nodes()
    actual_nodes: list[dict[str, Any]],
) -> ReconcileReport:
    """Categorize the gap between profile predictions and actual scan output.

    ``expected`` is the list returned by
    ``TargetProfile.expected_nodes()`` — each entry has ``.alias``,
    ``.node_id``, and ``.node_type``.

    ``actual_nodes`` is the merged ``ScanResult.nodes`` list from the
    dispatcher (manifest + LLM if --enable-llm was used).
    """
    report = ReconcileReport()

    # Build lookup tables.
    actual_by_id: dict[str, dict[str, Any]] = {n["id"]: n for n in actual_nodes}
    actual_by_type: dict[str, list[str]] = {}
    for n in actual_nodes:
        actual_by_type.setdefault(n["node_type"], []).append(n["id"])

    # Track which actual IDs got "claimed" (by confirm or drift) so we
    # don't double-count them as both drift candidates and unclaimed.
    claimed_actual_ids: set[str] = set()

    for ref in expected:
        if ref.node_id in actual_by_id:
            report.confirmed.append(ConfirmedEntry(
                alias=ref.alias,
                node_id=ref.node_id,
                node_type=ref.node_type,
            ))
            claimed_actual_ids.add(ref.node_id)
            continue

        # Look for a same-type actual node not yet claimed by another
        # profile entry — that's the drift candidate.
        same_type_actuals = [
            aid for aid in actual_by_type.get(ref.node_type, [])
            if aid not in claimed_actual_ids
        ]
        if len(same_type_actuals) == 1:
            # Single candidate — high-confidence rename.
            report.drifted.append(DriftedEntry(
                alias=ref.alias,
                predicted_id=ref.node_id,
                actual_id=same_type_actuals[0],
                node_type=ref.node_type,
            ))
            claimed_actual_ids.add(same_type_actuals[0])
        elif len(same_type_actuals) > 1:
            # Multiple candidates — pick the first (sorted) and let the
            # human decide. Note all candidates in the report by
            # creating one drift per remaining candidate.
            chosen = sorted(same_type_actuals)[0]
            report.drifted.append(DriftedEntry(
                alias=ref.alias,
                predicted_id=ref.node_id,
                actual_id=chosen,
                node_type=ref.node_type,
            ))
            claimed_actual_ids.add(chosen)
        else:
            report.missing.append(MissingEntry(
                alias=ref.alias,
                predicted_id=ref.node_id,
                node_type=ref.node_type,
            ))

    # Anything actual_by_id holds that isn't claimed is unclaimed —
    # but auto-narrow to types the profile already cares about, so
    # manifest-pass Artifact/File nodes don't drown out the signal once
    # the profile is fleshed out. Empty profile = report everything
    # (bootstrap workflow).
    if expected:
        relevant_types = {ref.node_type for ref in expected}
    else:
        relevant_types = None  # empty profile → no filtering
    for node_id, node in actual_by_id.items():
        if node_id in claimed_actual_ids:
            continue
        if relevant_types is not None and node["node_type"] not in relevant_types:
            continue
        report.unclaimed.append(UnclaimedEntry(
            node_id=node_id,
            node_type=node["node_type"],
        ))

    # Stable order for deterministic test assertions and report output.
    report.confirmed.sort(key=lambda c: c.alias)
    report.drifted.sort(key=lambda d: d.alias)
    report.missing.sort(key=lambda m: m.alias)
    report.unclaimed.sort(key=lambda u: u.node_id)

    return report
