# Architecture Decision Records

Decisions are numbered and immutable. If a decision changes, a new ADR supersedes the old one; the old one stays in the tree marked `Superseded by: NNNN`.

| # | Title | Status |
|---|---|---|
| [0001](./0001-graph-first-architecture.md) | Graph-first architecture | Accepted |
| [0003](./0003-tenant-scoping-discipline.md) | Tenant Scoping Discipline | Accepted |
| [0004](./0004-saas-multi-tenancy-out-of-scope.md) | SaaS multi-tenancy out of scope for v1.0 | Accepted |
| [0005](./0005-llm-scanner-grounding-contract.md) | LLM scanner grounding contract | Accepted |

> ADR-0002 is reserved for the Probabilistic Mitigation model in compliance mapping (Phase 3 deliverable). Slot held to keep numbering stable.

## Authoring a new ADR

1. Pick the next number.
2. Copy the template structure from ADR 0001 — Status, Date, Deciders, Consulted, Superseded by, Context, Decision, Rationale, Consequences, Alternatives reconsidered, References.
3. Open a PR. ADRs merge via lazy consensus with a 72-hour veto window for changes affecting graph schema, agent protocols, or the policy interface (per `GOVERNANCE.md`).
