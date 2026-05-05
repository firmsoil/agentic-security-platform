"""Validation tests for the seed script's edge definitions.

These tests are pure — they validate the seed edge types and source/target
node types against the YAML ontology.  No Neo4j required.

The seed is now driven by ``targets/<target>.yaml`` profiles. The
``get_vulnerable_rag_app_*`` shims load the bundled profile so existing
assertions still apply, and a separate test class exercises the profile
loader (alias resolution, validation errors).
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

# scripts/ is not a Python package — add it to sys.path so we can import
# seed_graph directly.
_SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from asp_core.graph import load_ontology

from seed_graph import (
    TargetProfile,
    get_vulnerable_rag_app_edges,
    get_vulnerable_rag_app_nodes,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BUNDLED_PROFILE = _REPO_ROOT / "targets" / "vulnerable-rag-app.yaml"


@pytest.fixture(scope="module")
def ontology():
    return load_ontology("v1")


@pytest.fixture(scope="module")
def seed_edges():
    return get_vulnerable_rag_app_edges()


@pytest.fixture(scope="module")
def seed_nodes():
    return get_vulnerable_rag_app_nodes()


class TestSeedNodeTypesValid:
    def test_all_node_types_exist_in_ontology(self, seed_nodes, ontology) -> None:
        valid_names = {n.name for n in ontology.nodes}
        for node in seed_nodes:
            assert node.node_type in valid_names, (
                f"Seed node type '{node.node_type}' not found in ontology"
            )


class TestSeedEdgeTypesValid:
    def test_all_edge_types_exist_in_ontology(self, seed_edges, ontology) -> None:
        """Every edge type the seed script creates must be defined in edges.yaml."""
        valid_names = {e.name for e in ontology.edges}
        for edge in seed_edges:
            assert edge.edge_type in valid_names, (
                f"Seed edge type '{edge.edge_type}' not found in ontology"
            )


class TestSeedEdgeConstraints:
    def test_source_types_match_ontology(self, seed_edges, ontology) -> None:
        """For each edge, the source node type must be in the edge's source_types
        (or source_types must be empty = any).
        """
        for edge in seed_edges:
            edge_def = ontology.edge_by_name(edge.edge_type)
            assert edge_def is not None
            if edge_def.source_types:
                assert edge.source_type in edge_def.source_types, (
                    f"Seed edge {edge.edge_type}: source type '{edge.source_type}' "
                    f"not in allowed source_types {edge_def.source_types}"
                )

    def test_target_types_match_ontology(self, seed_edges, ontology) -> None:
        """For each edge, the target node type must be in the edge's target_types
        (or target_types must be empty = any).
        """
        for edge in seed_edges:
            edge_def = ontology.edge_by_name(edge.edge_type)
            assert edge_def is not None
            if edge_def.target_types:
                assert edge.target_type in edge_def.target_types, (
                    f"Seed edge {edge.edge_type}: target type '{edge.target_type}' "
                    f"not in allowed target_types {edge_def.target_types}"
                )


class TestSeedEdgeCoverage:
    def test_has_prompt_injectable_into(self, seed_edges) -> None:
        pii = [e for e in seed_edges if e.edge_type == "PROMPT_INJECTABLE_INTO"]
        assert len(pii) == 2, "Expected 2 PROMPT_INJECTABLE_INTO edges (RAG + Memory)"

    def test_has_tool_invokable_by(self, seed_edges) -> None:
        tib = [e for e in seed_edges if e.edge_type == "TOOL_INVOKABLE_BY"]
        assert len(tib) == 1

    def test_has_calls_tool(self, seed_edges) -> None:
        ct = [e for e in seed_edges if e.edge_type == "CALLS_TOOL"]
        assert len(ct) == 1

    def test_has_retrieves_from(self, seed_edges) -> None:
        rf = [e for e in seed_edges if e.edge_type == "RETRIEVES_FROM"]
        assert len(rf) == 1

    def test_has_uses_prompt(self, seed_edges) -> None:
        up = [e for e in seed_edges if e.edge_type == "USES_PROMPT"]
        assert len(up) == 1

    def test_has_memory_poisonable_by(self, seed_edges) -> None:
        mp = [e for e in seed_edges if e.edge_type == "MEMORY_POISONABLE_BY"]
        assert len(mp) == 1

    def test_total_edge_count(self, seed_edges) -> None:
        assert len(seed_edges) == 10, "Expected 10 total seed edges"

    def test_has_reads_edge_to_memory_store(self, seed_edges) -> None:
        reads = [e for e in seed_edges if e.edge_type == "READS"]
        assert len(reads) == 1

    def test_has_memory_classification(self, seed_edges) -> None:
        classified = [e for e in seed_edges if e.edge_type == "CLASSIFIED_AS"]
        assert len(classified) == 1


class TestSeedEdgeProperties:
    def test_prompt_injectable_edges_unsanitized(self, seed_edges) -> None:
        """Both PROMPT_INJECTABLE_INTO edges should have sanitized=False."""
        pii = [e for e in seed_edges if e.edge_type == "PROMPT_INJECTABLE_INTO"]
        for edge in pii:
            assert edge.properties.get("sanitized") is False
            assert edge.properties.get("trust_boundary_crossed") is True

    def test_tool_invokable_no_approval(self, seed_edges) -> None:
        tib = [e for e in seed_edges if e.edge_type == "TOOL_INVOKABLE_BY"]
        for edge in tib:
            assert edge.properties.get("requires_human_approval") is False


class TestSeedNodeProperties:
    def test_regulated_classification_node(self, seed_nodes) -> None:
        assert len(seed_nodes) == 2
        regulated = next(node for node in seed_nodes if node.node_type == "DataClassification")
        assert regulated.node_type == "DataClassification"
        assert regulated.properties["level"] == "regulated"

    def test_prompt_node_present(self, seed_nodes) -> None:
        prompt = next(node for node in seed_nodes if node.node_type == "Prompt")
        assert prompt.node_id == "Prompt:system_prompt_runtime"


# ---------------------------------------------------------------------------
# TargetProfile loader — new behaviour introduced when the seed became
# config-driven.  These tests cover alias resolution and error paths so
# that authoring a new targets/<x>.yaml fails fast on typos.
# ---------------------------------------------------------------------------


class TestTargetProfileBundled:
    def test_loads_bundled_profile(self) -> None:
        profile = TargetProfile.load(_BUNDLED_PROFILE)
        assert profile.name == "vulnerable-rag-app"
        assert profile.repo_url.startswith("https://github.com/")

    def test_bundled_profile_node_counts(self) -> None:
        profile = TargetProfile.load(_BUNDLED_PROFILE)
        # 7 connector-derived + 2 synthetic = 9 declared aliases.
        assert len(profile.expected_nodes()) == 7
        assert len(profile.synthetic_nodes()) == 2
        assert len(profile.edges) == 10

    def test_bundled_profile_aliases_resolve(self) -> None:
        profile = TargetProfile.load(_BUNDLED_PROFILE)
        # Every edge endpoint must reference a declared alias's node_type
        # — i.e. resolution succeeded during load (otherwise load() would
        # have raised).
        types = {n.node_type for n in profile.nodes_by_alias.values()}
        assert {"Repository", "Container", "Model", "Tool", "RAGIndex",
                "MemoryStore", "PromptTemplate", "Prompt",
                "DataClassification"}.issubset(types)


class TestTargetProfileValidation:
    @staticmethod
    def _load_yaml(text: str) -> TargetProfile:
        # NamedTemporaryFile doesn't flush before yielding the path on
        # some platforms — close the handle so TargetProfile.load reads
        # the full content.
        f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
        try:
            f.write(text)
        finally:
            f.close()
        return TargetProfile.load(Path(f.name))

    def test_unknown_edge_alias_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown alias 'ghost'"):
            self._load_yaml(
                """
                name: bogus
                expected_nodes:
                  thing: {id: "X:y", node_type: Repository}
                edges:
                  - {type: INVOKES_MODEL, source: ghost, target: thing}
                """
            )

    def test_missing_name_raises(self) -> None:
        with pytest.raises(ValueError, match="'name'"):
            self._load_yaml("expected_nodes: {}\n")

    def test_missing_required_field_raises(self) -> None:
        with pytest.raises(ValueError, match="missing required 'id'"):
            self._load_yaml(
                """
                name: x
                expected_nodes:
                  thing: {node_type: Repository}
                """
            )

    def test_duplicate_alias_raises(self) -> None:
        with pytest.raises(ValueError, match="alias 'thing' defined twice"):
            self._load_yaml(
                """
                name: x
                expected_nodes:
                  thing: {id: "Repository:a", node_type: Repository}
                synthetic_nodes:
                  thing: {id: "Prompt:b", node_type: Prompt}
                """
            )

    def test_missing_file_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            TargetProfile.load(Path("/nonexistent/profile.yaml"))
