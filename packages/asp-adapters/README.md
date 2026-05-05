# asp-adapters

Infrastructure drivers for the Agentic Security Platform. This is the **only** package allowed to import Neo4j, Kafka, HTTP clients, or LLM SDKs. Everything here implements a contract declared in `asp-core`.

## Contents

- `graph/` — Neo4j driver (primary). Future: Memgraph, FalkorDB adapters.
- `telemetry/` — OpenTelemetry ingestion + trace↔graph correlator.
- `llm/` — LiteLLM gateway wrapper with per-agent audit logging.
- `policy/` — OPA HTTP client.
- `mcp/` — MCP server (we expose tools) and client (we consume tools).

## Why this split matters

If a bug lives here, it's an integration bug — there's a real system on the other side of the wire. If the same bug lived in `asp-core`, the abstraction was wrong and the fix is at the interface level. Keep this distinction strict.
