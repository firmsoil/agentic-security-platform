"""Unit tests for asp_core.graph.schema — the ontology loader.

These tests run against the bundled ontology v1. They require only
pydantic + pyyaml — no Neo4j, no network.
"""

from __future__ import annotations

import pytest

from asp_core.graph import (
    EdgeCategory,
    NodeCategory,
    Ontology,
    load_ontology,
)


@pytest.fixture(scope="module")
def ontology() -> Ontology:
    return load_ontology("v1")


class TestOntologyLoads:
    def test_version_is_semver(self, ontology: Ontology) -> None:
        assert ontology.version.count(".") == 2

    def test_has_nodes_and_edges(self, ontology: Ontology) -> None:
        assert len(ontology.nodes) > 0
        assert len(ontology.edges) > 0

    def test_node_names_are_unique(self, ontology: Ontology) -> None:
        names = [n.name for n in ontology.nodes]
        assert len(names) == len(set(names)), "duplicate node type names"

    def test_edge_names_are_unique(self, ontology: Ontology) -> None:
        names = [e.name for e in ontology.edges]
        assert len(names) == len(set(names)), "duplicate edge type names"

    def test_all_categories_present(self, ontology: Ontology) -> None:
        """Every NodeCategory must have at least one node type defined."""
        categories = {n.category for n in ontology.nodes}
        for cat in NodeCategory:
            assert cat in categories, f"no nodes for category {cat.value}"

    def test_all_edge_categories_present(self, ontology: Ontology) -> None:
        categories = {e.category for e in ontology.edges}
        for cat in EdgeCategory:
            assert cat in categories, f"no edges for category {cat.value}"


class TestAIDifferentiation:
    """The differentiating value of this ontology is its AI-specific content.
    These tests lock in the claim that the ontology actually covers what the
    platform's marketing material says it covers."""

    def test_has_ai_node_types(self, ontology: Ontology) -> None:
        expected = {
            "Model",
            "Prompt",
            "PromptTemplate",
            "Guardrail",
            "Tool",
            "RAGIndex",
            "VectorStore",
            "MemoryStore",
            "TrainingDataset",
            "Evaluation",
        }
        names = {n.name for n in ontology.nodes if n.category == NodeCategory.AI}
        missing = expected - names
        assert not missing, f"missing AI node types: {missing}"

    def test_has_ai_attack_edges(self, ontology: Ontology) -> None:
        """These edges are the platform's reason for existing."""
        expected = {
            "PROMPT_INJECTABLE_INTO",
            "TOOL_INVOKABLE_BY",
            "MEMORY_POISONABLE_BY",
            "DATA_POISONABLE_BY",
            "HALLUCINATION_IMPACTS",
        }
        names = {e.name for e in ontology.edges}
        missing = expected - names
        assert not missing, f"missing AI attack edges: {missing}"


class TestFrameworkMappings:
    """Validates that the framework mappings are actually wired through."""

    def test_prompt_injection_edge_maps_to_llm01(self, ontology: Ontology) -> None:
        edge = ontology.edge_by_name("PROMPT_INJECTABLE_INTO")
        assert edge is not None
        ids = [(m.framework, m.identifier) for m in edge.mappings]
        assert ("OWASP_LLM_TOP_10_2025", "LLM01:2025") in ids

    def test_prompt_injection_edge_maps_to_asi01(self, ontology: Ontology) -> None:
        edge = ontology.edge_by_name("PROMPT_INJECTABLE_INTO")
        assert edge is not None
        ids = [(m.framework, m.identifier) for m in edge.mappings]
        assert ("OWASP_AGENTIC_TOP_10_2026", "ASI01") in ids

    def test_tool_invokable_maps_to_excessive_agency(self, ontology: Ontology) -> None:
        edge = ontology.edge_by_name("TOOL_INVOKABLE_BY")
        assert edge is not None
        ids = [(m.framework, m.identifier) for m in edge.mappings]
        assert ("OWASP_LLM_TOP_10_2025", "LLM06:2025") in ids
        assert ("OWASP_AGENTIC_TOP_10_2026", "ASI02") in ids

    def test_memory_poisoning_maps_to_asi06(self, ontology: Ontology) -> None:
        edge = ontology.edge_by_name("MEMORY_POISONABLE_BY")
        assert edge is not None
        ids = [(m.framework, m.identifier) for m in edge.mappings]
        assert ("OWASP_AGENTIC_TOP_10_2026", "ASI06") in ids


class TestLookups:
    def test_node_by_name_hit(self, ontology: Ontology) -> None:
        n = ontology.node_by_name("Model")
        assert n is not None
        assert n.category == NodeCategory.AI

    def test_node_by_name_miss(self, ontology: Ontology) -> None:
        assert ontology.node_by_name("NotARealNode") is None

    def test_edge_by_name_hit(self, ontology: Ontology) -> None:
        e = ontology.edge_by_name("CALLS_TOOL")
        assert e is not None
        assert e.category == EdgeCategory.AI


class TestLoaderFailures:
    def test_missing_version_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_ontology("v999")
