# ADR 0004 — SaaS Multi-Tenancy Out of Scope for v1.0

- **Status**: Accepted
- **Date**: 2026-04-25
- **Deciders**: Founding maintainers
- **Consulted**: Architectural review (Round 2 — deployment scenarios)
- **Related**: ADR-0001 (Graph-first architecture), ADR-0003 (Tenant Scoping Discipline)

## Context

ADR-0003 commits the platform to Day-0 tenant scoping discipline so that logical isolation between trusted environments — dev / staging / prod, or multiple client engagements run by a single consultancy — works correctly from the first commit. That discipline does not address a different deployment scenario: hosting the platform as a SaaS where multiple **mutually untrusted external customers** share one deployment.

That scenario raises a qualitatively different threat model. With trusted internal tenants the adversary is mostly external; cross-tenant leaks are protected against operator error. With untrusted external tenants, every other tenant *is* a potential adversary, and the threat model expands to include:

- Cypher injection breakouts that escape the adapter's tenant precondition
- Side-channel attacks (timing, resource exhaustion, error-message inference) that leak across tenant boundaries
- Tenant-A controlled telemetry that poisons Tenant-B's graph by exploiting an ingestion-path bug
- Resource starvation by one tenant degrading the platform for others
- Compliance and data-residency requirements that vary per tenant
- Audit-log isolation requirements that vary per tenant

Mitigating these credibly requires either Neo4j Enterprise's database-engine-level access control, separate physical Neo4j instances per tenant, or a custom Cypher query-rewriting layer with a security review budget the project does not have. None of these are achievable for an Apache-2.0 OSS project at v1.0 without becoming the project's primary engineering investment for a year.

## Decision

The platform's v0.1 through v1.0 releases are explicitly **not designed for SaaS multi-tenant deployment** — that is, deployment by an operator who hosts the platform on behalf of multiple external customers who do not trust each other. The threat model assumes a single trust boundary at the deployment level: all tenants within one deployment trust the deployment's operator and, transitively, each other.

Concrete consequences:

1. The README capability matrix lists "SaaS multi-tenancy (untrusted tenants)" as out of scope at v1.0, with a link to this ADR.
2. The threat model assumes one trust boundary per deployment. Threats that arise specifically from untrusted-tenant adjacency (Cypher injection breakouts, cross-tenant timing channels, resource-starvation attacks across tenants) are noted as out of scope rather than mitigated.
3. The default Docker Compose, Helm chart, and Kubernetes manifests target single-deployment, multiple-trusted-tenant operation. Examples and quickstart materials reflect this.
4. Documentation explicitly warns operators considering a SaaS deployment that they take on additional security work the platform does not perform for them — at minimum: separate Neo4j instances per tenant, separate compute pools per tenant, and an external authorization layer.

This decision does **not** restrict:

- Single-organization deployments where all tenants share a trust boundary (banks, enterprises with dev/staging/prod, consultancies managing client environments under one engagement contract).
- Future versions adding SaaS multi-tenancy as an explicit goal.
- Downstream forks adopting the platform for SaaS use, with the understanding that the additional hardening is theirs to do.

## Rationale

**Why exclude rather than degrade.** The alternative is shipping something that *looks like* SaaS multi-tenancy — `tenant_id` is present, queries filter on it, OPA enforces some authorization — without the database-engine guarantees that make the isolation real against an adversarial co-tenant. That is worse than excluding the use case entirely, because it invites operators to deploy the platform in a way the threat model does not actually cover.

**Why this is consistent with ADR-0003.** ADR-0003 implements the *discipline* needed for any tenancy model to work. ADR-0004 scopes which tenancy models are claimed at v1.0. The discipline is the prerequisite for ever supporting SaaS multi-tenancy in the future; this ADR just declines to claim that support today.

**Why now, not later.** Operators evaluating the platform need to know what it claims to do *before* they invest in adoption. An MSP that deploys the platform thinking SaaS multi-tenancy is supported, then discovers in production that it is not, has a much worse experience than an MSP that knows the constraint up front and chooses either to deploy one platform instance per customer or to layer their own authorization mechanism on top. Visibility is the kindest possible failure mode.

**Why "v1.0" rather than "forever."** The decision is reversible. The work to support SaaS multi-tenancy credibly — Neo4j Enterprise integration or equivalent isolation, side-channel hardening, per-tenant resource quotas, an external review of the resulting threat model — is real and substantial, but it is not impossible. Marking it "out of scope for v1.0" leaves room for a future major version to take it on if there is funding and demand.

## Consequences

Positive:

- Operators have a clear, written boundary for the platform's intended use.
- The project does not overcommit on isolation guarantees the codebase cannot deliver.
- The security review surface for v1.0 is bounded.
- The threat model can be honest about its assumptions.

Negative / limits:

- A class of potential adopters (MSPs, SaaS security vendors building on top of the platform) is excluded at v1.0. Some will fork; some will wait; some will go elsewhere.
- The `tenant_id` discipline (ADR-0003) ships *looking* like multi-tenant primitives, which may invite confusion. The README and threat model must be unambiguous that the discipline is for trusted tenancy only.
- A future move to SaaS multi-tenancy is non-trivial work, not a configuration change.

## Alternatives reconsidered

We will revisit this decision if:

- A maintainer or contributor commits funded engineering effort to the SaaS multi-tenancy hardening work, including external security review.
- A clearly-articulated downstream user case requires it and is willing to fund the work.
- Neo4j Community gains the access-control features that make adapter-layer enforcement of untrusted-tenant isolation tractable.

## References

- ADR-0001 — Graph-first architecture
- ADR-0003 — Tenant Scoping Discipline
- `docs/architecture/threat-model.md` — explicit scope note
- `README.md` — capability matrix entry
