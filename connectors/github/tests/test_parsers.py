"""Unit tests for the GitHub connector parsers.

Run against the actual ``examples/vulnerable-rag-app`` files.  These are
fast, pure tests — no network, no graph database.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from connectors.github.src.parsers import (
    parse_corpus,
    parse_memory_store,
    parse_prompt_template,
    parse_requirements,
    parse_tool_schemas,
)

# Resolve the vulnerable-rag-app path relative to the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_APP_DIR = _REPO_ROOT / "examples" / "vulnerable-rag-app"


class TestParseRequirements:
    def test_finds_anthropic(self) -> None:
        deps = parse_requirements(_APP_DIR / "requirements.txt")
        names = [d["name"] for d in deps]
        assert "anthropic" in names

    def test_finds_fastapi(self) -> None:
        deps = parse_requirements(_APP_DIR / "requirements.txt")
        names = [d["name"] for d in deps]
        assert "fastapi" in names

    def test_skips_comments_and_blanks(self) -> None:
        deps = parse_requirements(_APP_DIR / "requirements.txt")
        # Should have exactly 5 dependencies (fastapi, uvicorn, pydantic,
        # anthropic, httpx).
        assert len(deps) == 5

    def test_extracts_specifiers(self) -> None:
        deps = parse_requirements(_APP_DIR / "requirements.txt")
        anthropic_dep = next(d for d in deps if d["name"] == "anthropic")
        assert anthropic_dep["specifier"] == ">=0.40"


class TestParseToolSchemas:
    def test_extracts_export_data(self) -> None:
        tools = parse_tool_schemas(_APP_DIR / "tools.py")
        assert len(tools) >= 1
        names = [t["properties"]["name"] for t in tools]
        assert "export_data" in names

    def test_tool_has_correct_node_type(self) -> None:
        tools = parse_tool_schemas(_APP_DIR / "tools.py")
        for tool in tools:
            assert tool["node_type"] == "Tool"

    def test_tool_has_json_schema(self) -> None:
        tools = parse_tool_schemas(_APP_DIR / "tools.py")
        export = next(t for t in tools if t["properties"]["name"] == "export_data")
        schema_str = export["properties"]["schema"]
        assert isinstance(schema_str, str)
        import json
        schema = json.loads(schema_str)
        assert schema.get("type") == "object"
        assert "properties" in schema

    def test_tool_id_format(self) -> None:
        tools = parse_tool_schemas(_APP_DIR / "tools.py")
        export = next(t for t in tools if t["properties"]["name"] == "export_data")
        assert export["id"] == "Tool:export_data"

    def test_deduplicates(self) -> None:
        """TOOL_SCHEMAS references EXPORT_DATA_TOOL; parser should not emit it twice."""
        tools = parse_tool_schemas(_APP_DIR / "tools.py")
        names = [t["properties"]["name"] for t in tools]
        assert len(names) == len(set(names))


class TestParsePromptTemplate:
    def test_extracts_system_prompt(self) -> None:
        pt = parse_prompt_template(_APP_DIR / "model.py")
        assert pt is not None
        assert pt["node_type"] == "PromptTemplate"
        assert pt["properties"]["name"] == "system_prompt"

    def test_has_checksum(self) -> None:
        pt = parse_prompt_template(_APP_DIR / "model.py")
        assert pt is not None
        checksum = pt["properties"]["checksum"]
        # sha256 hex digest is 64 chars.
        assert len(checksum) == 64

    def test_id_format(self) -> None:
        pt = parse_prompt_template(_APP_DIR / "model.py")
        assert pt is not None
        assert pt["id"] == "PromptTemplate:system_prompt"


class TestParseCorpus:
    def test_finds_all_docs(self) -> None:
        rag_node, file_nodes = parse_corpus(_APP_DIR / "corpus")
        assert len(file_nodes) == 3  # injected-doc.md, refund-policy.md, shipping-faq.md

    def test_rag_index_node_type(self) -> None:
        rag_node, _ = parse_corpus(_APP_DIR / "corpus")
        assert rag_node["node_type"] == "RAGIndex"
        assert rag_node["id"] == "RAGIndex:corpus"

    def test_file_paths_are_relative(self) -> None:
        _, file_nodes = parse_corpus(_APP_DIR / "corpus")
        for fn in file_nodes:
            path = fn["properties"]["path"]
            assert not path.startswith("/"), f"Path should be relative: {path}"

    def test_file_node_type(self) -> None:
        _, file_nodes = parse_corpus(_APP_DIR / "corpus")
        for fn in file_nodes:
            assert fn["node_type"] == "File"


class TestParseMemoryStore:
    def test_detects_memory_store(self) -> None:
        mem = parse_memory_store(_APP_DIR / "memory.py")
        assert mem is not None
        assert mem["node_type"] == "MemoryStore"

    def test_properties(self) -> None:
        mem = parse_memory_store(_APP_DIR / "memory.py")
        assert mem is not None
        assert mem["properties"]["kind"] == "conversation"
        assert mem["properties"]["principal_scoped"] is False

    def test_id_format(self) -> None:
        mem = parse_memory_store(_APP_DIR / "memory.py")
        assert mem is not None
        assert mem["id"] == "MemoryStore:session_memory"
