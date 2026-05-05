# asp-core

Pure domain logic for the Agentic Security Platform. **Zero I/O dependencies.**

If a module in this package imports `neo4j`, `kafka`, `httpx`, `anthropic`, or any other client library, that is a bug — it belongs in `asp-adapters`. Core is the layer that describes *what the platform means*, not *how it talks to the outside world*.

## Contents

- `graph/` — the Security Graph ontology (nodes, edges, mappings) and pure path algorithms
- `detection/` — typed detection rules and trace↔graph correlator logic
- `agents/` — agent protocols (ABCs) and immutable context
- `policy/` — policy engine contract (the interface `asp-adapters` implements against OPA)
- `compliance/` — OSCAL pydantic models and evidence collection contracts
- `events.py` — CloudEvents-compatible event model

## Testability

This package ships with unit tests that require nothing beyond Python. If you need Neo4j to test it, the abstraction is wrong — see the adapter layer instead.
