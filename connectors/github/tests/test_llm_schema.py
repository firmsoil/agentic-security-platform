"""Schema validation tests for the LLM scanner — no API calls."""

from __future__ import annotations

import hashlib
import json

import pytest

from connectors.github.src.llm.schema import (
    ALLOWED_NODE_TYPES,
    EXTRACTION_RESPONSE_SCHEMA,
    GROUNDED_NODE_SCHEMA,
    GroundingValidationError,
    validate_extraction_response,
    validate_grounded_node,
    validate_verification_response,
)

_FAKE_SHA = hashlib.sha256(b"fake content").hexdigest()


def _good_node(**overrides):
    base = {
        "node_type": "Tool",
        "id": "Tool:export_data",
        "properties": {"name": "export_data", "scope": "filesystem_write"},
        "grounding": {
            "file_path": "src/tools.py",
            "line_start": 10,
            "line_end": 25,
            "file_sha256": _FAKE_SHA,
            "evidence": "Function export_data declared as a tool.",
            "confidence": "high",
        },
    }
    base.update(overrides)
    return base


def _good_grounding(**overrides):
    base = {
        "file_path": "src/tools.py",
        "line_start": 10,
        "line_end": 25,
        "file_sha256": _FAKE_SHA,
        "evidence": "Function export_data declared as a tool.",
        "confidence": "high",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Top-level schema shape
# ---------------------------------------------------------------------------


class TestSchemaShape:
    def test_grounded_node_schema_is_strict(self):
        # Both adapters depend on additionalProperties=False and explicit
        # required lists. Regression-test the schema dict directly.
        assert GROUNDED_NODE_SCHEMA["additionalProperties"] is False
        assert set(GROUNDED_NODE_SCHEMA["required"]) == {
            "node_type", "id", "properties", "grounding",
        }
        node_type_def = GROUNDED_NODE_SCHEMA["properties"]["node_type"]
        assert set(node_type_def["enum"]) == set(ALLOWED_NODE_TYPES)

    def test_grounding_block_required_fields(self):
        g = GROUNDED_NODE_SCHEMA["properties"]["grounding"]
        assert g["additionalProperties"] is False
        assert set(g["required"]) == {
            "file_path", "line_start", "line_end",
            "file_sha256", "evidence", "confidence",
        }

    def test_extraction_response_wraps_nodes(self):
        assert "nodes" in EXTRACTION_RESPONSE_SCHEMA["properties"]
        assert EXTRACTION_RESPONSE_SCHEMA["properties"]["nodes"]["type"] == "array"


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


class TestValidateGroundedNodeHappyPaths:
    @pytest.mark.parametrize("node_type,id_name", [
        ("Tool", "Tool:export_data"),
        ("Tool", "Tool:fetch_url"),
        ("PromptTemplate", "PromptTemplate:system_prompt"),
        ("RAGIndex", "RAGIndex:corpus"),
        ("MemoryStore", "MemoryStore:session_memory"),
        ("Tool", "Tool:com.example.tools.ExportData"),  # dots ok
        ("Tool", "Tool:@scope/some-tool"),               # npm-ish ok
    ])
    def test_accepts_valid_node(self, node_type, id_name):
        node = _good_node(node_type=node_type, id=id_name)
        validate_grounded_node(node)  # no raise

    def test_extraction_response_passes_through(self):
        nodes = validate_extraction_response({"nodes": [_good_node()]})
        assert len(nodes) == 1

    def test_empty_nodes_list_is_valid(self):
        nodes = validate_extraction_response({"nodes": []})
        assert nodes == []


# ---------------------------------------------------------------------------
# Rejection paths
# ---------------------------------------------------------------------------


class TestValidateGroundedNodeRejections:
    def test_rejects_unknown_node_type(self):
        with pytest.raises(GroundingValidationError, match="node_type"):
            validate_grounded_node(_good_node(node_type="Repository"))

    def test_rejects_id_without_colon(self):
        with pytest.raises(GroundingValidationError, match="NodeType:name"):
            validate_grounded_node(_good_node(id="export_data"))

    def test_rejects_id_with_empty_name(self):
        with pytest.raises(GroundingValidationError, match="non-empty name"):
            validate_grounded_node(_good_node(id="Tool:"))

    def test_rejects_id_prefix_mismatch(self):
        with pytest.raises(GroundingValidationError, match="does not match node_type"):
            validate_grounded_node(_good_node(node_type="Tool", id="MemoryStore:x"))

    def test_rejects_id_with_disallowed_chars(self):
        with pytest.raises(GroundingValidationError, match=r"\[A-Za-z0-9"):
            validate_grounded_node(_good_node(id="Tool:has spaces"))

    def test_rejects_extra_top_level_keys(self):
        node = _good_node()
        node["extra"] = "hi"
        with pytest.raises(GroundingValidationError, match="Unexpected top-level"):
            validate_grounded_node(node)

    def test_rejects_non_dict_properties(self):
        with pytest.raises(GroundingValidationError, match="properties"):
            validate_grounded_node(_good_node(properties=["a", "b"]))

    def test_rejects_missing_grounding(self):
        node = _good_node()
        del node["grounding"]
        with pytest.raises(GroundingValidationError):
            validate_grounded_node(node)

    def test_rejects_grounding_extra_keys(self):
        node = _good_node()
        node["grounding"]["extra"] = "hi"
        with pytest.raises(GroundingValidationError, match="Unexpected grounding keys"):
            validate_grounded_node(node)

    def test_rejects_empty_file_path(self):
        node = _good_node()
        node["grounding"]["file_path"] = ""
        with pytest.raises(GroundingValidationError, match="file_path"):
            validate_grounded_node(node)

    def test_rejects_backslash_paths(self):
        node = _good_node()
        node["grounding"]["file_path"] = "src\\tools.py"
        with pytest.raises(GroundingValidationError, match="forward slashes"):
            validate_grounded_node(node)

    def test_rejects_non_positive_line_start(self):
        node = _good_node()
        node["grounding"]["line_start"] = 0
        with pytest.raises(GroundingValidationError, match="line_start"):
            validate_grounded_node(node)

    def test_rejects_line_end_before_start(self):
        node = _good_node()
        node["grounding"]["line_start"] = 50
        node["grounding"]["line_end"] = 5
        with pytest.raises(GroundingValidationError, match=">= line_start"):
            validate_grounded_node(node)

    def test_rejects_short_sha(self):
        node = _good_node()
        node["grounding"]["file_sha256"] = "abc123"
        with pytest.raises(GroundingValidationError, match="64 lowercase hex"):
            validate_grounded_node(node)

    def test_rejects_uppercase_sha(self):
        node = _good_node()
        node["grounding"]["file_sha256"] = _FAKE_SHA.upper()
        with pytest.raises(GroundingValidationError, match="64 lowercase hex"):
            validate_grounded_node(node)

    def test_rejects_empty_evidence(self):
        node = _good_node()
        node["grounding"]["evidence"] = ""
        with pytest.raises(GroundingValidationError, match="evidence"):
            validate_grounded_node(node)

    def test_rejects_overlong_evidence(self):
        node = _good_node()
        node["grounding"]["evidence"] = "x" * 501
        with pytest.raises(GroundingValidationError, match="500"):
            validate_grounded_node(node)

    def test_rejects_unknown_confidence(self):
        node = _good_node()
        node["grounding"]["confidence"] = "very_high"
        with pytest.raises(GroundingValidationError, match="confidence"):
            validate_grounded_node(node)

    def test_extraction_response_index_in_error(self):
        good = _good_node()
        bad = _good_node(id="Tool:has spaces")
        with pytest.raises(GroundingValidationError, match="nodes\\[1\\]"):
            validate_extraction_response({"nodes": [good, bad]})


# ---------------------------------------------------------------------------
# Verification response
# ---------------------------------------------------------------------------


class TestValidateVerificationResponse:
    def test_accepts_verified_true(self):
        verified, reason = validate_verification_response({
            "verified": True,
            "reason": "The cited span declares the tool.",
        })
        assert verified is True
        assert reason

    def test_accepts_verified_false(self):
        verified, reason = validate_verification_response({
            "verified": False,
            "reason": "The span declares a different function.",
        })
        assert verified is False

    def test_rejects_non_bool_verified(self):
        with pytest.raises(GroundingValidationError, match="verified"):
            validate_verification_response({"verified": "yes", "reason": "ok"})

    def test_rejects_empty_reason(self):
        with pytest.raises(GroundingValidationError):
            validate_verification_response({"verified": True, "reason": ""})

    def test_rejects_overlong_reason(self):
        with pytest.raises(GroundingValidationError, match="500"):
            validate_verification_response({
                "verified": True,
                "reason": "x" * 501,
            })
