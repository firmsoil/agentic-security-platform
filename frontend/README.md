# asp-frontend

Next.js 15 (App Router) + React 19 scaffold for the Agentic Security Platform frontend.

## v0.1 status

This is a scaffold only. It renders a landing page that confirms the API is reachable. The graph visualization (Cytoscape.js), attack-path browser, and incidents dashboard land in Phase 1.

## Local dev

From the repo root:

```
docker compose up frontend
```

Or standalone:

```
cd frontend
npm install
npm run dev
```

Then open http://localhost:3000. The API URL is configured via `NEXT_PUBLIC_API_URL` (defaults to `http://localhost:8000`).
