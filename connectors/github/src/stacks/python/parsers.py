"""Pure-function parsers for repository artifacts (Python stack).

Each parser reads a file or directory and returns typed dicts ready for
``Neo4jGraphStore.upsert_node``.  No network I/O, no graph I/O, no imports
from the scanned code (we use ``ast.parse`` — never ``exec`` or ``import``).

Security note
-------------
These parsers are designed to run on *untrusted* repositories.  Tool-schema
extraction and prompt-template extraction both use ``ast.literal_eval`` on
AST nodes.  If a value is not a literal, we skip it and log a warning rather
than evaluating arbitrary code.
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# requirements.txt
# ---------------------------------------------------------------------------

# Matches lines like:  anthropic>=0.40   or   fastapi>=0.115
_REQ_LINE_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?)"
    r"(?P<extras>\[.+?\])?"
    r"(?P<specifier>[><=!~].+)?$"
)


def parse_requirements(path: Path) -> list[dict[str, str]]:
    """Parse a ``requirements.txt`` into a list of ``{name, specifier}`` dicts.

    Comments and blank lines are ignored.  This is intentionally simple; we
    are not trying to resolve the full PEP 508 grammar — just extract names
    and version specifiers for dependency-graph construction.
    """
    results: list[dict[str, str]] = []
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        m = _REQ_LINE_RE.match(line)
        if m:
            results.append({
                "name": m.group("name"),
                "specifier": (m.group("specifier") or "").strip(),
            })
        else:
            log.warning("Unparsable requirements line: %r", line)
    return results


# ---------------------------------------------------------------------------
# tools.py  — tool-schema extraction via AST
# ---------------------------------------------------------------------------

def _try_literal_eval(node: ast.expr) -> Any | None:
    """Attempt ``ast.literal_eval`` on an AST node.  Return None on failure."""
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, RecursionError):
        return None


def parse_tool_schemas(path: Path) -> list[dict[str, Any]]:
    """Extract tool-schema dicts from a Python file.

    Strategy:
      1. AST-parse the file.
      2. Find all top-level ``Assign`` / ``AnnAssign`` whose target name ends
         with ``_TOOL`` or equals ``TOOL_SCHEMAS``.
      3. For ``*_TOOL`` names, ``ast.literal_eval`` the value — it should be a
         dict with ``name``, ``description``, ``input_schema``.
      4. For ``TOOL_SCHEMAS`` (a list), eval each element.

    Returns a list of dicts, each representing a ``Tool`` ontology node::

        {"node_type": "Tool", "id": ..., "properties": {"name": ..., ...}}
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    raw_schemas: list[dict[str, Any]] = []

    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue

        # Determine the variable name.
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        elif isinstance(node, ast.AnnAssign) and node.target:
            target = node.target
        else:
            continue
        if not isinstance(target, ast.Name):
            continue
        var_name: str = target.id

        if var_name.endswith("_TOOL"):
            val = _try_literal_eval(node.value)
            if isinstance(val, dict) and "name" in val:
                raw_schemas.append(val)
        elif var_name == "TOOL_SCHEMAS":
            val = _try_literal_eval(node.value)
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict) and "name" in item:
                        raw_schemas.append(item)

    # Deduplicate by tool name (TOOL_SCHEMAS may reference the same dicts).
    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    for schema in raw_schemas:
        name = schema["name"]
        if name in seen:
            continue
        seen.add(name)
        results.append({
            "node_type": "Tool",
            "id": f"Tool:{name}",
            "properties": {
                "name": name,
                "description": schema.get("description", ""),
                "schema": json.dumps(schema.get("input_schema", {}), sort_keys=True),
            },
        })
    return results


# ---------------------------------------------------------------------------
# model.py  — prompt-template extraction via AST
# ---------------------------------------------------------------------------

def parse_prompt_template(path: Path) -> dict[str, Any] | None:
    """Extract the ``SYSTEM_PROMPT`` constant from a Python file.

    Returns a dict representing a ``PromptTemplate`` ontology node, or None
    if no ``SYSTEM_PROMPT`` assignment is found.
    """
    tree = ast.parse(path.read_text(), filename=str(path))

    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        elif isinstance(node, ast.AnnAssign) and node.target:
            target = node.target
        else:
            continue
        if not isinstance(target, ast.Name):
            continue
        if target.id != "SYSTEM_PROMPT":
            continue

        val = _try_literal_eval(node.value)
        if not isinstance(val, str):
            log.warning("SYSTEM_PROMPT is not a string literal; skipping")
            continue

        checksum = hashlib.sha256(val.encode()).hexdigest()
        return {
            "node_type": "PromptTemplate",
            "id": "PromptTemplate:system_prompt",
            "properties": {
                "name": "system_prompt",
                "version": "1",
                "checksum": checksum,
            },
        }
    return None


# ---------------------------------------------------------------------------
# corpus/  — RAG index + file listing
# ---------------------------------------------------------------------------

def parse_corpus(corpus_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Enumerate a corpus directory into a ``RAGIndex`` node and ``File`` nodes.

    Returns ``(rag_index_node, [file_nodes])``.
    """
    rag_index: dict[str, Any] = {
        "node_type": "RAGIndex",
        "id": f"RAGIndex:{corpus_dir.name}",
        "properties": {
            "name": corpus_dir.name,
        },
    }

    file_nodes: list[dict[str, Any]] = []
    if corpus_dir.is_dir():
        for file_path in sorted(corpus_dir.iterdir()):
            if file_path.is_file():
                file_nodes.append({
                    "node_type": "File",
                    "id": f"File:{file_path.name}",
                    "properties": {
                        "path": str(file_path.relative_to(corpus_dir.parent.parent)),
                    },
                })

    return rag_index, file_nodes


# ---------------------------------------------------------------------------
# memory.py  — MemoryStore detection
# ---------------------------------------------------------------------------

def parse_memory_store(path: Path) -> dict[str, Any] | None:
    """Detect an in-process memory store in a Python file.

    Heuristic: looks for a module-level ``_memory`` dict assignment — the
    pattern used by the vulnerable-rag-app.  Returns a ``MemoryStore`` node
    dict or None.
    """
    tree = ast.parse(path.read_text(), filename=str(path))

    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        elif isinstance(node, ast.AnnAssign) and node.target:
            target = node.target
        else:
            continue
        if not isinstance(target, ast.Name):
            continue
        # Detect any module-level dict-shaped variable that looks like
        # session memory. Use the variable name verbatim as the node id —
        # this matches what the LLM scanner emits (which honestly uses
        # whatever name the source code uses) and avoids a special-case
        # rename to "session_memory" that the LLM has no way to learn.
        if target.id == "_memory":
            return {
                "node_type": "MemoryStore",
                "id": f"MemoryStore:{target.id}",
                "properties": {
                    "name": target.id,
                    "kind": "conversation",
                    "principal_scoped": False,
                },
            }
    return None
