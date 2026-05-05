# asp-api

FastAPI service for the Agentic Security Platform. Thin — routes defer to `asp-core` for domain logic and `asp-adapters` for I/O. No business rules live here.

## Endpoints (v0.1 scaffold)

- `GET /health` — liveness + readiness
- `GET /api/ontology` — the loaded graph ontology (for clients and docs)
- `GET /api/security/attack-paths` — materialized attack paths (stub; returns empty list in v0.1)
- `GET /api/security/incidents` — active incidents (stub)
- `GET /api/security/policy` — policy evaluation summary (stub)

## Running locally

```
uv run asp-api
```

Environment comes from `.env` at the repo root. See `.env.example`.
