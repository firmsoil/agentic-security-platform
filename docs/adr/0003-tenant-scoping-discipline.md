# ADR 0003 — Tenant Scoping Discipline

- **Status**: Accepted
- **Date**: 2026-04-25
- **Deciders**: Founding maintainers
- **Consulted**: Architectural review (Round 1, 2 — multi-tenancy thread)
- **Supersedes**: An earlier draft proposal that scoped multi-tenancy to "Phase 4." That position has been reversed; see Context.
- **Related**: ADR-0001 (Graph-first architecture), ADR-0004 (SaaS multi-tenancy out of scope for v1.0)

## Context

In the v0.1 scaffold, the platform shipped no notion of tenancy. An earlier draft of the proposal explicitly scoped logical multi-tenancy to "Phase 4," reasoning that Neo4j Community Edition lacks built-in label-based RBAC and that single-tenant deployments would suffice until a SaaS use case justified the cost.

A round-trip architectural review surfaced that this position conflated two genuinely separable concerns:

1. **Tenant scoping discipline** — every node and edge carries `tenant_id`; every adapter session is tenant-bound; every Cypher query filters on tenant; every ingestion payload requires a tenant. This is data-modeling and adapter-layer hygiene. Cost: a few days of work now.

2. **Tenant authorization mechanism** — the database engine itself enforces that user A cannot read nodes owned by tenant B. In Neo4j this is the label-based, property-based fine-grained access control that ships only in Enterprise edition. Replicating it in the adapter layer means writing a custom Cypher query-rewriting engine, which is operationally complex and prone to silent bugs. Cost: weeks to months, plus permanent residual risk.

The earlier "Phase 4" position deferred *both*. The review demonstrated that the first is cheap now and catastrophically expensive later — a year of accumulated graph data plus a year of custom Cypher queries cannot be retrofitted without downtime and silent-leak risk — while the second remains genuinely deferred.

The deployment scenarios in scope at v1.0 are:

- A bank deploys the platform internally, one Neo4j instance, all data is theirs.
- An enterprise has separate dev, staging, and prod environments and wants their security graphs isolated from each other within the same Neo4j cluster to save infrastructure costs.
- A consultancy deploys one platform instance to manage multiple client environments, with each client's findings logically isolated.

Out of scope at v1.0: hosting the platform as a SaaS for mutually untrusted external customers. See ADR-0004 for that decision.

The Enterprise (dev/staging/prod) and Consultancy (multiple-client) scenarios both require tenant scoping discipline from Day 0. The BloodHound deployment model — fresh Docker container per engagement — does not apply, because this platform is continuous and stateful, accumulating telemetry over months. The relevant operational peer is CloudQuery, where a single ingestion pipeline routes data into isolated destinations and tenant scoping is a Day-0 property of the pipeline.

## Decision

The platform implements **tenant scoping discipline** as a Day-0, mandatory property of the data model and adapter layer. Every node and every edge in the Security Graph carries a `tenant_id`. Every adapter operation requires a tenant context. Every ingestion payload supplies a tenant. Every Cypher query filters on `tenant_id`.

The platform does **not** implement a tenant authorization mechanism enforced by the database engine. Cross-tenant query enforcement lives in the adapter layer as a precondition on every operation, not as a Cypher rewriter or a Neo4j RBAC rule. Adapters that do not bind a tenant cannot be constructed.

Concrete commitments:

1. The ontology defines `tenant_id` as an implicit required property on every node type and every edge type. The schema loader validates that no operation produces a node or edge without one.

2. The Neo4j adapter exposes no method that takes node/edge writes without an explicit `tenant_id` parameter. The signature change is breaking; that is the point.

3. The API layer extracts `tenant_id` from request context (header in v0.1; JWT claim from Phase 2 onward) via middleware, before any router runs. Routers receive the tenant via dependency injection; they cannot forge or omit it.

4. Single-tenant deployments use the literal string `"default"` for `tenant_id`. This is the same code path as multi-tenant deployments, with one tenant.

5. A `_safe_label()` helper in the adapter validates Cypher labels and relationship types against the loaded ontology *and* a strict regex (`^[A-Z][A-Za-z0-9_]*$`) before interpolation. This is the only sanctioned way to interpolate identifiers into Cypher. Property values continue to use parameterized queries.

## Rationale

**Why discipline now, mechanism later.** The cost asymmetry is overwhelming. Adding `tenant_id` to a fresh codebase with no production data is a few days of work and produces a uniform, auditable invariant. Adding it after a year of operation requires backfilling millions of nodes and edges, auditing every Cypher query in the codebase, and accepting permanent residual risk that a query was missed — silent cross-tenant leaks rather than errors. The discipline is the cheapest insurance the project will ever buy.

**Why no Cypher rewriter.** Neo4j Community Edition's RBAC limitations are real: label-based and property-based access control enforced by the database is paywalled to Enterprise. Replicating that in the adapter layer means intercepting every Cypher query and modifying its AST, which is brittle, complex, and prone to silent leaks. The review's original concern about "label-based RBAC is too complex for Community" is correct *for that specific mechanism*. It is not a reason to skip the discipline that costs two orders of magnitude less and delivers most of the value.

**Why CloudQuery is the right peer.** BloodHound's tenancy model is "fresh database per engagement" because BloodHound is point-in-time. This platform is continuous and stateful — telemetry, agent memory, and historical findings accumulate over months. The relevant peer is CloudQuery, which routes data from many sources into isolated destinations from Day 0 and where multi-environment usage is the default rather than the exception. Adopting the CloudQuery operational model means a single ingestion pipeline (the eventual Redpanda event bus) consumes telemetry from Dev, Staging, and Prod, and the adapter layer routes by `tenant_id`.

**Why `tenant_id` rather than separate Neo4j databases.** Separate databases per tenant is operationally heavier and does not solve the same problem — three Neo4j clusters to separate dev/staging/prod is a punitive deployment model. The `tenant_id` property approach scales to dozens of tenants on a single cluster and matches the deployment scenarios in scope.

**Why the API extracts tenant via middleware.** Putting the tenant binding at the request boundary, before any router runs, eliminates an entire class of "I forgot to filter" bugs in handler code. Routers receive a tenant they cannot omit. The same pattern applies to ingestion: every payload carries a tenant before it ever reaches a worker.

## Consequences

Positive:

- The data model is correct from Day 0 for every in-scope deployment scenario.
- Cross-tenant graph poisoning (T-13 in the threat model) has a concrete mitigation that's enforced at the adapter layer rather than relied upon by convention.
- T-04 ("Sensitive details leak via graph queries") retains its stated mitigation ("Cross-tenant queries blocked at the adapter layer") because the discipline implements exactly that.
- Future migration to Neo4j Enterprise's strict RBAC is a configuration change, not a data migration — the data model is already compliant.
- The platform aligns operationally with CloudQuery, the correct OSS peer for continuous, multi-environment ingestion.

Negative / limits:

- All adapter call sites had to change. Every test fixture, every example, every connector must pass an explicit tenant. We accept this; it is the cost of getting the invariant right.
- Cross-tenant data leaks are still possible *inside the adapter layer* if a contributor adds a method that does not enforce the precondition. Mitigation: code review discipline, lint rules where possible, and the `_safe_label()` helper as a chokepoint.
- Single-tenant deployments carry a small overhead (one extra property, one extra filter clause per query). This is negligible at any practical scale and is the price of having one code path.
- This ADR does not solve the SaaS multi-tenant case. See ADR-0004.

## Alternatives reconsidered

We will revisit this decision if:

- A new in-scope deployment scenario requires the database engine itself (rather than the adapter) to enforce isolation — at which point the discipline is the *prerequisite* for that move, not an obstacle.
- Profiling shows the per-query tenant filter is a meaningful performance cost (we have not seen this in any comparable graph deployment, but the option remains open).
- Neo4j Community gains property-based access control without paywalling (unlikely but worth tracking).

## References

- ADR-0001 — Graph-first architecture
- ADR-0004 — SaaS multi-tenancy out of scope for v1.0
- `docs/architecture/threat-model.md` — T-04 (graph query leakage) and T-13 (cross-tenant graph poisoning) both depend on this discipline being implemented and remaining in place
- Architectural review threads (Rounds 1 and 2, multi-tenancy)
