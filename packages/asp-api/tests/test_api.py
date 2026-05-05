"""API contract tests. No network; uses Starlette's in-process TestClient."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from asp_api.main import create_app


@pytest.fixture(scope="module")
def client() -> TestClient:
    # TestClient triggers lifespan, so the ontology is loaded.
    with TestClient(create_app()) as c:
        yield c


class TestHealth:
    def test_health_ok(self, client: TestClient) -> None:
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "version" in body

    def test_ready_ok(self, client: TestClient) -> None:
        r = client.get("/ready")
        assert r.status_code == 200


class TestOntologyEndpoints:
    def test_full_ontology(self, client: TestClient) -> None:
        r = client.get("/api/ontology")
        assert r.status_code == 200
        body = r.json()
        assert body["version"].startswith("v1")
        assert len(body["nodes"]) > 30
        assert len(body["edges"]) > 20

    def test_node_types(self, client: TestClient) -> None:
        r = client.get("/api/ontology/nodes")
        assert r.status_code == 200
        names = {n["name"] for n in r.json()}
        # AI-specific types must be present.
        assert {"Model", "Prompt", "Tool", "MemoryStore"} <= names

    def test_edge_types(self, client: TestClient) -> None:
        r = client.get("/api/ontology/edges")
        assert r.status_code == 200
        names = {e["name"] for e in r.json()}
        assert {"PROMPT_INJECTABLE_INTO", "TOOL_INVOKABLE_BY"} <= names


class TestSecurityStubs:
    """v0.1 contracts — shape must be stable even though content is empty."""

    def test_attack_paths_empty_list(self, client: TestClient) -> None:
        r = client.get("/api/security/attack-paths")
        assert r.status_code == 200
        assert r.json() == []

    def test_incidents_empty_list(self, client: TestClient) -> None:
        r = client.get("/api/security/incidents")
        assert r.status_code == 200
        assert r.json() == []

    def test_policy_vacuous_pass(self, client: TestClient) -> None:
        r = client.get("/api/security/policy")
        assert r.status_code == 200
        body = r.json()
        assert body["passed"] is True
        assert body["risk_score"] == 0.0
        # Default tenant when no header is supplied — ADR-0003.
        assert body["tenant_id"] == "default"


class TestTenantBinding:
    """ADR-0003: every security endpoint receives a tenant binding.

    Single-tenant deployments use ``"default"`` implicitly; multi-tenant
    deployments pass an explicit ``X-Tenant-ID`` header.
    """

    def test_default_tenant_when_header_absent(self, client: TestClient) -> None:
        r = client.get("/api/security/policy")
        assert r.status_code == 200
        assert r.json()["tenant_id"] == "default"

    def test_explicit_tenant_propagates_to_response(self, client: TestClient) -> None:
        r = client.get(
            "/api/security/policy",
            headers={"X-Tenant-ID": "acme-corp"},
        )
        assert r.status_code == 200
        assert r.json()["tenant_id"] == "acme-corp"

    def test_malformed_tenant_rejected(self, client: TestClient) -> None:
        # Spaces, slashes, and special chars must be rejected before the
        # request reaches a router.
        for bad in ["has space", "has/slash", "'; DROP", "../etc/passwd", ""]:
            r = client.get(
                "/api/security/policy",
                headers={"X-Tenant-ID": bad},
            )
            assert r.status_code == 400, f"expected 400 for tenant {bad!r}, got {r.status_code}"

    def test_tenant_at_max_length_accepted(self, client: TestClient) -> None:
        # 64 chars: 1 leading alphanumeric + 63 from the suffix class.
        long_tenant = "a" + ("b" * 63)
        r = client.get(
            "/api/security/policy",
            headers={"X-Tenant-ID": long_tenant},
        )
        assert r.status_code == 200
        assert r.json()["tenant_id"] == long_tenant

    def test_tenant_too_long_rejected(self, client: TestClient) -> None:
        too_long = "a" + ("b" * 64)
        r = client.get(
            "/api/security/policy",
            headers={"X-Tenant-ID": too_long},
        )
        assert r.status_code == 400
