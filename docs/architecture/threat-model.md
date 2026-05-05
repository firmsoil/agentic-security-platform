# Threat model — Agentic Security Platform itself

- **Status**: v0.2 — incorporates ADR-0003 (tenant scoping discipline) and ADR-0004 (SaaS multi-tenancy out of scope)
- **Last reviewed**: 2026-04-25
- **Next review due**: 2026-07-25 (quarterly cadence)
- **Owners**: Platform maintainers

> A security platform that has not been threat-modeled against itself is not a credible security platform. This document is that model. It is intentionally incomplete in v0.1 — the goal is to publish one and improve it quarterly, not to wait for a perfect one.

## Scope

This threat model covers the platform's own attack surface: the API, agents, graph, policy engine, OTel ingestion path, MCP bridge, and supply chain. It does **not** cover the *customer* systems the platform protects — that's what the platform itself is for.

**Trust-boundary assumption (per ADR-0004).** This threat model assumes a single trust boundary per deployment. All tenants within one platform instance trust the deployment's operator and, transitively, each other. The platform implements logical tenant scoping (per ADR-0003) so that operator error does not produce cross-tenant leaks between trusted tenants — but it does not defend one tenant against another mutually-untrusted tenant in the same deployment. Operators wishing to host the platform as a SaaS for mutually-untrusted external customers must take on additional hardening that this threat model does not cover (separate Neo4j instances per customer at minimum; see ADR-0004).

## Trust boundaries

```
┌─────────────────────────────────────────────────────────────────┐
│  Untrusted: external HTTP, OTel sources, MCP consumers,         │
│             policy bundles fetched from OCI, PyPI/npm deps      │
├─────────────────────────────────────────────────────────────────┤
│  Semi-trusted: connectors (each isolated, least privilege)      │
├─────────────────────────────────────────────────────────────────┤
│  Trusted: core domain, graph, policy evaluator                  │
├─────────────────────────────────────────────────────────────────┤
│  Highly trusted: secrets store, signing keys, release pipeline  │
└─────────────────────────────────────────────────────────────────┘
```

Crossings between these layers are the places to threat-model most carefully.

## Assets

1. **The Security Graph contents** — accumulated knowledge of customer environments. Confidentiality-sensitive.
2. **LLM provider credentials** — API keys for Anthropic, OpenAI, etc.
3. **Customer-facing write credentials** — GitHub tokens, Slack tokens, ticketing system credentials the Green Agent uses.
4. **Signing keys** — Cosign identities for release artifacts and policy bundles.
5. **Policy bundles** — the Rego rules that decide what passes and fails.
6. **Audit log** — tamper-evident record of agent decisions and human approvals.

## Threats (STRIDE sketch)

| # | Asset / Boundary | Category | Threat | Example | Mitigation |
|---|---|---|---|---|---|
| T-01 | Red Agent process | EoP | Red Agent's offensive capabilities turned against Blue/Green agents or the host | A prompt-injected Red Agent run pivots from "attack-path proposal" to "exfiltrate Green Agent's GitHub token" | Strict process isolation (separate containers, seccomp, read-only FS, dropped capabilities). Red Agent runs with zero customer-write credentials. OPA authz at the adapter layer enforces that Red cannot touch Green's credential namespace. |
| T-02 | LLM credentials | I | Compromised agent leaks provider keys | Keys end up in log output, crash dumps, or prompts | Keys never live in agent context. All LLM calls go through the LiteLLM gateway (in `asp-adapters`), which attaches keys server-side and never returns them. Per-agent tenancy and full audit logging of prompts/responses (but not keys) to the graph. |
| T-03 | Green Agent GitHub write access | T | Prompt-injected Green Agent opens a malicious PR | Indirect prompt injection in a RAG-retrieved issue description tells the agent "also delete .github/workflows" | Green Agent writes only to a designated sandbox repo by default; writes to customer repos require an explicit Temporal human-approval activity; every Green-authored PR is signed with a key derived from agent identity, and the signature is logged to the audit chain. |
| T-04 | Security Graph contents | I | Sensitive details leak via graph queries | An MCP consumer queries the graph and retrieves attack paths from a tenant they don't have scope for | Graph encrypted at rest. Every node and edge carries `tenant_id`; the Neo4j adapter requires an explicit tenant on every read and write (see `_validate_tenant_id`, `upsert_node`, `upsert_edge`, `run_cypher`). The API binds tenant from `X-Tenant-ID` (Phase 2: JWT claim) via `TenantBindingMiddleware` before any router runs. Secret *values* are never stored in the graph — only references (`vault://path/to/secret`). Per ADR-0003 / ADR-0004, this protects trusted-tenant deployments; SaaS multi-tenancy is out of scope. |
| T-05 | OTel ingestion | S, DoS | Attacker sends forged or excessive spans | Flooding the collector with fake spans to poison detections or exhaust storage | mTLS on the OTel collector. Span signing via Sigstore/Fulcio for high-trust sources. Rate limits per source. Anomaly detection on ingestion rate itself. |
| T-06 | MCP server (us as producer) | EoP / I | External agent queries the graph and retrieves content it shouldn't see | A developer's Claude Code session queries attack paths for a tenant it has no scope in | MCP server enforces OIDC + OPA authz per tool call. Every tool call carries a tenant binding (same chokepoint as the HTTP API); cross-tenant queries are blocked at the adapter layer. Audit log entry for every MCP tool invocation. |
| T-07 | Policy bundle (OCI) | T | Compromised policy silently weakens enforcement | An attacker pushes a modified bundle that adds `allow := true` to a critical rule | All policy bundles Cosign-signed. Platform refuses to load unsigned bundles when `ASP_REQUIRE_SIGNED_POLICIES=true` (mandatory in staging/prod). Policy changes require signed Git tags. Diff of loaded-vs-expected policies is reported by Blue Agent. |
| T-08 | Supply chain (our deps) | T | Malicious dependency lands via PyPI or npm | Typosquat on a connector dependency | Every build produces a CycloneDX SBOM. Dependencies pinned with hashes via `uv.lock`. CI scans with Trivy, Grype, OSV-Scanner, and Socket. Connectors run in per-connector containers with minimum privilege, so a compromised connector cannot reach the core. |
| T-09 | Platform operators | R | "I didn't approve that Green Agent PR" | Operator denies having approved a destructive change | All human-in-the-loop decisions are Temporal workflow events. Every approval is signed and appended to an audit log that is itself a graph sub-tree, tamper-evident via a Merkle chain. |
| T-10 | Release pipeline | T | Compromised CI injects backdoored image | GitHub Actions secret exfiltrated, attacker publishes `latest` tag pointing at malicious image | SLSA Level 3 build provenance. Two-person review on release tags. Cosign signatures verified on pull. Reproducible builds for the core image so a divergence from expected digest triggers an alert. |
| T-11 | Agent memory (MemoryStore) | T | Poisoned agent memory biases future decisions | Malicious content in an agent's long-term memory steers a later Green remediation | Memory is principal-scoped. Reads from memory are treated as untrusted input for prompt-injection checks. Memory contents are themselves graph nodes subject to the same analysis the platform runs on customers — we dogfood. |
| T-12 | Self-red-team | — | Adversarial suite drifts and stops catching regressions | `tests/adversarial/` grows stale; new vulnerability classes added without tests | Adversarial suite coverage tracked as a release-blocking metric. Target: 100% of OWASP LLM Top 10 and OWASP Agentic Top 10 by v1.0. Coverage published on every main build. |
| T-13 | Cross-tenant graph poisoning | T, EoP | An ingestion path or an internal caller writes nodes or edges into the wrong tenant's subgraph | An OTel span from Tenant A is dispatched (by bug or by attacker) to a worker that writes into Tenant B's graph; or an adapter caller forgets to pass `tenant_id` and writes appear in the wrong place | Adapter-layer enforcement: every `upsert_node` and `upsert_edge` is keyword-only on `tenant_id`, callers cannot omit it, properties named `tenant_id` are rejected (no smuggling via the property dict), `_validate_tenant_id` enforces the character class, composite (tenant_id, id) uniqueness constraint at the database level. API: `TenantBindingMiddleware` binds `tenant_id` from request before any router; routers receive it via `Depends(get_tenant_id)` so they cannot run without one. Cypher injection chokepoint: the `_safe_label` helper validates labels and relationship types against the loaded ontology *and* a strict `^[A-Z][A-Za-z0-9_]*$` regex, blocking the only path by which label-position attacks could break out. Future work (Phase 1 async ingestion ADR): `tenant_id` will be a required field on every Redpanda topic schema, enforced by the worker before any Cypher write. |

## Out of scope for v0.1

- Formal data-flow diagrams — will be added in v0.2
- Cryptographic review of the audit-chain Merkle construction — needs external review
- Threat model of the Temporal worker pool itself — pending Phase 2
- **SaaS multi-tenant deployment** (mutually-untrusted tenants in one deployment) — explicitly out of scope per ADR-0004. Operators wishing to host the platform as a SaaS take on their own additional hardening.

## Process

- Reviewed quarterly by maintainers
- Any material architectural change (new agent type, new external trust boundary, new credential class) triggers an interim review
- Independent third-party review of this document is a **release blocker for v1.0**

## Related documents

- `docs/adr/0001-graph-first-architecture.md` — graph as the system of record
- `docs/adr/0003-tenant-scoping-discipline.md` — tenant_id discipline implemented (T-04, T-13)
- `docs/adr/0004-saas-multi-tenancy-out-of-scope.md` — trust-boundary scope assumption
- `SECURITY.md` — vulnerability disclosure process
- `tests/adversarial/` — the self-red-team suite (Phase 2+)
