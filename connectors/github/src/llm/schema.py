"""JSON Schema for grounded ontology nodes.

This module is the single source of truth for the grounding contract from
ADR-0005. Both adapters bind to ``GROUNDED_NODE_SCHEMA``:

- ``AnthropicAdapter`` passes it to ``tool-use`` as the tool's
  ``input_schema``, so Claude returns exactly this shape.
- ``OpenAIAdapter`` passes it to ``response_format`` with type
  ``json_schema``, so GPT returns exactly this shape.

Validation:
- ``validate_grounded_node`` raises ``GroundingValidationError`` on
  malformed input — the same checks both adapters' outputs must pass
  before the verification step.
- ``GROUNDED_NODE_SCHEMA`` is exported as a plain dict so it can be
  serialized into prompts, written to disk for the cache, and shipped
  to either provider's structured-output API verbatim.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Allowed values
# ---------------------------------------------------------------------------

# These must stay in sync with the ontology. The ``v1`` ontology defines
# more node types than the LLM scanner is responsible for — the LLM
# scanner only emits the four "code-shape" types. Manifest scanning
# handles the rest deterministically.
ALLOWED_NODE_TYPES: tuple[str, ...] = (
    "Tool",
    "PromptTemplate",
    "RAGIndex",
    "MemoryStore",
)

ALLOWED_CONFIDENCES: tuple[str, ...] = ("high", "medium", "low")


# ---------------------------------------------------------------------------
# JSON Schema for one grounded node
# ---------------------------------------------------------------------------

GROUNDING_BLOCK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "file_path",
        "line_start",
        "line_end",
        "file_sha256",
        "evidence",
        "confidence",
    ],
    "properties": {
        "file_path": {
            "type": "string",
            "description": (
                "Path to the source file relative to the repo root. Use "
                "forward slashes regardless of OS. Must point to an "
                "existing file the verifier can re-open."
            ),
            "minLength": 1,
        },
        "line_start": {
            "type": "integer",
            "description": "1-indexed line where the node definition begins.",
            "minimum": 1,
        },
        "line_end": {
            "type": "integer",
            "description": "1-indexed line where the node definition ends.",
            "minimum": 1,
        },
        "file_sha256": {
            "type": "string",
            "description": (
                "SHA-256 of the file's content at extraction time, lowercase "
                "hex. The verifier recomputes this before re-reading the "
                "span — drift means the file changed mid-scan and the node "
                "is rejected."
            ),
            "pattern": "^[0-9a-f]{64}$",
        },
        "evidence": {
            "type": "string",
            "description": (
                "One sentence explaining why this code span defines this "
                "node. Used for audit logs and the verification prompt."
            ),
            "minLength": 1,
            "maxLength": 500,
        },
        "confidence": {
            "type": "string",
            "description": (
                "Self-reported confidence. The platform may filter low-"
                "confidence nodes by policy."
            ),
            "enum": list(ALLOWED_CONFIDENCES),
        },
    },
}


GROUNDED_NODE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["node_type", "id", "properties", "grounding"],
    "properties": {
        "node_type": {
            "type": "string",
            "description": (
                "Ontology node type. The LLM scanner only emits the four "
                "code-shape types; manifest scanning handles the rest."
            ),
            "enum": list(ALLOWED_NODE_TYPES),
        },
        "id": {
            "type": "string",
            "description": (
                "Stable node ID of the form '<NodeType>:<name>', e.g. "
                "'Tool:export_data'. Must be unique within a scan."
            ),
            "pattern": r"^(Tool|PromptTemplate|RAGIndex|MemoryStore):[A-Za-z0-9_./@-]+$",
        },
        "properties": {
            "type": "object",
            "description": (
                "Free-form properties for the node. Each ontology type has "
                "expected keys, but extras are tolerated downstream."
            ),
            "additionalProperties": True,
        },
        "grounding": GROUNDING_BLOCK_SCHEMA,
    },
}


# ---------------------------------------------------------------------------
# Top-level extraction-response schema (what the adapter returns)
# ---------------------------------------------------------------------------

EXTRACTION_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["nodes"],
    "properties": {
        "nodes": {
            "type": "array",
            "description": (
                "Grounded ontology nodes extracted from the input. May be "
                "empty if the model concludes nothing applies."
            ),
            "items": GROUNDED_NODE_SCHEMA,
        },
    },
}


# ---------------------------------------------------------------------------
# Verification-response schema (second-pass yes/no)
# ---------------------------------------------------------------------------

VERIFICATION_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verified", "reason"],
    "properties": {
        "verified": {
            "type": "boolean",
            "description": (
                "True iff the cited code span actually defines the claimed "
                "node. False rejects the node before it reaches the graph."
            ),
        },
        "reason": {
            "type": "string",
            "description": "One sentence explaining the verification verdict.",
            "minLength": 1,
            "maxLength": 500,
        },
    },
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class GroundingValidationError(ValueError):
    """Raised when a grounded node does not match GROUNDED_NODE_SCHEMA."""


def validate_grounded_node(node: Any) -> None:
    """Validate one grounded-node dict against the schema.

    We enforce the contract manually rather than pulling in a JSON Schema
    library: the schema is small enough that hand-written checks are
    clearer (and faster), and the keys align 1:1 with the contract from
    ADR-0005, so any future change here forces a re-read of the ADR.
    """
    if not isinstance(node, dict):
        msg = f"Expected dict, got {type(node).__name__}"
        raise GroundingValidationError(msg)

    extra = set(node.keys()) - {"node_type", "id", "properties", "grounding"}
    if extra:
        msg = f"Unexpected top-level keys: {sorted(extra)}"
        raise GroundingValidationError(msg)

    node_type = node.get("node_type")
    if node_type not in ALLOWED_NODE_TYPES:
        msg = (
            f"node_type must be one of {ALLOWED_NODE_TYPES}; got "
            f"{node_type!r}"
        )
        raise GroundingValidationError(msg)

    node_id = node.get("id")
    if not isinstance(node_id, str) or ":" not in node_id:
        msg = f"id must be 'NodeType:name'; got {node_id!r}"
        raise GroundingValidationError(msg)
    id_prefix, _, id_suffix = node_id.partition(":")
    if id_prefix != node_type:
        msg = (
            f"id prefix {id_prefix!r} does not match node_type "
            f"{node_type!r} (id={node_id!r})"
        )
        raise GroundingValidationError(msg)
    if not id_suffix:
        msg = f"id must have a non-empty name after the colon; got {node_id!r}"
        raise GroundingValidationError(msg)
    # Match the regex pattern in GROUNDED_NODE_SCHEMA["properties"]["id"].
    if not all(c.isalnum() or c in "_./@-" for c in id_suffix):
        msg = (
            f"id name may only contain [A-Za-z0-9_./@-]; got "
            f"{id_suffix!r}"
        )
        raise GroundingValidationError(msg)

    if not isinstance(node.get("properties"), dict):
        msg = "properties must be a dict"
        raise GroundingValidationError(msg)

    g = node.get("grounding")
    if not isinstance(g, dict):
        msg = "grounding must be a dict"
        raise GroundingValidationError(msg)

    g_extra = set(g.keys()) - {
        "file_path", "line_start", "line_end",
        "file_sha256", "evidence", "confidence",
    }
    if g_extra:
        msg = f"Unexpected grounding keys: {sorted(g_extra)}"
        raise GroundingValidationError(msg)

    if not isinstance(g.get("file_path"), str) or not g["file_path"]:
        msg = "grounding.file_path must be a non-empty string"
        raise GroundingValidationError(msg)
    if "/" not in g["file_path"] and "\\" in g["file_path"]:
        msg = "grounding.file_path must use forward slashes, not backslashes"
        raise GroundingValidationError(msg)

    for k in ("line_start", "line_end"):
        v = g.get(k)
        if not isinstance(v, int) or isinstance(v, bool) or v < 1:
            msg = f"grounding.{k} must be a positive integer; got {v!r}"
            raise GroundingValidationError(msg)
    if g["line_end"] < g["line_start"]:
        msg = (
            f"grounding.line_end ({g['line_end']}) must be >= "
            f"line_start ({g['line_start']})"
        )
        raise GroundingValidationError(msg)

    sha = g.get("file_sha256")
    if not isinstance(sha, str) or len(sha) != 64 or any(
        c not in "0123456789abcdef" for c in sha
    ):
        msg = (
            f"grounding.file_sha256 must be 64 lowercase hex chars; "
            f"got {sha!r}"
        )
        raise GroundingValidationError(msg)

    ev = g.get("evidence")
    if not isinstance(ev, str) or not ev or len(ev) > 500:
        msg = (
            "grounding.evidence must be a non-empty string up to 500 "
            "characters"
        )
        raise GroundingValidationError(msg)

    if g.get("confidence") not in ALLOWED_CONFIDENCES:
        msg = (
            f"grounding.confidence must be one of {ALLOWED_CONFIDENCES}; "
            f"got {g.get('confidence')!r}"
        )
        raise GroundingValidationError(msg)


def validate_extraction_response(payload: Any) -> list[dict[str, Any]]:
    """Validate the adapter's extraction response and return the nodes list."""
    if not isinstance(payload, dict):
        msg = f"Extraction response must be a dict; got {type(payload).__name__}"
        raise GroundingValidationError(msg)
    if list(payload.keys()) != ["nodes"]:
        # Tolerate extra top-level keys silently — the schema disallows
        # them but real adapters sometimes wrap responses in metadata. We
        # only require ``nodes`` to be present and well-formed.
        if "nodes" not in payload:
            msg = "Extraction response missing 'nodes' field"
            raise GroundingValidationError(msg)
    nodes = payload["nodes"]
    if not isinstance(nodes, list):
        msg = "Extraction response 'nodes' must be a list"
        raise GroundingValidationError(msg)
    for i, node in enumerate(nodes):
        try:
            validate_grounded_node(node)
        except GroundingValidationError as exc:
            msg = f"nodes[{i}]: {exc}"
            raise GroundingValidationError(msg) from exc
    return nodes


def validate_verification_response(payload: Any) -> tuple[bool, str]:
    """Validate the adapter's verification response."""
    if not isinstance(payload, dict):
        msg = f"Verification response must be a dict; got {type(payload).__name__}"
        raise GroundingValidationError(msg)
    if "verified" not in payload or not isinstance(payload["verified"], bool):
        msg = "Verification response 'verified' must be a bool"
        raise GroundingValidationError(msg)
    if "reason" not in payload or not isinstance(payload["reason"], str):
        msg = "Verification response 'reason' must be a string"
        raise GroundingValidationError(msg)
    if not payload["reason"] or len(payload["reason"]) > 500:
        msg = "Verification response 'reason' must be 1..500 characters"
        raise GroundingValidationError(msg)
    return payload["verified"], payload["reason"]
