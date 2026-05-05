# ASP GitHub Connector

Repository scanner that produces ontology-typed nodes for the Agentic
Security Platform's Security Graph. Multi-stack since v0.2 — detects
Python, Java, or Node from manifest files at the repo root and dispatches
to the matching stack scanner. Companion LLM scanner (ADR-0005) extracts
the four code-shape node types (`Tool`, `PromptTemplate`, `RAGIndex`,
`MemoryStore`) from non-Python repos with grounded, verified output.

## What it scans

### Manifest pass — deterministic, runs for every stack

| Stack  | Manifest                          | Emits                             |
|--------|-----------------------------------|-----------------------------------|
| Python | `requirements.txt`                | `Artifact[]`, `Model` (via SDK map) |
| Java   | `pom.xml`, `build.gradle[.kts]`   | `Artifact[]`, `Model` (via SDK map) |
| Node   | `package.json`                    | `Artifact[]`, `Model` (via SDK map) |
| All    | (computed)                        | `Repository`, `Container`         |

The SDK→Model maps live next to each stack scanner under
`src/stacks/<lang>/sdk_model_map.py`. Java covers LangChain4j, Spring AI,
and the AWS Bedrock SDK; Node covers `@anthropic-ai/sdk`, `openai`,
LangChain JS, the Vercel AI SDK, and `@aws-sdk/client-bedrock-runtime`.

### Source pass — Python deterministic, Java/Node via LLM scanner

| Stack  | Source files                      | Emits                                                            |
|--------|-----------------------------------|------------------------------------------------------------------|
| Python | `tools.py`                        | `Tool` (from `TOOL_SCHEMAS` / `*_TOOL` literal assignments)      |
| Python | `model.py`                        | `PromptTemplate` (from `SYSTEM_PROMPT` literal)                  |
| Python | `corpus/`                         | `RAGIndex` + `File[]`                                            |
| Python | `memory.py`                       | `MemoryStore` (from `_memory` dict pattern)                      |
| Java   | source files (week 2)             | `Tool` / `PromptTemplate` / `RAGIndex` / `MemoryStore` via LLM scanner |
| Node   | source files (week 2)             | same — LLM scanner with grounding + verification                 |

The connector also creates structural edges: `DEPENDS_ON` (Repository →
Artifact) and `CONTAINS` (RAGIndex → File).

**Attack-potential edges** (`PROMPT_INJECTABLE_INTO`, `TOOL_INVOKABLE_BY`,
`MEMORY_POISONABLE_BY`, `CALLS_TOOL`, etc.) are *not* derived here. They
are seeded from a per-target profile YAML under `targets/` by the
companion seed script `scripts/seed_graph.py`.

## Layout

```
connectors/github/src/
  __init__.py
  __main__.py            # CLI: --repo-path, --repo-url, --stack, --neo4j-*
  detect.py              # stack sniffer (java > node > python precedence)
  scanner.py             # dispatcher; re-exports ScanResult for back-compat
  types.py               # ScanResult dataclass (carries .stack)
  common.py              # Repository/Container/Artifact/Model helpers
  parsers.py             # back-compat shim, re-exports stacks/python/parsers
  writer.py              # ScanResult → Neo4jGraphStore
  stacks/
    python/{__init__,parsers,scanner,sdk_model_map}.py
    java/{__init__,parsers,scanner,sdk_model_map}.py
    node/{__init__,parsers,scanner,sdk_model_map}.py
  llm/                   # ADR-0005 LLM scanner (week-2 work in progress)
    schema.py            # GROUNDED_NODE_SCHEMA + validators
    protocol.py          # StructuredExtractor Protocol
    anthropic_adapter.py # tool-use enforcement
    openai_adapter.py    # response_format=json_schema enforcement
    cache.py             # (commit, scanner_ver, adapter, model, prompt_sha)
    verifier.py          # static checks + second-pass LLM verification
```

## Usage

### Dry-run (no infrastructure required)

```bash
python3 -m connectors.github.src --repo-path ./examples/vulnerable-rag-app
```

Prints the `ScanResult` as JSON — node types, IDs, properties, structural
edges, and the detected stack. Stack auto-detected from manifest files;
override with `--stack {python|java|node}` if the heuristic picks wrong
(e.g. a Python backend with a Node/React frontend at the repo root).

### Live mode (writes to Neo4j)

```bash
# Start Neo4j
podman compose up neo4j -d   # docker compose works too

# Scan
python3 -m connectors.github.src \
    --repo-path ./examples/vulnerable-rag-app \
    --neo4j-uri bolt://localhost:7687 \
    --neo4j-user neo4j \
    --neo4j-password changeme

# Seed attack-potential edges from a target profile
python3 scripts/seed_graph.py \
    --target targets/vulnerable-rag-app.yaml \
    --neo4j-uri bolt://localhost:7687 \
    --neo4j-user neo4j \
    --neo4j-password changeme
```

### Onboarding a different GitHub repo

1. Clone the repo. The clone directory name becomes the `Repository:<name>`
   ID — keep it consistent with what the profile will declare.
2. Bind-mount it into the asp-api container (edit `docker-compose.yml`,
   add `~/path/to/clone:/targets/<name>:ro` under `asp-api.volumes`).
3. Dry-scan to see what node IDs the parsers emit:
   ```bash
   python3 -m connectors.github.src --repo-path /targets/<name> \
     | jq '.nodes[] | {node_type, id}'
   ```
4. Author `targets/<name>.yaml` from `targets/vulnerable-rag-app.yaml` —
   paste the dry-scan IDs into `expected_nodes`, write the per-target
   `edges` block (this is where security-semantic judgment lives).
5. Live scan + seed:
   ```bash
   python3 -m connectors.github.src --repo-path /targets/<name> \
       --neo4j-uri bolt://localhost:7687 --neo4j-password changeme
   python3 scripts/seed_graph.py --target targets/<name>.yaml \
       --neo4j-uri bolt://localhost:7687 --neo4j-password changeme
   ```

The seed verifies every `expected_nodes` ID exists in Neo4j before
writing any edges; it aborts with a "did you run the connector?" error
if the connector and profile are out of sync (rather than silently
no-opping).

### Verify in Neo4j Browser

```cypher
-- All nodes
MATCH (n) WHERE n.tenant_id = 'default' RETURN labels(n), n.id, n.name

-- Attack paths (one of several query families the platform supports)
MATCH p = (s)-[:PROMPT_INJECTABLE_INTO]->(:Prompt)
        -[:USES_PROMPT]->(:Model)
        -[:CALLS_TOOL]->(:Tool)
WHERE s.tenant_id = 'default'
RETURN p
```

## Installation

```bash
# Manifest scanner only (no LLM dependencies)
pip install -e .

# With Anthropic adapter
pip install -e ".[anthropic]"

# With OpenAI adapter
pip install -e ".[openai]"

# Both adapters
pip install -e ".[llm]"
```

The LLM scanner adapters are optional — users who only need the manifest
pass don't pay the SDK install cost. Selection happens at config time
(`--llm-provider {anthropic|openai}` once the orchestrator lands), not
per-request, per the grounding contract in ADR-0005.

## Security

- **No `exec` / `import`** in the Python parsers: tool schemas and prompt
  templates are extracted via `ast.parse` + `ast.literal_eval`. The
  connector never executes code from the scanned repository.
- **Java/Node manifest parsers** are pure XML/regex/JSON — no DSL
  evaluation, no plugin resolution.
- **LLM scanner output is grounded and verified.** Every emitted node
  carries a `grounding` block (file path, line range, file SHA-256,
  evidence, confidence). The verifier re-opens the file, recomputes the
  SHA, and asks the model — through a separate, narrowly-scoped call —
  to confirm or reject the claim. Drift or rejection drops the node
  before it reaches the graph. See ADR-0005 for the full contract.
- **Ontology-validated**: every emitted node and edge type is validated
  against `asp-core`'s ontology YAML at test time.
- **Tenant-scoped**: all graph writes go through
  `Neo4jGraphStore.upsert_node/edge`, which enforces tenant isolation.

## Tests

```bash
# Stack detection
python3 -m pytest connectors/github/tests/test_detect.py -v

# Per-stack manifest parsers
python3 -m pytest connectors/github/tests/test_java_parsers.py -v
python3 -m pytest connectors/github/tests/test_node_parsers.py -v
python3 -m pytest connectors/github/tests/test_parsers.py -v   # Python (back-compat)

# Multi-stack dispatcher
python3 -m pytest connectors/github/tests/test_dispatcher.py -v

# Python-stack scanner integration
python3 -m pytest connectors/github/tests/test_scanner.py -v

# LLM scanner — schema + cache + verifier (no API calls required)
python3 -m pytest connectors/github/tests/test_llm_schema.py -v
python3 -m pytest connectors/github/tests/test_llm_cache.py -v
python3 -m pytest connectors/github/tests/test_llm_verifier.py -v

# Seed script validation
python3 -m pytest scripts/tests/test_seed.py -v
```

Adapter integration tests (real API calls) are gated behind environment
variables and run only when the orchestrator lands in week 2.

## References

- ADR-0001 — graph-first architecture
- ADR-0005 — LLM scanner grounding contract
- `targets/vulnerable-rag-app.yaml` — example target profile
- `prompts/README.md` — prompt catalog and editing rules
