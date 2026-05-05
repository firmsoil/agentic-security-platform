# Launch execution checklist — operator runbook

Step-by-step commands to take the codebase from its current state to a
shipped launch. Every step is something you run on your MacBook;
nothing here is automated by Claude or CI yet.

Estimated total wall-clock: **8–14 hours** spread across 4–5 weeks,
not including waiting for things you've kicked off.

Estimated API spend: **~$5–25** across all parity / reconciliation /
golden-recording / adversarial-sweep runs. Cap is `--max-llm-tokens
200000` per scan; the `scripts/estimate_llm_cost.py` helper (Tier 1
follow-up) will give exact numbers per target.

---

## Phase 0 — Pre-flight (15 min)

Confirm your environment is ready before spending API budget on it.

> **Important: connector + seed run on the host, not inside the container.**
> The asp-api Dockerfile (`packages/asp-api/Dockerfile`) is a minimal
> runtime image that only carries the API's transitive workspace deps.
> The connector, the seed script, and the prompts/profile/target
> directories are not in that image by design — they are *tooling*,
> not runtime services. All connector and seed commands below run
> from your local checkout against the *published* Neo4j port
> (`bolt://localhost:7687`), not the compose-internal hostname
> (`bolt://neo4j:7687`).

```bash
cd ~/clouddev/agentic-security-platform

# 1. Bring the dev stack up. podman compose works as a drop-in for docker compose.
podman machine list                      # confirm machine is running
podman compose up -d --build
podman compose ps                         # all five containers should be 'running'

# 2. Smoke-test each service.
curl -sf http://localhost:8000/api/healthz | jq
curl -sf http://localhost:7474            > /dev/null && echo "neo4j ok"
curl -sf http://localhost:8181/health     > /dev/null && echo "opa ok"
open http://localhost:3000                # frontend should render the hero card

# 3. Make sure your local venv has the connector + scripts synced.
#    If you don't have uv: curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync --all-packages --dev

# 4. Confirm the seeded bundled-demo path still lights up the frontend.
#    Run from the host. Use bolt://localhost:7687 (published port).
uv run python3 -m connectors.github.src \
    --repo-path ./examples/vulnerable-rag-app \
    --neo4j-uri bolt://localhost:7687 --neo4j-password changeme

uv run python3 scripts/seed_graph.py \
    --target targets/vulnerable-rag-app.yaml \
    --neo4j-uri bolt://localhost:7687 --neo4j-password changeme

# Reload localhost:3000 — the hero should read "ASP found N attack paths"
# with N > 0. If N is 0, the seed didn't write — re-check the connector
# step finished without errors.

# 5. Confirm at least one LLM API key is exported.
echo "${ANTHROPIC_API_KEY:-MISSING}" | head -c 20
echo "${OPENAI_API_KEY:-MISSING}"    | head -c 20
# At least one should print a real prefix, not "MISSING".

# 6. Confirm full test suite still green from your local checkout.
uv run pytest connectors/github/tests/ scripts/tests/    # ~180 passed expected
```

**Stop here if anything fails.** The downstream phases all assume this
runs clean.

---

## Phase 1 — Close week 2 (parity test) — 30 min, ~$0.50

Goal: prove the LLM scanner reproduces the Python static scanner's
output on the bundled demo. This is the load-bearing trust signal for
the launch.

```bash
# Run the parity test. -s shows the parity report inline.
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}" \
  uv run pytest connectors/github/tests/test_parity_python.py -v -s
```

**Expected output:** `1 passed`. Inline report shows the static scanner
produced N nodes, the LLM scanner produced N nodes, all IDs match,
property diffs are zero or limited to model-narrated fields
(`description` enrichment).

**If it fails with `missing_in_llm`:** an extraction prompt is missing
something the static scanner finds. Iterate on the relevant prompt
under `prompts/`, save (this bumps `prompt_sha` so the cache invalidates
cleanly), re-run the test. ≤3 iterations expected.

**If it fails with `extra_in_llm`:** the model is hallucinating. Check
the rejection log printed to stdout — the orchestrator's static check
should have caught any wrong file_path / sha_drift. If those passed and
the verifier still accepted, the prompts under "What NOT to extract"
need tightening.

**Decision gate:** Once parity passes, check it in by running the
runner script and inspecting:

```bash
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}" \
  uv run python3 scripts/run_parity_test.py
echo "Exit: $?"
# 0 = parity strict-match. Week 2 is done.
```

Then record the LLM-augmented golden so future regressions are caught
in CI:

```bash
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}" \
  uv run python3 scripts/record_golden.py \
    --repo examples/vulnerable-rag-app \
    --enable-llm \
    --output connectors/github/tests/fixtures/vulnerable-rag-app.llm.golden.json

git add connectors/github/tests/fixtures/vulnerable-rag-app.llm.golden.json
git commit -m "test(connector): add LLM-augmented golden for vulnerable-rag-app"
```

---

## Phase 2 — Week 3, target J1 (LangChain4j) — 2–3 hours, ~$2

### 2a. Clone

```bash
mkdir -p ~/clouddev/asp-demo-targets
cd ~/clouddev/asp-demo-targets
git clone https://github.com/langchain4j/langchain4j-examples.git
```

No bind-mount needed — connector runs on the host. The repo path the
connector reads is the host clone path:

```bash
export J1_REPO=~/clouddev/asp-demo-targets/langchain4j-examples/customer-support-agent-example
```

### 2b. License + size verification (the 5-min owed task from #16)

```bash
ls ~/clouddev/asp-demo-targets/langchain4j-examples/LICENSE
head -3 ~/clouddev/asp-demo-targets/langchain4j-examples/LICENSE
# Expect: Apache 2.0 license header

find "$J1_REPO" -type f -name '*.java' | wc -l
# Expect: <50
```

If license is anything other than Apache-2.0 or MIT, **stop** and pivot
to fallback target J2 (`kszapsza/spring-ai-rag`) per
`docs/demo-target-candidates.md`.

### 2c. Reconcile against the preliminary profile

```bash
# Manifest-only first — fast, free, catches Repository/Container/Artifact/Model drift
uv run python3 scripts/reconcile_target.py \
  --target targets/customer-support-agent.yaml \
  --repo "$J1_REPO"

# Then with --enable-llm to catch Tool/PromptTemplate/RAGIndex/MemoryStore drift
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}" \
  uv run python3 scripts/reconcile_target.py \
    --target targets/customer-support-agent.yaml \
    --repo "$J1_REPO" \
    --enable-llm
```

**Expected:** the runner reports CONFIRMED for `repo` / `container` /
`model`, and DRIFTED for some subset of the LLM-scope predictions
(`tool` / `prompt_template` / `rag_index` / `memory_store`). Each
DRIFTED entry suggests an exact one-line YAML edit.

**Apply the edits manually** — open `targets/customer-support-agent.yaml`,
update each `expected_nodes.<alias>.id` per the runner's suggestion.

If `MISSING (rag_index)` reports — the example doesn't ship a corpus.
You have two choices:

- **Fork the repo** to add a `src/main/resources/terms-of-use/` directory
  with one canonical injection document (per the candidates doc), then
  point the bind-mount at your fork.
- **Drop `rag_index` from the profile** entirely, also drop the
  `PROMPT_INJECTABLE_INTO source: rag_index` edge. The demo's attack-
  path then comes through the memory-poisoning path only, not the
  corpus-injection path. Less visually punchy but honest.

Re-run reconciliation until it reports clean (`exit 0`).

### 2d. Live scan → seed → verify graph

```bash
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}" \
  uv run python3 -m connectors.github.src \
    --repo-path "$J1_REPO" \
    --enable-llm \
    --neo4j-uri bolt://localhost:7687 \
    --neo4j-password changeme

uv run python3 scripts/seed_graph.py \
    --target targets/customer-support-agent.yaml \
    --neo4j-uri bolt://localhost:7687 \
    --neo4j-password changeme

# Open the frontend; /graph should now show the J1 attack paths.
open http://localhost:3000/graph
```

### 2e. Record the LLM-augmented golden for J1

```bash
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}" \
  uv run python3 scripts/record_golden.py \
    --repo "$J1_REPO" \
    --enable-llm \
    --output connectors/github/tests/fixtures/customer-support-agent.llm.golden.json

git add connectors/github/tests/fixtures/customer-support-agent.llm.golden.json
```

---

## Phase 3 — Week 3, target N1 (Vercel AI SDK) — 1–2 hours, ~$1.50

Same shape as Phase 2, no fork needed (N1 already has both
`getInformation` and `addResource` tools wired up).

```bash
cd ~/clouddev/asp-demo-targets
git clone https://github.com/vercel-labs/ai-sdk-preview-rag.git
```

No bind-mount needed.

```bash
cd ~/clouddev/agentic-security-platform
export N1_REPO=~/clouddev/asp-demo-targets/ai-sdk-preview-rag

# License check
head -5 "$N1_REPO/LICENSE"

# Reconcile
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}" \
  uv run python3 scripts/reconcile_target.py \
    --target targets/ai-sdk-preview-rag.yaml \
    --repo "$N1_REPO" \
    --enable-llm

# Apply suggested YAML edits, re-run until clean.

# Live scan + seed
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}" \
  uv run python3 -m connectors.github.src \
    --repo-path "$N1_REPO" \
    --enable-llm \
    --neo4j-uri bolt://localhost:7687 --neo4j-password changeme

uv run python3 scripts/seed_graph.py \
    --target targets/ai-sdk-preview-rag.yaml \
    --neo4j-uri bolt://localhost:7687 --neo4j-password changeme

# Record golden
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}" \
  uv run python3 scripts/record_golden.py \
    --repo "$N1_REPO" \
    --enable-llm \
    --output connectors/github/tests/fixtures/ai-sdk-preview-rag.llm.golden.json

git add connectors/github/tests/fixtures/ai-sdk-preview-rag.llm.golden.json
git commit -m "test(connector): add J1 + N1 LLM goldens after week-3 reconciliation"
```

After both targets are reconciled and seeded:

```bash
# Verify all three targets render in /graph (toggle via the explorer).
open http://localhost:3000/graph

# Run the full test suite — every committed golden re-verifies.
uv run pytest connectors/github/tests/ scripts/tests/
# Expect ~180 passed plus your new goldens picked up automatically.
```

---

## Phase 4 — Week 4, adversarial false-positive sweep — half day, ~$3

The launch decision point. Goal: confirm the LLM scanner produces
**zero** Tool/PromptTemplate/RAGIndex/MemoryStore nodes on repos that
genuinely have none.

### 4a. Pick 10 non-RAG-with-tools repos

Mix of stacks. Suggested baseline list (verify each is still active and
permissively licensed before cloning):

- Python: a Flask CRUD app, a CLI tool, a Django project
- Java: a vanilla Spring Boot CRUD service, an Apache Maven plugin
- Node: a Vue starter, a tRPC starter, a basic Next.js marketing site

Clone each into `~/clouddev/asp-demo-targets/sweep/`:

```bash
mkdir -p ~/clouddev/asp-demo-targets/sweep
cd ~/clouddev/asp-demo-targets/sweep
git clone <repo-1>
git clone <repo-2>
# ... etc
```

### 4b. Sweep

```bash
for repo in ~/clouddev/asp-demo-targets/sweep/*/; do
  echo "=== $(basename "$repo") ==="
  ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}" \
    uv run python3 -m connectors.github.src \
      --repo-path "$repo" \
      --enable-llm \
      --max-llm-tokens 100000 \
      2>&1 | jq '.nodes[] | select(.node_type | IN("Tool", "PromptTemplate", "RAGIndex", "MemoryStore")) | {node_type, id}'
done > /tmp/sweep-results.txt 2>&1
```

**Pass:** `/tmp/sweep-results.txt` shows zero Tool/PromptTemplate/
RAGIndex/MemoryStore nodes across all 10 repos.

**Fail:** any one false positive is launch-blocking. Iterate prompts:
tighten "What NOT to extract" sections, re-run the sweep. The
`prompt_sha` change invalidates caches automatically.

### 4c. Decision

- **Pass after ≤3 iterations:** ship Option C as launch headline. Proceed to Phase 5.
- **Pass only after 4+ iterations:** launch is shippable but document the iteration in `docs/llm-scanner.md` so reviewers see the calibration history.
- **Fail to converge:** demote LLM scanner to *"preview"* in `docs/launch-post-draft.md`, ship the deterministic multi-stack manifest scanner as headline. The fallback is documented in ADR-0005 and not embarrassing — it's still a meaningful upgrade over Python-only.

---

## Phase 5 — Week 5, polish + recording — 4–6 hours, ~$1

### 5a. Final doc pass

```bash
# Re-read the launch post draft with the updated paragraph.
$EDITOR docs/launch-post-draft.md

# If you tweaked anything in week 4 (prompts, scanner_version), the
# trust doc may need a sentence update.
$EDITOR docs/llm-scanner.md
```

### 5b. Demo dry-run (record nothing yet)

Run through the full demo recording guide
(`docs/demo-recording-guide.md`) end-to-end against the J1 target.
Time it. If any scene runs over budget, decide what to cut.

### 5c. Record

Per the recording guide. Use Screen Studio (or whichever recorder you
locked in). Record against the most narratively interesting target —
N1's two-attack-paths-from-one-repo story is probably the strongest
visual.

### 5d. Launch checklist

- [ ] `uv run pytest` clean across the workspace
- [ ] `docs/adr/0005-llm-scanner-grounding-contract.md` status: Accepted
- [ ] `docs/launch-post-draft.md` reviewed by deciders
- [ ] `docs/llm-scanner.md` reviewed by deciders
- [ ] `connectors/github/tests/fixtures/*.llm.golden.json` committed
      for every demo target
- [ ] `README.md` capability matrix audit pass complete
- [ ] Demo video recorded, edited, hosted
- [ ] Frontend screenshot up-to-date if the UI shifted

---

## Phase 6 — D-day — 30 min

```bash
# Tag the release.
cd ~/clouddev/agentic-security-platform
git tag -s v0.2.0 -m "v0.2.0 — multi-stack scanner + LLM-assisted source extraction"
git push origin v0.2.0

# The .github/workflows/release.yml workflow is already wired to:
#   - Cosign-sign every wheel and sdist
#   - Generate SLSA L3 build provenance attestations
#   - Build container images
#   - Cosign-sign every container image
#
# Confirm it ran clean:
gh run watch  # GitHub CLI; or check the Actions tab in the web UI

# Publish the launch post.
$EDITOR docs/launch-post-draft.md  # rename / move to wherever the post is published
```

Open the repo for issues / PRs (Settings → General → un-archive if it
was archived during the freeze).

Announce in the venues planned in `docs/launch-post-draft.md`'s
*"For sponsors"* section.

---

## Rollback / abort plans

**If parity test won't converge after week 2:** stop. Either fix the
prompts (most likely) or back out the LLM scanner from the launch
post and ship deterministic-only — not embarrassing, ADR-0005's
documented fallback.

**If a demo target's reconciliation surfaces an architectural issue:**
swap to the candidate doc's fallback (J2 or N3). Profile authoring
has to redo, but the infrastructure doesn't.

**If week-4 sweep produces stubborn false positives:** demote LLM
scanner to "preview" in the launch post. Update `docs/llm-scanner.md`
to reflect the preview status. Tag a v0.2.0-rc1 instead of v0.2.0
to signal the demotion.

**If week 5 runs out of time:** slip launch by a week. Better to ship
under-rehearsed than panicked. The `docs/launch-roadmap.md` calls this
out as the intended use of the buffer.

---

## What this checklist deliberately doesn't cover

- **Post-launch infrastructure** (AWS connector, Redpanda, OTel
  ingestion, Phase 2 agents). Those start *after* the launch ships
  and are tracked in `docs/launch-roadmap.md` Phase 1 remainder + 2 + 3 + 4.
- **Tier 1 codebase follow-ups I named** in the previous plan
  conversation (`--apply-suggestions` flag, cost estimator, CI golden
  workflow). These are leverage-positive but optional. If you want
  them landed before launch, ask in chat — they're each one focused
  session.
- **Marketing / community ops** beyond the launch post itself. Sponsor
  outreach, conference talks, blog cross-posting. Those live in your
  launch playbook, not this engineering checklist.
