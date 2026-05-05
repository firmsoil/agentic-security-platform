"""Integration tests for the repository scanner.

Validates that ``scan_repository`` produces a ScanResult whose node and edge
types are all valid against the loaded ontology.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from asp_core.graph import load_ontology
from connectors.github.src.scanner import scan_repository

_REPO_ROOT = Path(__file__).resolve().parents[3]
_APP_DIR = _REPO_ROOT / "examples" / "vulnerable-rag-app"


@pytest.fixture(scope="module")
def scan_result():
    return scan_repository(_APP_DIR)


@pytest.fixture(scope="module")
def ontology():
    return load_ontology("v1")


class TestScanResultTypes:
    def test_all_node_types_are_ontology_valid(self, scan_result, ontology) -> None:
        """Every emitted node type must exist in the ontology YAML."""
        valid_names = {n.name for n in ontology.nodes}
        for node in scan_result.nodes:
            nt = node["node_type"]
            assert nt in valid_names, (
                f"Node type '{nt}' (id={node['id']}) not in ontology"
            )

    def test_all_edge_types_are_ontology_valid(self, scan_result, ontology) -> None:
        """Every emitted edge type must exist in the ontology YAML."""
        valid_names = {e.name for e in ontology.edges}
        for edge in scan_result.edges:
            et = edge["edge_type"]
            assert et in valid_names, (
                f"Edge type '{et}' not in ontology"
            )


class TestScanResultCounts:
    def test_produces_expected_node_count(self, scan_result) -> None:
        """Expected nodes:
            1 Repository
            1 Container (app runtime)
            5 Artifact (fastapi, uvicorn, pydantic, anthropic, httpx)
            1 Model (claude, inferred from anthropic dep)
            1 Tool (export_data)
            1 PromptTemplate (system_prompt)
            1 RAGIndex (corpus)
            3 File (injected-doc.md, refund-policy.md, shipping-faq.md)
            1 MemoryStore (session_memory)
            = 15 total
        """
        assert len(scan_result.nodes) == 15

    def test_produces_expected_edge_count(self, scan_result) -> None:
        """Expected structural edges:
            5 DEPENDS_ON (Repository → each Artifact)
            3 CONTAINS (RAGIndex → each File)
            = 8 total
        """
        assert len(scan_result.edges) == 8

    def test_has_repository_node(self, scan_result) -> None:
        repo_nodes = [n for n in scan_result.nodes if n["node_type"] == "Repository"]
        assert len(repo_nodes) == 1

    def test_has_model_node(self, scan_result) -> None:
        model_nodes = [n for n in scan_result.nodes if n["node_type"] == "Model"]
        assert len(model_nodes) == 1
        assert model_nodes[0]["properties"]["provider"] == "anthropic"

    def test_has_container_node(self, scan_result) -> None:
        container_nodes = [n for n in scan_result.nodes if n["node_type"] == "Container"]
        assert len(container_nodes) == 1

    def test_repo_path_is_set(self, scan_result) -> None:
        assert scan_result.repo_path != ""

    def test_scanned_at_is_set(self, scan_result) -> None:
        assert scan_result.scanned_at != ""


class TestEdgeSourceTargetConsistency:
    def test_edge_endpoints_reference_existing_nodes(self, scan_result) -> None:
        """Every edge source/target ID must reference a node in the result."""
        node_ids = {n["id"] for n in scan_result.nodes}
        for edge in scan_result.edges:
            assert edge["source_id"] in node_ids, (
                f"Edge {edge['edge_type']} source {edge['source_id']} not in nodes"
            )
            assert edge["target_id"] in node_ids, (
                f"Edge {edge['edge_type']} target {edge['target_id']} not in nodes"
            )
