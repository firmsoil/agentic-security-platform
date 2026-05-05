"""Unit tests for the parity-diff logic — pure, no API calls."""

from __future__ import annotations

import pytest

from connectors.github.tests.parity import (
    LLM_SCOPE_NODE_TYPES,
    PropertyDiff,
    ParityReport,
    compute_parity_diff,
    filter_to_llm_scope,
)


def _node(node_type: str, name: str, **props):
    base = {
        "node_type": node_type,
        "id": f"{node_type}:{name}",
        "properties": {"name": name, **props},
    }
    return base


# ---------------------------------------------------------------------------
# filter_to_llm_scope
# ---------------------------------------------------------------------------


class TestFilterToLLMScope:
    def test_keeps_four_types(self):
        nodes = [
            _node("Tool", "x"),
            _node("PromptTemplate", "y"),
            _node("RAGIndex", "z"),
            _node("MemoryStore", "m"),
            _node("Repository", "repo"),  # filtered out
            _node("Container", "c"),       # filtered out
            _node("Artifact", "a"),        # filtered out
            _node("Model", "mod"),         # filtered out
            _node("File", "f"),            # filtered out
        ]
        kept = filter_to_llm_scope(nodes)
        types = {n["node_type"] for n in kept}
        assert types == LLM_SCOPE_NODE_TYPES

    def test_empty_input(self):
        assert filter_to_llm_scope([]) == []

    def test_node_without_type_filtered(self):
        # Defensive: don't crash on malformed input, just drop it.
        assert filter_to_llm_scope([{"id": "x"}]) == []


# ---------------------------------------------------------------------------
# Strict-match cases
# ---------------------------------------------------------------------------


class TestStrictMatch:
    def test_exact_match_no_diffs(self):
        static = [_node("Tool", "export_data", description="Write data.")]
        llm = [_node("Tool", "export_data", description="Write data.")]
        report = compute_parity_diff(static, llm)
        assert report.is_strict_match
        assert report.property_diffs == []
        assert "Byte-equal property match" in report.format_report()

    def test_description_enrichment_produces_no_recorded_diff(self):
        # Static = empty description, LLM = real description: tolerated.
        # No property diff is recorded, so the report claims byte-equality
        # of the property dicts (since the only "difference" was the
        # tolerated enrichment).
        static = [_node("Tool", "export_data", description="")]
        llm = [_node("Tool", "export_data", description="Write memory to disk.")]
        report = compute_parity_diff(static, llm)
        assert report.is_strict_match
        assert report.property_diffs == []
        assert "Byte-equal property match" in report.format_report()

    def test_strict_id_parity_with_recorded_property_diff(self):
        # When a real property diff IS recorded (missing key), the report
        # falls back to the "Strict ID parity ✓ — property diffs are
        # audit-only" message instead of the byte-equal message.
        static = [_node("PromptTemplate", "system_prompt", checksum="abc")]
        llm = [_node("PromptTemplate", "system_prompt")]
        report = compute_parity_diff(static, llm)
        assert report.is_strict_match
        assert len(report.property_diffs) == 1
        assert "Strict ID parity" in report.format_report()

    def test_property_addition_not_a_diff(self):
        # LLM emits an extra property the static scanner doesn't produce.
        # That's enrichment, not a diff (we only diff keys static produced).
        static = [_node("Tool", "export_data")]
        llm = [_node("Tool", "export_data", schema='{"type": "object"}')]
        report = compute_parity_diff(static, llm)
        assert report.is_strict_match
        assert report.property_diffs == []


# ---------------------------------------------------------------------------
# Strict-match failures
# ---------------------------------------------------------------------------


class TestStrictMatchFailures:
    def test_missing_in_llm(self):
        static = [
            _node("Tool", "export_data"),
            _node("Tool", "missed_one"),
        ]
        llm = [_node("Tool", "export_data")]
        report = compute_parity_diff(static, llm)
        assert not report.is_strict_match
        assert report.missing_in_llm == {"Tool:missed_one"}
        assert "static scanner produced but the LLM did not" in report.format_report()

    def test_extra_in_llm(self):
        static = [_node("Tool", "export_data")]
        llm = [
            _node("Tool", "export_data"),
            _node("Tool", "hallucinated"),
        ]
        report = compute_parity_diff(static, llm)
        assert not report.is_strict_match
        assert report.extra_in_llm == {"Tool:hallucinated"}
        assert "LLM produced that the static scanner did not" in report.format_report()

    def test_node_type_mismatch(self):
        static = [{"node_type": "Tool", "id": "Tool:x", "properties": {}}]
        # Same ID, different type. Schema validation would normally
        # catch this earlier, but the diff layer is defensive.
        llm = [{"node_type": "RAGIndex", "id": "Tool:x", "properties": {}}]
        report = compute_parity_diff(static, llm)
        assert not report.is_strict_match
        assert report.node_type_mismatches == [("Tool:x", "Tool", "RAGIndex")]


# ---------------------------------------------------------------------------
# Property-level diffs
# ---------------------------------------------------------------------------


class TestPropertyDiffs:
    def test_missing_property_recorded(self):
        # LLM doesn't emit a property the static scanner produced.
        # Strict ID parity holds; the missing property is informational.
        static = [_node("PromptTemplate", "system_prompt", checksum="abc")]
        llm = [_node("PromptTemplate", "system_prompt")]
        report = compute_parity_diff(static, llm)
        assert report.is_strict_match
        assert len(report.property_diffs) == 1
        diff = report.property_diffs[0]
        assert diff.node_id == "PromptTemplate:system_prompt"
        assert diff.key == "checksum"
        assert diff.is_missing
        assert "<missing>" in diff.format()

    def test_value_disagreement_recorded(self):
        static = [_node("MemoryStore", "session_memory", principal_scoped=False)]
        llm = [_node("MemoryStore", "session_memory", principal_scoped=True)]
        report = compute_parity_diff(static, llm)
        assert report.is_strict_match
        assert len(report.property_diffs) == 1
        assert report.property_diffs[0].static_value is False
        assert report.property_diffs[0].llm_value is True

    def test_description_enrichment_tolerated(self):
        # Static = empty string, LLM = real description: allowed.
        static = [_node("Tool", "x", description="")]
        llm = [_node("Tool", "x", description="useful tool that does X")]
        report = compute_parity_diff(static, llm)
        assert report.property_diffs == []

    def test_description_change_not_tolerated(self):
        # Both non-empty but different: that IS a real disagreement.
        static = [_node("Tool", "x", description="written")]
        llm = [_node("Tool", "x", description="rewritten")]
        report = compute_parity_diff(static, llm)
        assert len(report.property_diffs) == 1
        assert report.property_diffs[0].key == "description"


# ---------------------------------------------------------------------------
# Filtering applied during diff
# ---------------------------------------------------------------------------


class TestFilteringDuringDiff:
    def test_repository_node_ignored_on_static_side(self):
        # The static scanner emits Repository/Container/etc. nodes the LLM
        # scanner doesn't extract. The diff layer filters before comparing
        # so those don't show up as missing_in_llm.
        static = [
            _node("Tool", "export_data"),
            _node("Repository", "vulnerable-rag-app"),
            _node("Container", "vulnerable-rag-app"),
        ]
        llm = [_node("Tool", "export_data")]
        report = compute_parity_diff(static, llm)
        assert report.is_strict_match
        assert "Repository:vulnerable-rag-app" not in report.missing_in_llm

    def test_grounding_block_on_llm_side_does_not_break_diff(self):
        # The LLM scanner attaches a 'grounding' block at top level.
        # Properties live one level deeper, so the diff is unaffected.
        static = [_node("Tool", "export_data")]
        llm_with_grounding = {
            "node_type": "Tool",
            "id": "Tool:export_data",
            "properties": {"name": "export_data"},
            "grounding": {
                "file_path": "tools.py", "line_start": 1, "line_end": 5,
                "file_sha256": "0" * 64, "evidence": "x", "confidence": "high",
            },
        }
        report = compute_parity_diff(static, [llm_with_grounding])
        assert report.is_strict_match
        assert report.property_diffs == []


# ---------------------------------------------------------------------------
# Empty cases
# ---------------------------------------------------------------------------


class TestEmptyInputs:
    def test_both_empty_passes(self):
        report = compute_parity_diff([], [])
        assert report.is_strict_match
        assert report.static_ids == set()
        assert report.llm_ids == set()

    def test_static_only_misses_everything(self):
        report = compute_parity_diff([_node("Tool", "x")], [])
        assert not report.is_strict_match
        assert report.missing_in_llm == {"Tool:x"}

    def test_llm_only_extras_everything(self):
        report = compute_parity_diff([], [_node("Tool", "x")])
        assert not report.is_strict_match
        assert report.extra_in_llm == {"Tool:x"}
