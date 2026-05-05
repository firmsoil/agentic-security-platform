"""Unit tests for the Neo4j adapter's safety helpers and preconditions.

These tests deliberately do NOT require Neo4j to be running. They exercise
the validation logic that runs before any database call, plus the static
helpers (_safe_label, _validate_tenant_id) that are pure functions.

Integration tests against a real Neo4j (via testcontainers) live in a
separate module and are marked `@pytest.mark.integration`.
"""

from __future__ import annotations

import pytest

from asp_adapters.graph import DEFAULT_TENANT_ID, Neo4jConfig, Neo4jGraphStore
from asp_core.graph import load_ontology


@pytest.fixture(scope="module")
def store() -> Neo4jGraphStore:
    """A store instance with the v1 ontology loaded.

    We never call connect(); these tests only exercise validation logic
    that runs before the driver is needed.
    """
    config = Neo4jConfig(uri="bolt://unused", user="neo4j", password="unused")
    return Neo4jGraphStore(config=config, ontology=load_ontology("v1"))


class TestSafeLabel:
    """The Cypher injection chokepoint."""

    def test_accepts_valid_pascal_case(self) -> None:
        assert Neo4jGraphStore._safe_label("Model", kind="node") == "Model"
        assert Neo4jGraphStore._safe_label("CloudAccount", kind="node") == "CloudAccount"

    def test_accepts_valid_screaming_snake_case(self) -> None:
        assert (
            Neo4jGraphStore._safe_label("PROMPT_INJECTABLE_INTO", kind="edge")
            == "PROMPT_INJECTABLE_INTO"
        )
        assert (
            Neo4jGraphStore._safe_label("TOOL_INVOKABLE_BY", kind="edge")
            == "TOOL_INVOKABLE_BY"
        )

    def test_rejects_lowercase_start(self) -> None:
        with pytest.raises(ValueError, match="does not match"):
            Neo4jGraphStore._safe_label("model", kind="node")

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError):
            Neo4jGraphStore._safe_label("", kind="node")

    def test_rejects_clause_breakout(self) -> None:
        # The classic Cypher injection payload — closing the label position
        # and opening a new clause. Must be refused.
        with pytest.raises(ValueError):
            Neo4jGraphStore._safe_label("MyNode) DETACH DELETE n //", kind="node")

    def test_rejects_whitespace(self) -> None:
        with pytest.raises(ValueError):
            Neo4jGraphStore._safe_label("My Node", kind="node")

    def test_rejects_special_chars(self) -> None:
        for bad in ["My-Node", "My.Node", "My/Node", "My`Node`", "My;DROP"]:
            with pytest.raises(ValueError):
                Neo4jGraphStore._safe_label(bad, kind="node")

    def test_rejects_non_string(self) -> None:
        with pytest.raises(ValueError):
            Neo4jGraphStore._safe_label(123, kind="node")  # type: ignore[arg-type]


class TestValidateTenantId:
    """tenant_id hygiene rules."""

    def test_default_tenant_accepted(self) -> None:
        Neo4jGraphStore._validate_tenant_id(DEFAULT_TENANT_ID)
        # default literal must equal "default" — exposed deliberately for
        # adopters who expect that string.
        assert DEFAULT_TENANT_ID == "default"

    def test_alphanumeric_accepted(self) -> None:
        Neo4jGraphStore._validate_tenant_id("acme")
        Neo4jGraphStore._validate_tenant_id("acme-corp")
        Neo4jGraphStore._validate_tenant_id("acme_corp")
        Neo4jGraphStore._validate_tenant_id("acme.corp")
        Neo4jGraphStore._validate_tenant_id("tenant-2026-04")

    def test_at_max_length_accepted(self) -> None:
        Neo4jGraphStore._validate_tenant_id("a" + ("b" * 63))

    def test_too_long_rejected(self) -> None:
        with pytest.raises(ValueError):
            Neo4jGraphStore._validate_tenant_id("a" + ("b" * 64))

    def test_empty_rejected(self) -> None:
        with pytest.raises(ValueError):
            Neo4jGraphStore._validate_tenant_id("")

    def test_whitespace_rejected(self) -> None:
        with pytest.raises(ValueError):
            Neo4jGraphStore._validate_tenant_id("acme corp")

    def test_leading_special_rejected(self) -> None:
        # The pattern requires a leading alphanumeric.
        for bad in ["-acme", "_acme", ".acme"]:
            with pytest.raises(ValueError):
                Neo4jGraphStore._validate_tenant_id(bad)

    def test_injection_attempts_rejected(self) -> None:
        for bad in ["'; DROP", "tenant/../other", "tenant\x00null"]:
            with pytest.raises(ValueError):
                Neo4jGraphStore._validate_tenant_id(bad)


class TestUpsertPreconditions:
    """upsert_node and upsert_edge enforce tenant + ontology + property
    invariants *before* the driver is touched. We can verify those without
    a running Neo4j by triggering them and asserting the right exception."""

    @pytest.mark.asyncio
    async def test_upsert_node_rejects_unknown_type(self, store: Neo4jGraphStore) -> None:
        with pytest.raises(ValueError, match="Unknown node type"):
            await store.upsert_node(
                tenant_id="default",
                node_type="NotARealType",
                node_id="x",
                properties={},
            )

    @pytest.mark.asyncio
    async def test_upsert_node_rejects_tenant_id_in_properties(
        self, store: Neo4jGraphStore
    ) -> None:
        # Smuggling tenant_id via the properties dict is an obvious bypass
        # to attempt; reject it explicitly.
        with pytest.raises(ValueError, match="must not set tenant_id"):
            await store.upsert_node(
                tenant_id="default",
                node_type="Model",
                node_id="x",
                properties={"tenant_id": "other"},
            )

    @pytest.mark.asyncio
    async def test_upsert_node_rejects_invalid_tenant(self, store: Neo4jGraphStore) -> None:
        with pytest.raises(ValueError, match="tenant_id"):
            await store.upsert_node(
                tenant_id="has space",
                node_type="Model",
                node_id="x",
                properties={},
            )

    @pytest.mark.asyncio
    async def test_upsert_edge_rejects_unknown_type(self, store: Neo4jGraphStore) -> None:
        with pytest.raises(ValueError, match="Unknown edge type"):
            await store.upsert_edge(
                tenant_id="default",
                edge_type="NotAnEdge",
                source_type="Model",
                source_id="m1",
                target_type="Tool",
                target_id="t1",
            )

    @pytest.mark.asyncio
    async def test_upsert_edge_rejects_tenant_in_props(
        self, store: Neo4jGraphStore
    ) -> None:
        with pytest.raises(ValueError, match="must not set tenant_id"):
            await store.upsert_edge(
                tenant_id="default",
                edge_type="CALLS_TOOL",
                source_type="Model",
                source_id="m1",
                target_type="Tool",
                target_id="t1",
                properties={"tenant_id": "other"},
            )
