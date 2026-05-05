# ADR 0001 — Graph-first architecture

- **Status**: Accepted
- **Date**: 2026-04-24
- **Deciders**: Founding maintainers
- **Consulted**: Reference architecture diagram (Agentic AI-Driven Security SDLC, G-SIB Ready), OSS proposal review
- **Superseded by**: —

## Context

The Agentic Security Platform has to answer a question that conventional scanning tools cannot answer well: *is this issue actually exploitable in our environment?* The answer depends on relationships — between a public API, an over-privileged IAM role, a sensitive database, a prompt-injectable RAG source, and a tool a model can invoke — not on any single finding in isolation.

Several organizational designs are possible:

**Option A: Flat findings store with correlation at query time.** Store scanner outputs in Postgres or a SIEM; correlate by foreign-key joins and views. This is how most AST/SCA/CSPM products have historically worked.

**Option B: Document store with denormalized risk objects.** Elasticsearch or MongoDB, with each finding carrying a denormalized "context" blob. Tools like Wiz historically leaned in this direction before converging toward graph models.

**Option C: Graph database as the central system of record.** All components — code, identity, infrastructure, data, AI application elements (models, prompts, tools, RAG, memory), security findings, runtime events — are nodes and edges in one graph. Risk is expressed as graph traversals.

## Decision

We adopt **Option C** and make it a load-bearing architectural commitment: the Security Graph is the platform's single source of truth. Everything else — API handlers, agents, the policy engine, compliance evidence, the frontend — derives from the graph. The graph is not an implementation detail of one service; it is the domain.

Three concrete consequences follow:

1. The **graph ontology is a first-class, versioned artifact**. It lives in `packages/asp-core/src/asp_core/graph/ontology/v1/` as a set of YAML files with a Pydantic-typed loader. Breaking changes bump the major version. Mappings to external frameworks (OWASP LLM Top 10 2025, OWASP Agentic Top 10 2026, MITRE ATLAS, NIST CSF, ...) live in sibling files and are merged at load time.

2. The **ontology defines the platform's public contract**, not just its internal schema. The API exposes it at `/api/ontology`; the CLI prints and validates it; the frontend can consume it to render type-aware UIs; other teams' agents can consume it via MCP to know what the Security Graph can answer. If the ontology changes, all downstream consumers are automatically aware.

3. Domain logic that manipulates graph concepts lives in `asp-core` and must not import any database client. Only `asp-adapters` speaks Cypher. This is classic hexagonal architecture and keeps the core unit-testable without Docker.

## Rationale

**Why graph, not a flat findings store.** The questions that differentiate this platform from a scanning tool are path queries: "is there a path from an untrusted input channel through a prompt-injectable RAG source into a model that can invoke a tool with write-permission to a sensitive database?" That question compiles naturally into Cypher. Expressing the same thing as JOINs over a findings table is possible but brittle, slow, and unreadable. Documentation of the same risk pattern is easier too — a graph schema diagram explains in one picture what a SQL schema hides across ten tables.

**Why Neo4j first, not a multi-model or newer alternative.** Neo4j has the largest Cypher ecosystem, mature Graph Data Science algorithms, and is what every existing security-graph reference implementation (BloodHound, CloudQuery-on-Neo4j, Dynatrace's Davis, Uber's security graph) has used. Memgraph and FalkorDB are interesting alternatives; we design the adapter layer so that migration is possible, but we commit to one default for the v0.1 code path. Multi-database abstractions tend to be the worst of both worlds at v0.1 scale.

**Why the ontology is versioned and external to code.** The alternative — Python dataclasses in `schema.py` — couples every downstream consumer to a code release. YAML + a loader lets the ontology evolve independently, lets auditors read it directly, and lets non-Python tools (the frontend, other teams' agents, compliance tooling) consume it without importing Python. Versioning prevents breakage when we add new AI node types (which we will, quickly, as the agentic landscape moves).

**Why mappings are a separate layer, not baked into node definitions.** Framework mappings change more often than ontology structure. OWASP releases a new Agentic Top 10 each year; MITRE ATLAS adds techniques quarterly; regulators drop new controls on their own cadences. Keeping mappings in sibling files means updating a mapping is a one-file PR that doesn't touch the ontology itself, and conflicts stay localized.

**Why AI-specific edges are native, not tags on generic edges.** `PROMPT_INJECTABLE_INTO`, `TOOL_INVOKABLE_BY`, `MEMORY_POISONABLE_BY`, `DATA_POISONABLE_BY`, `HALLUCINATION_IMPACTS`: these are the platform's reason to exist. Modeling them as first-class edges rather than `edge.tag == "prompt_injectable"` means they're discoverable in the schema, queryable efficiently, and unambiguous in security reviews. The cost is a slightly larger edge-type catalog; the benefit is that every piece of tooling understands what the platform is actually watching for.

## Consequences

Positive:

- Path queries — the interesting ones — are idiomatic and fast
- Adding new node/edge types is a YAML edit plus a test, not a migration
- The ontology becomes a teaching artifact: a new contributor reads one directory and understands the domain
- Compliance mapping is declarative, not code
- The adapter boundary is obvious: if `neo4j` is imported outside `asp-adapters`, it's a bug

Negative / limits:

- Neo4j Community Edition lacks built-in multi-tenancy; we carry that cost until Phase 4 when tenant-scoped subgraphs + OPA authz arrive
- Cypher is a less familiar query language than SQL for most engineers joining the project; we compensate with a query library (`asp-core/graph/paths.py`) of canonical attack-path queries that don't require users to write Cypher themselves
- Graph-database scale-out is still an active area; we will hit scaling decisions around ingestion throughput in Phase 3 and may introduce Redpanda-based buffering ahead of Neo4j writes
- Multi-database portability requires discipline — every Cypher query we write is an assumption that constrains later moves to Memgraph/FalkorDB; APOC-specific procedures in particular will complicate that path

## Alternatives reconsidered

We will revisit this decision if:

- Ingestion throughput requirements exceed what Neo4j can sustain at our target cluster size after reasonable tuning
- A meaningfully better open-source graph engine emerges that has both AI-workload affinity and Cypher compatibility
- Regulatory constraints force us to store raw findings in a system-of-record that is not a graph (in which case the graph becomes a derived projection)

In any of these cases, the adapter-layer split is what makes reconsideration feasible — the domain in `asp-core` does not care what backs the graph.

## References

- Proposal §5.2: "Treat the graph schema as a versioned artifact"
- Neo4j security-graph case studies: BloodHound (AD), CloudQuery+Neo4j (CSPM)
- OWASP Top 10 for LLM Applications 2025: https://genai.owasp.org/resource/owasp-top-10-for-llm-applications-2025/
- OWASP Top 10 for Agentic Applications 2026: https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/
- MITRE ATLAS: https://atlas.mitre.org/
