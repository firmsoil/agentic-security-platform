# Agentic Security Platform

Graph-native, telemetry-driven, agentic security for AI-native applications.

This documentation covers the platform's architecture, concepts, guides, and reference material. If you're new, start with:

- **[Graph-first architecture (ADR 0001)](adr/0001-graph-first-architecture.md)** — the decision that shapes the rest of the system
- **[Threat model of the platform itself](architecture/threat-model.md)** — our own security posture, quarterly-reviewed
- The project [README](https://github.com/agentic-security-platform/agentic-security-platform/blob/main/README.md) — quickstart, capability matrix, roadmap

## What this platform does

It answers one question that conventional scanning cannot: *is this issue actually exploitable in our environment?* The answer depends on relationships — between code, identity, infrastructure, data, AI components (models, prompts, tools, RAG, memory), runtime events, and policy. Those relationships live in one graph. Detection and remediation run as agents over that graph.

## What it doesn't do (yet)

See the capability matrix in the project README. The short version:

- **v0.1 (now)**: graph ontology, API scaffold, CLI, docker-compose dev stack
- **Phase 1**: GitHub + AWS connectors, attack-path queries, graph UI
- **Phase 2**: Red / Blue / Green agents on LangGraph + Temporal
- **Phase 3**: OSCAL-native compliance evidence, Redpanda-backed ingestion
- **Phase 4**: multi-tenancy, SSO, v1.0 release
