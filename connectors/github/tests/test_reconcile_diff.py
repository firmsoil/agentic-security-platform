"""Reconciliation diff tests — pure, no API calls."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from connectors.github.tests.reconcile import (
    ConfirmedEntry,
    DriftedEntry,
    MissingEntry,
    UnclaimedEntry,
    reconcile,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Ref:
    """Stand-in for TargetProfile NodeRef — only the three fields the
    reconciler reads."""
    alias: str
    node_id: str
    node_type: str


def _node(node_type: str, name: str):
    return {
        "node_type": node_type,
        "id": f"{node_type}:{name}",
        "properties": {"name": name},
    }


# ---------------------------------------------------------------------------
# Confirmed path
# ---------------------------------------------------------------------------


class TestConfirmed:
    def test_exact_match_confirmed(self):
        expected = [_Ref("tool", "Tool:export_data", "Tool")]
        actual = [_node("Tool", "export_data")]
        report = reconcile(expected=expected, actual_nodes=actual)
        assert report.is_clean
        assert len(report.confirmed) == 1
        assert report.confirmed[0].alias == "tool"
        assert report.drifted == []
        assert report.missing == []
        assert report.unclaimed == []

    def test_multiple_exact_matches(self):
        expected = [
            _Ref("repo", "Repository:demo", "Repository"),
            _Ref("container", "Container:demo", "Container"),
            _Ref("tool", "Tool:export_data", "Tool"),
        ]
        actual = [
            _node("Repository", "demo"),
            _node("Container", "demo"),
            _node("Tool", "export_data"),
        ]
        report = reconcile(expected=expected, actual_nodes=actual)
        assert report.is_clean
        assert len(report.confirmed) == 3
        # Stable alphabetical order on alias.
        assert [c.alias for c in report.confirmed] == [
            "container", "repo", "tool",
        ]


# ---------------------------------------------------------------------------
# Drifted path — predicted ID not found, but a same-type sibling was
# ---------------------------------------------------------------------------


class TestDrifted:
    def test_single_same_type_candidate_treated_as_drift(self):
        expected = [_Ref("tool", "Tool:getBookingDetails", "Tool")]
        actual = [_node("Tool", "bookingDetails")]
        report = reconcile(expected=expected, actual_nodes=actual)
        assert not report.is_clean
        assert len(report.drifted) == 1
        d = report.drifted[0]
        assert d.alias == "tool"
        assert d.predicted_id == "Tool:getBookingDetails"
        assert d.actual_id == "Tool:bookingDetails"
        assert d.node_type == "Tool"
        # Suggested edit is one line per node, ready to paste into YAML.
        assert "expected_nodes.tool.id" in d.suggested_edit()
        assert "Tool:getBookingDetails" in d.suggested_edit()
        assert "Tool:bookingDetails" in d.suggested_edit()
        # The drifted actual is "claimed" — it's not also reported as unclaimed.
        assert report.unclaimed == []

    def test_multiple_same_type_candidates_picks_first_sorted(self):
        # Three Tools in the scan, only one prediction. The reconciler
        # picks the alphabetically first one as the drift candidate; the
        # other two become unclaimed (legitimately — extra tools the
        # profile doesn't reference).
        expected = [_Ref("tool", "Tool:foo", "Tool")]
        actual = [
            _node("Tool", "alpha"),
            _node("Tool", "beta"),
            _node("Tool", "gamma"),
        ]
        report = reconcile(expected=expected, actual_nodes=actual)
        assert len(report.drifted) == 1
        assert report.drifted[0].actual_id == "Tool:alpha"  # first sorted
        assert len(report.unclaimed) == 2
        unclaimed_ids = {u.node_id for u in report.unclaimed}
        assert unclaimed_ids == {"Tool:beta", "Tool:gamma"}

    def test_two_predictions_two_actuals_both_drift_no_double_claim(self):
        # The reconciler must not claim the same actual ID for two
        # different profile aliases.
        expected = [
            _Ref("tool_a", "Tool:foo", "Tool"),
            _Ref("tool_b", "Tool:bar", "Tool"),
        ]
        actual = [
            _node("Tool", "alpha"),
            _node("Tool", "beta"),
        ]
        report = reconcile(expected=expected, actual_nodes=actual)
        assert len(report.drifted) == 2
        actual_ids = {d.actual_id for d in report.drifted}
        assert actual_ids == {"Tool:alpha", "Tool:beta"}
        # No unclaimed — both candidates were consumed.
        assert report.unclaimed == []


# ---------------------------------------------------------------------------
# Missing path — predicted, no candidate at all
# ---------------------------------------------------------------------------


class TestMissing:
    def test_no_same_type_node_means_missing(self):
        expected = [_Ref("rag_index", "RAGIndex:corpus", "RAGIndex")]
        actual = [_node("Tool", "x"), _node("Repository", "demo")]
        report = reconcile(expected=expected, actual_nodes=actual)
        assert len(report.missing) == 1
        m = report.missing[0]
        assert m.alias == "rag_index"
        assert m.predicted_id == "RAGIndex:corpus"
        assert m.node_type == "RAGIndex"
        assert "no RAGIndex nodes" in report.format_report()

    def test_drift_consumes_candidate_so_second_prediction_is_missing(self):
        # Two predictions of the same type, only one candidate in actual.
        # The first (alphabetical) consumes the candidate as drift; the
        # second is reported as missing.
        expected = [
            _Ref("tool_a", "Tool:foo", "Tool"),
            _Ref("tool_b", "Tool:bar", "Tool"),
        ]
        actual = [_node("Tool", "alpha")]
        report = reconcile(expected=expected, actual_nodes=actual)
        assert len(report.drifted) == 1
        assert len(report.missing) == 1
        # The drift goes to whichever alias was processed first; the
        # other becomes missing. With single-actual the consumption
        # rule is deterministic.
        drifted_alias = report.drifted[0].alias
        missing_alias = report.missing[0].alias
        assert {drifted_alias, missing_alias} == {"tool_a", "tool_b"}


# ---------------------------------------------------------------------------
# Unclaimed path — actual produced, profile didn't reference
# ---------------------------------------------------------------------------


class TestUnclaimed:
    def test_actual_node_with_no_prediction_is_unclaimed_when_profile_empty(self):
        # Empty profile = bootstrap mode = report everything so the user
        # can see what the scanner produced and paste IDs into the
        # profile.
        expected = []
        actual = [_node("Tool", "extra")]
        report = reconcile(expected=expected, actual_nodes=actual)
        assert not report.is_clean
        assert len(report.unclaimed) == 1
        assert report.unclaimed[0].node_id == "Tool:extra"

    def test_unclaimed_filtered_to_relevant_types_only(self):
        # The profile only cares about Tool. The scanner produced an
        # extra Tool (legitimate unclaimed) AND extra Artifact and File
        # nodes (manifest-pass noise the profile shouldn't have to
        # claim). Only the Tool unclaimed should report.
        expected = [_Ref("tool", "Tool:foo", "Tool")]
        actual = [
            _node("Tool", "foo"),
            _node("Tool", "extra"),
            _node("Artifact", "fastapi"),
            _node("Artifact", "httpx"),
            _node("File", "shipping-faq.md"),
        ]
        report = reconcile(expected=expected, actual_nodes=actual)
        assert len(report.confirmed) == 1
        unclaimed_ids = {u.node_id for u in report.unclaimed}
        assert unclaimed_ids == {"Tool:extra"}
        # Artifact and File noise dropped — profile doesn't list those types.

    def test_unclaimed_only_when_no_drift_consumed(self):
        # The drifted candidate is claimed, so it doesn't double-up
        # as unclaimed. MemoryStore IS in expected (so its type is in
        # the auto-narrow set) and the extra MemoryStore is reported.
        expected = [
            _Ref("tool", "Tool:foo", "Tool"),
            _Ref("memory", "MemoryStore:something", "MemoryStore"),
        ]
        actual = [
            _node("Tool", "drifted_target"),
            _node("MemoryStore", "something"),
            _node("MemoryStore", "extra"),
        ]
        report = reconcile(expected=expected, actual_nodes=actual)
        assert len(report.drifted) == 1
        unclaimed_ids = {u.node_id for u in report.unclaimed}
        assert unclaimed_ids == {"MemoryStore:extra"}


# ---------------------------------------------------------------------------
# Clean / dirty determination
# ---------------------------------------------------------------------------


class TestIsClean:
    def test_empty_inputs_is_clean(self):
        report = reconcile(expected=[], actual_nodes=[])
        assert report.is_clean
        assert "Clean reconciliation" in report.format_report()

    def test_only_drifted_is_dirty(self):
        report = reconcile(
            expected=[_Ref("t", "Tool:a", "Tool")],
            actual_nodes=[_node("Tool", "b")],
        )
        assert not report.is_clean
        assert "Suggested next" in report.format_report()

    def test_only_unclaimed_is_dirty(self):
        report = reconcile(expected=[], actual_nodes=[_node("Tool", "x")])
        assert not report.is_clean

    def test_only_missing_is_dirty(self):
        report = reconcile(
            expected=[_Ref("t", "Tool:a", "Tool")],
            actual_nodes=[],
        )
        assert not report.is_clean


# ---------------------------------------------------------------------------
# Realistic mixed scenario — what week-3 reconciliation actually looks like
# ---------------------------------------------------------------------------


def test_realistic_mixed_scenario_for_j1_dispatcher_output():
    """Simulates running reconcile against J1 (customer-support-agent)
    where some PREDICTED IDs match, one drifted, one missed (no corpus
    in the example), and the LLM scanner found an extra tool."""
    expected = [
        _Ref("repo", "Repository:customer-support-agent-example", "Repository"),
        _Ref("container", "Container:customer-support-agent-example", "Container"),
        _Ref("model", "Model:openai:gpt-4o", "Model"),
        _Ref("tool", "Tool:getBookingDetails", "Tool"),
        _Ref("prompt_template", "PromptTemplate:chat_system_prompt", "PromptTemplate"),
        _Ref("rag_index", "RAGIndex:terms-of-use", "RAGIndex"),
        _Ref("memory_store", "MemoryStore:chatMemory", "MemoryStore"),
    ]
    actual = [
        # Confirmed:
        _node("Repository", "customer-support-agent-example"),
        _node("Container", "customer-support-agent-example"),
        _node("Model", "openai:gpt-4o"),
        _node("Tool", "getBookingDetails"),
        # Drifted: profile predicted "chat_system_prompt", actual is just "system":
        _node("PromptTemplate", "system"),
        # Drifted: profile predicted "chatMemory", actual is "messageWindowChatMemory":
        _node("MemoryStore", "messageWindowChatMemory"),
        # Unclaimed: extra Tool the LLM found — likely also @Tool-annotated.
        _node("Tool", "cancelBooking"),
        # Missing entirely: no RAGIndex (the example doesn't ship a corpus).
    ]

    report = reconcile(expected=expected, actual_nodes=actual)

    confirmed_aliases = {c.alias for c in report.confirmed}
    assert confirmed_aliases == {"repo", "container", "model", "tool"}

    drifted_aliases = {d.alias for d in report.drifted}
    assert drifted_aliases == {"prompt_template", "memory_store"}

    missing_aliases = {m.alias for m in report.missing}
    assert missing_aliases == {"rag_index"}

    unclaimed_ids = {u.node_id for u in report.unclaimed}
    assert unclaimed_ids == {"Tool:cancelBooking"}

    assert not report.is_clean
    assert report.expected_count == 7

    # Format report should be readable and contain the suggested edits.
    out = report.format_report()
    assert "CONFIRMED (4)" in out
    assert "DRIFTED (2)" in out
    assert "MISSING (1)" in out
    assert "UNCLAIMED (1)" in out
    assert "expected_nodes.prompt_template.id" in out
    assert "expected_nodes.memory_store.id" in out
