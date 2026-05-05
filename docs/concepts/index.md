# Concepts

This section explains the mental model the platform operates on. If the code surprises you, the cause is usually a concept you haven't internalized yet.

Content lands here as the platform matures. For v0.1 the substance is in:

- [ADR 0001 — Graph-first architecture](../adr/0001-graph-first-architecture.md)
- The ontology itself: `packages/asp-core/src/asp_core/graph/ontology/v1/`

## Planned pages

- **The Security Graph**: nodes, edges, and why relationships are the unit of risk
- **Trace ↔ graph correlation**: how OpenTelemetry spans become graph evidence
- **The tri-agent model**: Red proposes, Blue correlates, Green remediates
- **Policy-as-code**: one Rego bundle, four enforcement points
- **Compliance-as-code**: OSCAL component definitions backed by graph queries
