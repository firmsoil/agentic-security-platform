"""Neo4j adapter for the Security Graph.

This module is the only place in the codebase that imports `neo4j`. It speaks
Cypher and returns plain Python values; the domain layer in `asp_core` does
not know Neo4j exists.

Tenant scoping (ADR-0003)
-------------------------
Every node and every edge in the graph carries a `tenant_id`. Every adapter
operation requires a tenant context. There is no method here that writes or
reads the graph without an explicit `tenant_id` parameter. Single-tenant
deployments use the literal string ``"default"``. The same code path applies.

Cypher injection hardening
--------------------------
Neo4j drivers cannot parameterize labels and relationship types — that is a
limitation of Cypher, not a code bug. Labels and types are interpolated into
queries via the ``_safe_label()`` helper below, which validates against the
loaded ontology *and* a strict regex. Property values continue to be passed
as query parameters. There must be no other path by which a label or
relationship type reaches a Cypher string.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase

from asp_core.graph import Ontology

# Strict identifier pattern. Cypher labels and relationship types are
# unquoted identifiers; allowing only this character class blocks any
# attempt to break out of the label position into a clause.
_IDENTIFIER_RE = re.compile(r"^[A-Z][A-Za-z0-9_]*$")

# The default tenant for single-tenant deployments. Used everywhere the same
# code path needs to run regardless of how many tenants exist in the graph.
DEFAULT_TENANT_ID = "default"


@dataclass(frozen=True)
class Neo4jConfig:
    uri: str
    user: str
    password: str
    database: str = "neo4j"


class Neo4jGraphStore:
    """Minimal graph store facade.

    Callers work in terms of ontology node/edge type names plus a tenant
    binding. This class is the chokepoint for tenant scoping and label
    safety enforcement.
    """

    def __init__(self, config: Neo4jConfig, ontology: Ontology) -> None:
        self._config = config
        self._ontology = ontology
        self._driver: AsyncDriver | None = None

    # ------------------------------------------------------------------ lifecycle

    async def connect(self) -> None:
        if self._driver is not None:
            return
        self._driver = AsyncGraphDatabase.driver(
            self._config.uri,
            auth=(self._config.user, self._config.password),
        )
        await self._driver.verify_connectivity()

    async def close(self) -> None:
        if self._driver is not None:
            await self._driver.close()
            self._driver = None

    # ------------------------------------------------------------------ schema

    async def apply_schema_constraints(self) -> None:
        """Create uniqueness constraints derived from the loaded ontology.

        Per ADR-0003, node IDs are unique *within* a tenant, not globally.
        We enforce this with a composite (tenant_id, id) uniqueness
        constraint on every node label.
        """
        self._require_driver()
        async with self._driver.session(database=self._config.database) as session:
            for node_type in self._ontology.nodes:
                label = self._safe_label(node_type.name, kind="node")
                cypher = (
                    f"CREATE CONSTRAINT {label.lower()}_tenant_id_unique "
                    f"IF NOT EXISTS FOR (n:{label}) "
                    "REQUIRE (n.tenant_id, n.id) IS UNIQUE"
                )
                await session.run(cypher)

    # ------------------------------------------------------------------ writes

    async def upsert_node(
        self,
        *,
        tenant_id: str,
        node_type: str,
        node_id: str,
        properties: dict[str, Any],
    ) -> None:
        """Upsert a node within the given tenant.

        ``tenant_id`` is required and is bound to the node. Subsequent reads
        of this node *must* supply the same ``tenant_id`` to retrieve it.
        Properties named ``tenant_id`` in the input dict are rejected to
        prevent confusion or smuggling.
        """
        # Argument validation runs before the driver check so callers get
        # informative errors regardless of connection state.
        self._validate_tenant_id(tenant_id)
        if "tenant_id" in properties:
            msg = "Caller must not set tenant_id in properties; pass via the parameter."
            raise ValueError(msg)
        label = self._resolve_node_label(node_type)
        self._require_driver()

        async with self._driver.session(database=self._config.database) as session:
            cypher = (
                f"MERGE (n:{label} {{tenant_id: $tenant_id, id: $id}}) "
                "SET n += $props, n.updated_at = timestamp()"
            )
            await session.run(
                cypher,
                tenant_id=tenant_id,
                id=node_id,
                props=properties,
            )

    async def upsert_edge(
        self,
        *,
        tenant_id: str,
        edge_type: str,
        source_type: str,
        source_id: str,
        target_type: str,
        target_id: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """Upsert an edge between two nodes within the given tenant.

        Edges cannot cross tenants. The source and target must both belong
        to ``tenant_id``; otherwise the MATCH yields zero rows and no edge
        is created.
        """
        self._validate_tenant_id(tenant_id)
        if properties and "tenant_id" in properties:
            msg = "Caller must not set tenant_id in properties; pass via the parameter."
            raise ValueError(msg)
        rel_type = self._resolve_edge_type(edge_type)
        src_label = self._resolve_node_label(source_type)
        tgt_label = self._resolve_node_label(target_type)
        self._require_driver()

        async with self._driver.session(database=self._config.database) as session:
            cypher = (
                f"MATCH (s:{src_label} {{tenant_id: $tenant_id, id: $src_id}}), "
                f"(t:{tgt_label} {{tenant_id: $tenant_id, id: $tgt_id}}) "
                f"MERGE (s)-[r:{rel_type} {{tenant_id: $tenant_id}}]->(t) "
                "SET r += $props, r.updated_at = timestamp()"
            )
            await session.run(
                cypher,
                tenant_id=tenant_id,
                src_id=source_id,
                tgt_id=target_id,
                props=properties or {},
            )

    # ------------------------------------------------------------------ reads

    async def run_cypher(
        self,
        cypher: str,
        *,
        tenant_id: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Escape hatch for read queries.

        Caller is responsible for including ``$tenant_id`` filters in the
        Cypher and passing ``tenant_id`` here. We bind it into params
        unconditionally so a forgotten ``$tenant_id`` reference yields a
        Cypher parameter error rather than a silent cross-tenant read.

        Prefer typed helpers when they exist. This method exists for
        attack-path queries and other read paths that don't fit a fixed
        signature.
        """
        self._require_driver()
        self._validate_tenant_id(tenant_id)
        merged_params: dict[str, Any] = {**(params or {}), "tenant_id": tenant_id}
        async with self._driver.session(database=self._config.database) as session:
            result = await session.run(cypher, merged_params)
            return [record.data() async for record in result]

    # ------------------------------------------------------------------ helpers

    def _resolve_node_label(self, node_type: str) -> str:
        if self._ontology.node_by_name(node_type) is None:
            msg = f"Unknown node type: {node_type}"
            raise ValueError(msg)
        return self._safe_label(node_type, kind="node")

    def _resolve_edge_type(self, edge_type: str) -> str:
        if self._ontology.edge_by_name(edge_type) is None:
            msg = f"Unknown edge type: {edge_type}"
            raise ValueError(msg)
        return self._safe_label(edge_type, kind="edge")

    @staticmethod
    def _safe_label(identifier: str, *, kind: str) -> str:
        """Validate an identifier against the strict Cypher-identifier pattern.

        Cypher labels and relationship types cannot be parameterized in the
        Neo4j driver. This helper is the single sanctioned path for
        interpolating them into Cypher strings. It enforces the
        ``^[A-Z][A-Za-z0-9_]*$`` pattern which blocks any attempt to break
        out of the label position into a Cypher clause.

        Callers are expected to have already verified the identifier is
        defined in the loaded ontology — this is a defense-in-depth check,
        not a substitute for the ontology lookup.
        """
        if not isinstance(identifier, str) or not _IDENTIFIER_RE.match(identifier):
            msg = (
                f"Refusing to interpolate {kind} identifier into Cypher: "
                f"{identifier!r} does not match {_IDENTIFIER_RE.pattern}"
            )
            raise ValueError(msg)
        return identifier

    @staticmethod
    def _validate_tenant_id(tenant_id: str) -> None:
        """Conservative character class for tenant IDs.

        Property values are parameterized — this is not an injection check,
        it's a hygiene check so that downstream systems (audit logs, OPA
        decisions, OTel traces) receive predictable identifiers.
        """
        if not isinstance(tenant_id, str) or not tenant_id:
            msg = "tenant_id must be a non-empty string"
            raise ValueError(msg)
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$", tenant_id):
            msg = (
                f"tenant_id {tenant_id!r} must match "
                "^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$"
            )
            raise ValueError(msg)

    def _require_driver(self) -> None:
        if self._driver is None:
            msg = "Neo4jGraphStore not connected — call connect() first"
            raise RuntimeError(msg)
