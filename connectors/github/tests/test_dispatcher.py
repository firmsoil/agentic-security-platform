"""Multi-stack dispatcher tests.

Verifies ``scan_repository`` picks the right stack scanner, that ``--stack``
overrides the detector, and that the same Repository/Container/Artifact
backbone shows up regardless of stack.

Also exercises the LLM-augmented entry point ``scan_repository_with_llm``
via a controllable FakeAdapter — no real API calls.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest

from connectors.github.src.llm.protocol import AdapterCallResult
from connectors.github.src.scanner import (
    scan_repository,
    scan_repository_with_llm,
)
from connectors.github.src.types import ScanResult


# ---------------------------------------------------------------------------
# Fixtures: minimal repos for each stack.
# ---------------------------------------------------------------------------


@pytest.fixture
def java_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "demo-java-app"
    repo.mkdir()
    (repo / "pom.xml").write_text("""\
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <dependencies>
    <dependency>
      <groupId>dev.langchain4j</groupId>
      <artifactId>langchain4j-anthropic</artifactId>
      <version>0.35.0</version>
    </dependency>
  </dependencies>
</project>
""")
    return repo


@pytest.fixture
def node_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "demo-node-app"
    repo.mkdir()
    (repo / "package.json").write_text(json.dumps({
        "name": "demo-node-app",
        "dependencies": {
            "@anthropic-ai/sdk": "^0.30.0",
            "next": "^15.0.0",
        },
    }))
    return repo


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDispatcher:
    def test_dispatches_to_java_scanner(self, java_repo: Path) -> None:
        result = scan_repository(java_repo)
        assert isinstance(result, ScanResult)
        assert result.stack == "java"
        node_ids = {n["id"] for n in result.nodes}
        assert "Repository:demo-java-app" in node_ids
        assert "Container:demo-java-app" in node_ids
        assert "Artifact:langchain4j-anthropic" in node_ids
        assert "Model:anthropic:claude-sonnet-4-5" in node_ids

    def test_dispatches_to_node_scanner(self, node_repo: Path) -> None:
        result = scan_repository(node_repo)
        assert result.stack == "node"
        node_ids = {n["id"] for n in result.nodes}
        assert "Repository:demo-node-app" in node_ids
        assert "Container:demo-node-app" in node_ids
        assert "Artifact:@anthropic-ai/sdk" in node_ids
        assert "Model:anthropic:claude-sonnet-4-5" in node_ids

    def test_stack_override_forces_python(self, node_repo: Path) -> None:
        # Auto-detect would pick node; --stack python should override even
        # though there's no Python manifest. The Python scanner just
        # produces Repository + Container with no deps.
        result = scan_repository(node_repo, stack="python")
        assert result.stack == "python"
        node_ids = {n["id"] for n in result.nodes}
        assert "Artifact:@anthropic-ai/sdk" not in node_ids

    def test_repo_url_recorded_on_repository_node(self, node_repo: Path) -> None:
        result = scan_repository(
            node_repo,
            repo_url="https://github.com/example/demo-node-app",
        )
        repo = next(n for n in result.nodes if n["node_type"] == "Repository")
        assert repo["properties"]["url"] == (
            "https://github.com/example/demo-node-app"
        )
        assert repo["properties"]["visibility"] == "public"

    def test_repository_and_container_present_for_every_stack(
        self,
        java_repo: Path,
        node_repo: Path,
    ) -> None:
        for repo in (java_repo, node_repo):
            result = scan_repository(repo)
            types = {n["node_type"] for n in result.nodes}
            assert "Repository" in types
            assert "Container" in types

    def test_metadata_unset_for_manifest_only_scan(self, node_repo: Path):
        # Backwards-compatible default — manifest-only scans don't carry
        # the LLM ride-along metadata block.
        result = scan_repository(node_repo)
        assert result.metadata is None


# ---------------------------------------------------------------------------
# scan_repository_with_llm — integration with the LLM scanner via FakeAdapter
# ---------------------------------------------------------------------------


def _sha_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _grounded_node(
    *,
    node_type: str,
    name: str,
    file_path: str,
    file_sha256: str,
    line_start: int = 1,
    line_end: int = 3,
):
    return {
        "node_type": node_type,
        "id": f"{node_type}:{name}",
        "properties": {"name": name},
        "grounding": {
            "file_path": file_path,
            "line_start": line_start,
            "line_end": line_end,
            "file_sha256": file_sha256,
            "evidence": f"file declares {name}",
            "confidence": "high",
        },
    }


class _FakeAdapter:
    """Stand-in StructuredExtractor for the dispatcher integration tests."""

    name = "fake"
    model_name = "fake-model"

    def __init__(self, extract_responses=None, verify_verdict: bool = True):
        self._responses = extract_responses or defaultdict(list)
        self._verdict = verify_verdict

    async def extract(self, *, system_prompt, user_prompt, schema):
        nodes: list[dict[str, Any]] = []
        for keyword, payload in self._responses.items():
            if keyword in user_prompt:
                nodes.extend(payload)
        return AdapterCallResult(
            payload={"nodes": nodes},
            model_name=self.model_name,
            input_tokens=50,
            output_tokens=50,
        )

    async def verify(self, *, system_prompt, user_prompt, schema):
        return AdapterCallResult(
            payload={"verified": self._verdict, "reason": "ok"},
            model_name=self.model_name,
            input_tokens=10,
            output_tokens=10,
        )


@pytest.fixture
def llm_test_repo(tmp_path: Path) -> Path:
    """A small Node repo + sibling prompts dir, mirroring the orchestrator
    tests' fixture shape so the LLM walk doesn't pick up the prompts."""
    repo = tmp_path / "repo"
    src = repo / "src"
    src.mkdir(parents=True)
    (repo / "package.json").write_text(json.dumps({
        "name": "demo-app",
        "dependencies": {"@anthropic-ai/sdk": "^0.30.0"},
    }))
    (src / "tools.ts").write_text(
        "export const exportData = tool({\n"
        "    description: 'export data',\n"
        "    execute: async () => {},\n"
        "});\n"
    )
    return repo


@pytest.fixture
def llm_prompts_dir(tmp_path: Path) -> Path:
    pdir = tmp_path / "prompts"
    pdir.mkdir()
    for name in (
        "extract_tools.md",
        "extract_prompt_templates.md",
        "extract_rag_indices.md",
        "extract_memory_stores.md",
    ):
        (pdir / name).write_text(f"# {name}\nstub\n")
    return pdir


@pytest.mark.asyncio
async def test_scan_with_llm_merges_manifest_and_llm_nodes(
    llm_test_repo: Path,
    llm_prompts_dir: Path,
):
    """Dispatcher returns manifest nodes + LLM-extracted nodes, all in
    one ScanResult, with LLM grounding moved under properties._llm_grounding."""
    sha = _sha_of(llm_test_repo / "src" / "tools.ts")
    adapter = _FakeAdapter(extract_responses={
        "extract_tools.md": [_grounded_node(
            node_type="Tool", name="exportData",
            file_path="src/tools.ts", file_sha256=sha,
        )],
    })

    result = await scan_repository_with_llm(
        llm_test_repo,
        adapter=adapter,
        prompts_dir=llm_prompts_dir,
    )

    # Manifest nodes still present.
    assert isinstance(result, ScanResult)
    assert result.stack == "node"
    ids = {n["id"] for n in result.nodes}
    assert "Repository:repo" in ids
    assert "Container:repo" in ids
    assert "Artifact:@anthropic-ai/sdk" in ids
    assert "Model:anthropic:claude-sonnet-4-5" in ids

    # LLM-extracted node also present.
    assert "Tool:exportData" in ids

    # Grounding flattened into properties._llm_grounding_* scalar fields.
    # Nested-map storage was rejected by Neo4j (only primitives + arrays of
    # primitives are valid property values), so we flatten each grounding
    # field into its own scalar property.
    tool_node = next(n for n in result.nodes if n["id"] == "Tool:exportData")
    assert "grounding" not in tool_node
    assert "_llm_grounding" not in tool_node["properties"]
    assert tool_node["properties"]["_llm_grounding_file_path"] == "src/tools.ts"
    assert tool_node["properties"]["_llm_grounding_file_sha256"] == sha
    assert tool_node["properties"]["_llm_grounding_line_start"] == 1
    assert tool_node["properties"]["_llm_grounding_confidence"] == "high"


@pytest.mark.asyncio
async def test_scan_with_llm_attaches_report_to_metadata(
    llm_test_repo: Path,
    llm_prompts_dir: Path,
):
    adapter = _FakeAdapter()
    result = await scan_repository_with_llm(
        llm_test_repo,
        adapter=adapter,
        prompts_dir=llm_prompts_dir,
    )
    assert result.metadata is not None
    assert "llm_scan" in result.metadata
    llm_meta = result.metadata["llm_scan"]
    assert llm_meta["adapter"] == "fake"
    assert llm_meta["model_name"] == "fake-model"
    assert "report" in llm_meta
    assert llm_meta["report"]["files_walked"] >= 1


def test_merge_logic_drops_llm_collisions_and_strips_grounding():
    """Unit test for the merge invariant.

    Going through the full pipeline can't easily produce a collision —
    the LLM scanner only emits the four code-shape node types and
    ``validate_grounded_node`` enforces that the ID prefix matches the
    node_type, so a Tool can never collide with a manifest Repository.
    But the merge logic is still defensive against the case where a
    future scanner produces overlapping IDs (e.g. an LLM scanner that
    emits Tools and a future Java AST parser that also emits Tools).
    """
    from connectors.github.src.scanner import _merge_nodes

    manifest = [
        {"node_type": "Repository", "id": "Repository:demo", "properties": {"url": "..."}},
        {"node_type": "Tool", "id": "Tool:export_data", "properties": {"name": "export_data"}},
    ]
    llm = [
        # Collision — manifest Tool wins.
        {
            "node_type": "Tool",
            "id": "Tool:export_data",
            "properties": {"name": "export_data"},
            "grounding": {
                "file_path": "tools.py", "line_start": 1, "line_end": 1,
                "file_sha256": "0" * 64, "evidence": "x", "confidence": "high",
            },
        },
        # Unique LLM contribution — kept, grounding moved.
        {
            "node_type": "PromptTemplate",
            "id": "PromptTemplate:system",
            "properties": {"name": "system"},
            "grounding": {
                "file_path": "model.py", "line_start": 5, "line_end": 5,
                "file_sha256": "0" * 64, "evidence": "y", "confidence": "high",
            },
        },
    ]

    merged, dropped = _merge_nodes(manifest_nodes=manifest, llm_nodes=llm)

    # Collision dropped, manifest version kept (no _llm_grounding on it).
    assert "Tool:export_data" in dropped
    tool = next(n for n in merged if n["id"] == "Tool:export_data")
    assert tool == manifest[1]  # untouched
    assert not any(
        k.startswith("_llm_grounding") for k in tool.get("properties", {})
    )

    # Unique LLM node kept, grounding flattened into scalar properties.
    pt = next(n for n in merged if n["id"] == "PromptTemplate:system")
    assert "grounding" not in pt
    assert pt["properties"]["_llm_grounding_file_path"] == "model.py"
    assert pt["properties"]["_llm_grounding_line_start"] == 5
    assert pt["properties"]["_llm_grounding_confidence"] == "high"

    # Original manifest list not mutated.
    assert len(manifest) == 2
    assert not any(
        k.startswith("_llm_grounding") for k in manifest[1].get("properties", {})
    )


@pytest.mark.asyncio
async def test_to_json_includes_metadata_when_present(
    llm_test_repo: Path,
    llm_prompts_dir: Path,
):
    adapter = _FakeAdapter()
    result = await scan_repository_with_llm(
        llm_test_repo,
        adapter=adapter,
        prompts_dir=llm_prompts_dir,
    )
    payload = json.loads(result.to_json())
    assert "metadata" in payload
    assert "llm_scan" in payload["metadata"]


def test_to_json_omits_metadata_when_none(node_repo: Path):
    """Backwards compatibility: manifest-only scans serialize the same
    JSON shape they did before metadata was added."""
    result = scan_repository(node_repo)
    payload = json.loads(result.to_json())
    assert "metadata" not in payload
