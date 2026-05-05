# Demo Recording Guide — Agentic Security Platform

Audience: launch-post / talk demo. Length target: 3–4 minutes. The narrative
arc is **inventory → attack path → mapping → reproduce the attack**.

The local stack runs under `podman compose` (drop-in for `docker compose`)
from the repo root using `docker-compose.yml`. Five services:

| Service        | Port(s)                   | URL                                  |
|----------------|---------------------------|--------------------------------------|
| frontend       | 3000                      | http://localhost:3000                |
| asp-api        | 8000                      | http://localhost:8000/api/healthz    |
| Neo4j          | 7474 (browser), 7687 bolt | http://localhost:7474                |
| OPA            | 8181                      | http://localhost:8181/health         |
| OTel collector | 4317/4318/13133           | http://localhost:13133               |

The vulnerable RAG target runs separately at `localhost:8001` (uvicorn,
not in the compose file).

---

## 1. Pre-flight (do this 15 min before recording)

### 1a. Bring the stack up

```bash
cd ~/clouddev/agentic-security-platform

# Make sure the podman machine is running and has enough headroom.
# Cytoscape + Next.js dev mode on 4 GB feels sluggish on a laptop;
# 8 GB is much smoother on camera.
podman machine list
podman machine stop  || true
podman machine set --cpus 4 --memory 8192
podman machine start

# .env is expected by docker-compose.yml — copy from example if missing.
[ -f .env ] || cp .env.example .env

podman compose up -d --build
podman compose ps          # all five should be 'running' / 'healthy'
```

Smoke-test each service before you hit record:

```bash
curl -sf http://localhost:8000/api/healthz | jq
curl -sf http://localhost:7474            > /dev/null && echo neo4j ok
curl -sf http://localhost:8181/health     > /dev/null && echo opa ok
open http://localhost:3000                # frontend should render the hero card
```

If `asp-api` 500s on `/api/security/attack-paths`, Neo4j is reachable but
empty — go straight to step 1b.

### 1b. Seed the graph so the demo has something to show

The frontend hero (`frontend/app/page.tsx`) renders *"ASP found N attack
paths"* off the live API. With an empty graph, N = 0 and every panel says
"seed the demo graph". You want non-zero numbers on screen.

The seed is profile-driven. Each demo target has its own YAML under
`targets/`. The bundled `targets/vulnerable-rag-app.yaml` declares which
node IDs the seed expects the connector to have produced and which
security-semantic edges to wire between them.

> **Note:** the connector + seed run on your host machine, not inside
> the asp-api container. The container is the runtime API service; the
> connector is a workspace package you run locally. Use the published
> Neo4j port (`bolt://localhost:7687`), not the compose-internal
> hostname.

```bash
# 1) Static scan: produce ontology-typed nodes from the vulnerable RAG repo.
uv run python3 -m connectors.github.src \
    --repo-path ./examples/vulnerable-rag-app \
    --neo4j-uri bolt://localhost:7687 \
    --neo4j-user neo4j \
    --neo4j-password changeme

# 2) Seed the security-semantic edges (PROMPT_INJECTABLE_INTO, CALLS_TOOL, …)
#    that the connector can't statically infer. Idempotent (MERGE).
#    The seed verifies expected_nodes exist before writing any edges and
#    aborts with a "did you run the connector?" error if they don't.
uv run python3 scripts/seed_graph.py \
    --target targets/vulnerable-rag-app.yaml \
    --neo4j-uri bolt://localhost:7687 \
    --neo4j-user neo4j \
    --neo4j-password changeme

# 3) Confirm the API now returns paths with OWASP mappings.
curl -s http://localhost:8000/api/security/attack-paths \
  | jq '.paths | length, .[0].mappings'
```

Reload `localhost:3000`. The hero should now read *"ASP found 3 attack
paths"* (or whatever the seed produces) and the Agentic-coverage card on
the right should have at least one OWASP-AGENTIC bullet.

#### Onboarding a different GitHub repo as the demo target

If you want the demo to scan a different vulnerable RAG (or any other
agentic app) hosted on GitHub:

```bash
# 1) Clone the GitHub repo. The clone directory name becomes the
#    Repository:<name> ID, so keep it consistent with what you'll
#    declare in the YAML.
git clone https://github.com/<org>/<repo>.git ~/clouddev/asp-demo-targets/<repo>

# 2) Dry-scan to discover the node IDs the parsers will produce.
#    No bind-mount needed — the connector runs on the host and reads
#    the host clone path directly.
uv run python3 -m connectors.github.src \
    --repo-path ~/clouddev/asp-demo-targets/<repo> \
  | jq '.nodes[] | {node_type, id}'

# 3) Author targets/<repo>.yaml. Copy targets/vulnerable-rag-app.yaml,
#    paste the dry-scan IDs into expected_nodes, then write the edges
#    block — those are per-target judgment calls (which tool is over-
#    privileged, which corpus is unsanitized, which memory store is
#    poisonable). Each edge takes a rationale that surfaces in code
#    review. The reconciliation runner does most of this for you:
#      uv run python3 scripts/reconcile_target.py \
#          --target targets/<repo>.yaml \
#          --repo ~/clouddev/asp-demo-targets/<repo> \
#          --enable-llm

# 4) Live scan + seed against the new profile.
uv run python3 -m connectors.github.src \
    --repo-path ~/clouddev/asp-demo-targets/<repo> \
    --neo4j-uri bolt://localhost:7687 --neo4j-password changeme

uv run python3 scripts/seed_graph.py \
    --target targets/<repo>.yaml \
    --neo4j-uri bolt://localhost:7687 --neo4j-password changeme
```

If step 5's seed aborts with `expected nodes are missing from Neo4j`,
the connector and the profile disagree — re-run the dry-scan and reconcile
`expected_nodes` IDs against what came out.

The two scanner limits to know about: the SDK→Model inference in
`connectors/github/src/scanner.py::_SDK_MODEL_MAP` only knows
`anthropic` / `openai` / `google-generativeai`, and the parsers expect
`requirements.txt` / `tools.py` / `model.py` / `corpus/` / `memory.py` at
the repo root. Repos that nest these under `src/` need the parsers
extended or the files symlinked to the root before scanning.

### 1c. Start the vulnerable RAG target

This is the system the platform claims is vulnerable. You'll run the live
attack against it in scene 4. Start it now so you don't fumble during the
take.

```bash
cd examples/vulnerable-rag-app
source .venv/bin/activate
# Leave ANTHROPIC_API_KEY unset to use the deterministic mock model — the
# attack still fires, and you don't burn API credits during rehearsal.
uvicorn app:app --port 8001 &
curl -sf http://localhost:8001/health || curl -s http://localhost:8001/  # whichever it exposes
```

Leave that terminal visible — you'll show it on screen during scene 4.

### 1d. Stage the browser

Open these four tabs in this order, in a clean profile (no extension
toolbars, no bookmarks bar):

1. `http://localhost:3000`            — overview / hero
2. `http://localhost:3000/graph`      — attack-path explorer
3. `http://localhost:7474`            — Neo4j browser (login `neo4j` /
   `changeme`, run `MATCH (n) RETURN count(n)` once and leave the result)
4. A terminal pane with the `attack.py` command pre-typed but **not**
   executed.

Set the browser zoom to **110–125%**. Default font sizing reads as
"developer screenshot," not "talk demo."

### 1e. Recording environment

- Resolution: record at **1920×1080** or **2560×1440**. If you're on a
  Retina display, set the screen to a scaled "looks like 1440 × 900" or
  "1680 × 1050" so text is readable when the video is downscaled.
- Hide the macOS dock (`⌘⌥D`), hide the menu bar via System Settings →
  Control Center → "Automatically hide menu bar: always", silence
  notifications (Focus → Do Not Disturb).
- Close Slack, Mail, calendar — anything that can pop a banner.
- Quiet the terminal: `clear && PS1='$ '` and turn off any oh-my-zsh
  segment that prints git status / hostname.
- Browser: incognito or fresh profile so autofill doesn't leak under the
  cursor.

### 1f. Recording tool

| Tool      | Why pick it                                                       |
|-----------|-------------------------------------------------------------------|
| **Screen Studio** ($) | Auto-zoom on cursor, smooth cursor, click highlights. Best polish-per-effort for launch demos. |
| **ScreenFlow** ($)    | Heavier editor, fine if you already own it.                  |
| **OBS Studio** (free) | More setup, but the only option if you want a webcam PIP and live-mix. |
| **QuickTime** (free)  | Fine for a rehearsal cut. Don't ship the launch demo from QT — no zoom, no cursor highlights. |

Set the recorder to capture **system audio off, mic on**. Demo audio
beeps from the shell or browser are pure distraction.

---

## 2. Recording — scene-by-scene

Total: ~3 minutes 30 seconds. Record each scene as a separate take and
stitch in post — fewer reshoots, fewer "uh"s.

### Scene 1 — Hero (0:00–0:30)

**Show:** `http://localhost:3000`

**Beat:** the green API-status pill, the "ASP found N attack paths"
headline, the three metric cards (Attack paths / OWASP Agentic mapped /
Highest score), and the live attack-path queue underneath.

**Say (script):**
> "This is the Agentic Security Platform. It's an open-source,
> graph-native security platform for AI-native applications. The headline
> isn't a static mockup — it's the live count of attack paths the API
> just returned, mapped to the OWASP Agentic Top 10 at query time."

**Cursor work:** hover the green pill (lands the "live API" point), then
sweep across the three metric cards left to right.

### Scene 2 — Attack-path explorer (0:30–1:30)

**Show:** click **View graph** → `/graph`.

**Beat:** the Cytoscape canvas renders the path. A node lights up for
each ontology type — `RAGIndex`, `File`, `PromptTemplate`, `Model`,
`Tool`, `MemoryStore` — colored by category (AI / data / code).

**Say:**
> "The graph is the system of record. Every node here came from a
> static scan of a real repository — `examples/vulnerable-rag-app`.
> The edges in red — `PROMPT_INJECTABLE_INTO`, `USES_PROMPT`,
> `CALLS_TOOL`, `WRITES_TO` — encode how those components interact at
> runtime. That's the path: untrusted document, into a prompt, into a
> model, into an over-privileged tool, into an exfil sink."

**Cursor work:** trace the path with the cursor, slow. Click each node
in the path so the side panel updates with its properties. Pause on the
`Tool:export_data` node — that's the privileged tool.

### Scene 3 — OWASP mapping (1:30–2:00)

**Show:** still on `/graph`, but call out the side-panel chips
(`ASI-01`, `LLM06`, `ASI-02`). Then back to `/` and zoom on the
red-bordered OWASP bullets.

**Say:**
> "Each path is annotated with OWASP mappings — LLM Top 10 2025 and
> Agentic Top 10 2026 — resolved from ontology metadata. So the
> conversation with security leadership stops being 'we may be exposed
> to prompt injection' and starts being 'here is the path, here are the
> nodes, here is the OWASP category.'"

### Scene 4 — Reproduce the attack (2:00–3:00)

**Show:** terminal in the foreground, browser tab still visible.

**Run:**

```bash
# Benign question first — sets the baseline.
curl -s http://localhost:8001/chat -H "content-type: application/json" \
  -d '{"message": "What is our refund policy?"}' | jq

# The attack — same surface, but the retrieved context contains the
# injected document the platform flagged.
python attack.py
ls -lh exfil/
cat exfil/export-*.json | jq '.session_memory[0]'
```

**Say:**
> "The platform predicted this attack path statically. Now I'll fire it
> against the running app. Same endpoint as the benign question — the
> only difference is which document gets retrieved into the prompt. The
> model gets prompt-injected, calls `export_data`, and writes session
> memory to disk. The graph said this was reachable. The runtime
> confirms it."

**Cursor work:** flick to the file listing (`ls -lh exfil/`) so the
viewer sees a JSON file appear with a fresh timestamp. That's the
"reduced to practice" beat.

### Scene 5 — Close (3:00–3:30)

**Show:** the Neo4j browser tab with the path query result, then back to
the `/graph` page.

**Run in Neo4j browser:**

```cypher
MATCH p = (s)-[:PROMPT_INJECTABLE_INTO]->(:PromptTemplate)
        -[:USES_PROMPT]->(:Model)
        -[:CALLS_TOOL]->(t:Tool)
WHERE s.tenant_id = 'default'
RETURN p
```

**Say:**
> "Every API response and frontend view derives from this graph. That's
> the architectural decision in ADR-0001 — the security graph is the
> domain, not an implementation detail. It's what lets us answer
> attack-path questions across code, infrastructure, models, prompts,
> tools, and data in one query."

End on the `/graph` page (visual punctuation).

---

## 3. Post-production checklist

- Trim dead air at the start and end of each scene.
- Add a single full-screen title card before scene 1 ("Agentic Security
  Platform" + version + date). Keep it under 2 seconds.
- Add lower-thirds for URLs the first time each one is on screen
  (`localhost:3000`, `/graph`, `:8001/chat`). Helps re-watchers.
- Don't background-music it. The narration carries.
- Export H.264 1080p, ≤30 Mbps. Anything bigger is wasted on YouTube /
  LinkedIn re-encode.
- Watch the cut at 1.25× before publishing. If it drags at 1.25×, it's
  too slow at 1×.

---

## 4. Troubleshooting on the day

| Symptom                                           | Fix                                                                 |
|---------------------------------------------------|---------------------------------------------------------------------|
| `localhost:3000` says "API unreachable"           | `podman compose logs asp-api` — usually Neo4j wasn't healthy yet. `podman compose restart asp-api`. |
| Hero says 0 attack paths                          | Re-run the seed steps in 1b. The seed is idempotent.                |
| `/graph` is blank                                 | Open the browser dev console — Cytoscape needs the API to return at least one path. Same fix as above. |
| `attack.py` doesn't write to `exfil/`             | Check `ANTHROPIC_API_KEY`. Unset it to fall back to the mock model — the attack still fires deterministically. |
| Frontend dev-mode HMR repaints mid-take           | Restart the frontend container right before recording so the first paint is fresh: `podman compose restart frontend`. |
| `podman compose` claims a port is in use          | Something else owns 3000/8000 — `lsof -i :3000` and kill it. Common culprit: a leftover `next dev` outside the container. |

---

## 5. Tear-down

```bash
podman compose down                       # stop containers, keep volumes
# or, full reset (drops the seeded graph):
podman compose down -v
pkill -f 'uvicorn app:app'                # the vulnerable-rag-app
```
