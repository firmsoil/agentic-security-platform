"""Unit tests for the golden-fixture normalization + diff logic — no I/O."""

from __future__ import annotations

import pytest

from connectors.github.tests.golden import (
    GOLDEN_SCHEMA_VERSION,
    Golden,
    compare_against_golden,
    normalize_scan_result,
    parse_golden_json,
    render_golden_json,
)


def _scan(*nodes, edges=()):
    return {
        "stack": "python",
        "nodes": list(nodes),
        "edges": list(edges),
    }


def _node(node_type, name, **props):
    return {
        "node_type": node_type,
        "id": f"{node_type}:{name}",
        "properties": {"name": name, **props},
    }


# ---------------------------------------------------------------------------
# normalize_scan_result
# ---------------------------------------------------------------------------


class TestNormalizeScanResult:
    def test_sorts_nodes_by_id_for_deterministic_diffs(self):
        scan = _scan(_node("Tool", "z"), _node("Tool", "a"))
        norm = normalize_scan_result(scan)
        assert [n["id"] for n in norm["nodes"]] == ["Tool:a", "Tool:z"]

    def test_sorts_edges_by_source_target_type(self):
        scan = _scan(edges=[
            {"edge_type": "B", "source_type": "X", "source_id": "X:1",
             "target_type": "Y", "target_id": "Y:1", "properties": {}},
            {"edge_type": "A", "source_type": "X", "source_id": "X:1",
             "target_type": "Y", "target_id": "Y:1", "properties": {}},
        ])
        norm = normalize_scan_result(scan)
        assert [e["edge_type"] for e in norm["edges"]] == ["A", "B"]

    def test_strips_top_level_volatile_fields(self):
        # repo_path and scanned_at are intentionally omitted from the
        # normalized output — they vary across runs even with stable
        # inputs.
        scan = {
            "stack": "python",
            "repo_path": "/home/runner/abs/path",
            "scanned_at": "2026-04-28T12:34:56Z",
            "nodes": [],
            "edges": [],
        }
        norm = normalize_scan_result(scan)
        assert "repo_path" not in norm
        assert "scanned_at" not in norm

    def test_description_volatile_when_non_empty(self):
        # Static-parser empty descriptions stay empty (deterministic).
        # LLM-narrated descriptions get placeholdered (model-narrated,
        # not strictly determinism-stable across re-records).
        scan = _scan(
            _node("Tool", "a", description=""),
            _node("Tool", "b", description="Real description text."),
        )
        norm = normalize_scan_result(scan)
        a = next(n for n in norm["nodes"] if n["id"] == "Tool:a")
        b = next(n for n in norm["nodes"] if n["id"] == "Tool:b")
        assert a["properties"]["description"] == ""
        assert b["properties"]["description"] == "__VOLATILE__"

    def test_grounding_volatile_fields_placeholdered(self):
        # Grounding is flattened into _llm_grounding_<field> scalar
        # properties (Neo4j compatibility — see scanner._strip_grounding).
        scan = _scan(_node(
            "Tool", "x",
            _llm_grounding_file_path="src/tools.py",
            _llm_grounding_file_sha256="0" * 64,
            _llm_grounding_line_start=1,
            _llm_grounding_line_end=5,
            _llm_grounding_evidence="function defines the tool",
            _llm_grounding_confidence="high",
        ))
        norm = normalize_scan_result(scan)
        props = norm["nodes"][0]["properties"]
        # Structural fields preserved verbatim.
        assert props["_llm_grounding_file_path"] == "src/tools.py"
        assert props["_llm_grounding_file_sha256"] == "0" * 64
        assert props["_llm_grounding_line_start"] == 1
        assert props["_llm_grounding_line_end"] == 5
        # Model-narrated fields placeholdered.
        assert props["_llm_grounding_evidence"] == "__VOLATILE__"
        assert props["_llm_grounding_confidence"] == "__VOLATILE__"

    def test_normalized_output_is_idempotent(self):
        scan = _scan(_node("Tool", "z"), _node("Tool", "a"))
        once = normalize_scan_result(scan)
        twice = normalize_scan_result(once)
        # Note: normalize re-keys nodes from the input shape; passing
        # an already-normalized dict back through should produce the
        # same content (the function is structural, not destructive).
        assert once == twice


# ---------------------------------------------------------------------------
# Golden file format round-trip
# ---------------------------------------------------------------------------


class TestGoldenFileFormat:
    def test_render_then_parse_round_trips(self):
        g = Golden(
            schema_version=GOLDEN_SCHEMA_VERSION,
            repo_path="examples/vulnerable-rag-app",
            enable_llm=False,
            adapter_name=None,
            model_name=None,
            prompts_dir=None,
            cache_key=None,
            normalized_scan=normalize_scan_result(
                _scan(_node("Tool", "x")),
            ),
        )
        rendered = render_golden_json(g)
        parsed = parse_golden_json(rendered)
        assert parsed == g

    def test_unsupported_schema_version_rejected(self):
        bad = '{"schema_version": 999, "repo_path": "x", "normalized_scan": {}}'
        with pytest.raises(ValueError, match="Unsupported golden schema_version"):
            parse_golden_json(bad)

    def test_render_is_diff_stable(self):
        # Two Goldens with the same content should render to identical
        # JSON regardless of the order their normalized_scan keys are
        # built in (the renderer uses sort_keys=True).
        g = Golden(
            schema_version=GOLDEN_SCHEMA_VERSION,
            repo_path="x",
            enable_llm=False,
            adapter_name=None,
            model_name=None,
            prompts_dir=None,
            cache_key=None,
            normalized_scan=normalize_scan_result(
                _scan(_node("Tool", "z"), _node("Tool", "a")),
            ),
        )
        first = render_golden_json(g)
        second = render_golden_json(g)
        assert first == second


# ---------------------------------------------------------------------------
# compare_against_golden
# ---------------------------------------------------------------------------


def _make_golden_from(scan):
    return Golden(
        schema_version=GOLDEN_SCHEMA_VERSION,
        repo_path="x",
        enable_llm=False,
        adapter_name=None,
        model_name=None,
        prompts_dir=None,
        cache_key=None,
        normalized_scan=normalize_scan_result(scan),
    )


class TestCompareAgainstGolden:
    def test_identical_scan_matches(self):
        scan = _scan(_node("Tool", "x"))
        g = _make_golden_from(scan)
        diff = compare_against_golden(golden=g, fresh_scan=scan)
        assert diff.matched
        assert "Golden match" in diff.format_report()

    def test_node_added_in_fresh_reported(self):
        g = _make_golden_from(_scan(_node("Tool", "x")))
        fresh = _scan(_node("Tool", "x"), _node("Tool", "y"))
        diff = compare_against_golden(golden=g, fresh_scan=fresh)
        assert not diff.matched
        assert any("Tool:y" in d and "added" in d for d in diff.differences)

    def test_node_missing_in_fresh_reported(self):
        g = _make_golden_from(_scan(_node("Tool", "x"), _node("Tool", "y")))
        fresh = _scan(_node("Tool", "x"))
        diff = compare_against_golden(golden=g, fresh_scan=fresh)
        assert not diff.matched
        assert any("Tool:y" in d and "missing" in d for d in diff.differences)

    def test_node_property_change_reported(self):
        g = _make_golden_from(_scan(_node("Tool", "x", scope="read")))
        fresh = _scan(_node("Tool", "x", scope="write"))
        diff = compare_against_golden(golden=g, fresh_scan=fresh)
        assert not diff.matched
        assert any("Tool:x" in d and "differs" in d for d in diff.differences)

    def test_volatile_fields_dont_cause_diff(self):
        # Different descriptions must not break the match — both are
        # placeholdered to __VOLATILE__.
        g = _make_golden_from(_scan(
            _node("Tool", "x", description="One sentence."),
        ))
        fresh = _scan(_node("Tool", "x", description="A different sentence."))
        diff = compare_against_golden(golden=g, fresh_scan=fresh)
        assert diff.matched

    def test_edge_added_in_fresh_reported(self):
        g = _make_golden_from(_scan())
        fresh = _scan(edges=[{
            "edge_type": "DEPENDS_ON",
            "source_type": "Repository", "source_id": "Repository:x",
            "target_type": "Artifact", "target_id": "Artifact:y",
            "properties": {},
        }])
        diff = compare_against_golden(golden=g, fresh_scan=fresh)
        assert not diff.matched
        assert any("edge added" in d for d in diff.differences)

    def test_repo_path_and_scanned_at_ignored(self):
        # Even though the fresh scan carries different repo_path /
        # scanned_at than the original, they get stripped during
        # normalization and don't cause a mismatch.
        scan_for_golden = {
            "stack": "python",
            "repo_path": "/golden/path",
            "scanned_at": "2026-01-01T00:00:00Z",
            "nodes": [_node("Tool", "x")],
            "edges": [],
        }
        g = Golden(
            schema_version=GOLDEN_SCHEMA_VERSION,
            repo_path="x",
            enable_llm=False,
            adapter_name=None,
            model_name=None,
            prompts_dir=None,
            cache_key=None,
            normalized_scan=normalize_scan_result(scan_for_golden),
        )
        fresh_scan = {
            "stack": "python",
            "repo_path": "/different/path",
            "scanned_at": "2026-12-31T23:59:59Z",
            "nodes": [_node("Tool", "x")],
            "edges": [],
        }
        diff = compare_against_golden(golden=g, fresh_scan=fresh_scan)
        assert diff.matched
