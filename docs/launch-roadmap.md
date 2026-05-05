# Launch roadmap — Option C MVP

Living document. Refresh at the end of each week to reflect what
shipped vs. what slipped. Date stamp at top reflects the last review.

**Last reviewed: 2026-04-27**
**Launch target: ~early-to-mid June 2026** (per the 4–6 week slip
from 2026-04-26, recorded in `memory/launch_option_c.md`)

## Where we are

Week 1 closed cleanly. Week 2 is roughly half-landed.

**Shipped:**
- Multi-stack connector restructure (`connectors/github/src/stacks/{python,java,node}/`)
- Stack detector with documented precedence rules
- Manifest parsers for `pom.xml`, Gradle (Groovy + KTS), `package.json`
- SDK→Model maps for all three stacks (LangChain4j, Spring AI, AWS
  Bedrock SDK on Java; `@anthropic-ai/sdk`, `openai`, LangChain JS,
  Vercel AI SDK, AWS SDK v3 on Node)
- Profile-driven seed (`targets/<x>.yaml`) with `expected_nodes`
  pre-flight verification
- ADR-0005 (LLM scanner grounding contract)
- Prompts directory + Apache-2.0 README + cache-key role
- LLM-scanner internals: JSON Schema + validators, `StructuredExtractor`
  Protocol, AnthropicAdapter (tool-use), OpenAIAdapter (Structured
  Outputs), filesystem cache keyed by `(commit, scanner_version,
  adapter, model, prompt_sha)`, verifier with static checks +
  second-LLM verification
- 93 tests passing across detect / parsers / dispatcher / schema /
  cache / verifier
- J1 + N1 demo targets locked in with placeholder `targets/` profiles
- Top-level `README.md`, `connectors/github/README.md`, and
  `docs/demo-recording-guide.md` updated to reflect the new shape

**Open tasks (tracked in TodoList):**
- #16 — Verify J1 + N1 before week-3 profile authoring
- #17 — Author `targets/customer-support-agent.yaml`
- #18 — Author `targets/ai-sdk-preview-rag.yaml`
- #23 — LLM scanner orchestrator
- #24 — Production `extract_tools.md` prompt

## Plan: 4 weeks to launch

### Week 2 — Finish the LLM scanner shell *(1–2 sessions)*

Goal: end the week with the LLM scanner producing grounded, verified
nodes for `examples/vulnerable-rag-app/` that match the existing
Python static scanner — same IDs, same properties, ±0 nodes. That is
the load-bearing parity proof for the whole MVP.

**Tasks (all currently pending or in-flight):**

- [ ] **#23 — Orchestrator** (`connectors/github/src/llm/orchestrator.py`).
  Function: `scan_with_llm(repo_path, adapter) -> ScanResult`. Walks
  the repo, batches files into the extractor, drives extract → verify
  → assemble, integrates the cache. Honors `--max-llm-tokens` to
  fail-loud on cost overruns rather than silently rack up spend.
- [ ] **#24 — Production `extract_tools.md`**. Replaces the stub.
  Establishes the shape for the other three extraction prompts.
  Critical: the prompt must instruct the model to *cite* file path +
  line range in the response, not narrate around them. Bumps
  `prompt_sha`, invalidates the cache (intentional first-time cost).
- [ ] **Production prompts for `extract_prompt_templates.md`,
  `extract_rag_indices.md`, `extract_memory_stores.md`, `verify_node.md`.**
  Same shape as `extract_tools.md`. Each one bumps `prompt_sha`.
- [ ] **`--max-llm-tokens` flag and budget abort.** Hard-cap default
  of 200k tokens per scan; configurable per-run. Saves the launch
  budget from a runaway prompt.
- [ ] **Adapter integration tests gated on env keys.** Run only when
  `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` is present. CI stays green
  without keys; release CI runs both.
- [ ] **Parity test: LLM scanner vs Python static scanner on
  `examples/vulnerable-rag-app/`.** End of week 2 deliverable. Both
  must produce identical `Tool` / `PromptTemplate` / `RAGIndex` /
  `MemoryStore` IDs and properties. Any diff is either a static-scanner
  miss or an LLM hallucination — both block the week-3 work.

**Decision point (end of week 2):** Does the parity test pass on the
first real run, or does it surface drift the prompts need to fix? If
parity is within one prompt iteration, proceed to week 3. If parity
needs three or more iterations, the week-4 fallback ("LLM scanner as
preview, deterministic-only as headline") becomes the active plan.

### Week 3 — Three-stack live demo

Goal: end the week with all three stacks rendering attack paths in
`/graph`, all three captured as committed golden fixtures, and a
single demo script that switches between them cleanly.

- [ ] **Verify J1 + N1 (#16, ~30 min).** License, source-file count,
  manifest dependencies, tool wiring, corpus presence, recent
  activity. Per the verification checklist in
  `docs/demo-target-candidates.md`. If either fails, swap to the
  fallback (J2 / N2).
- [ ] **Clone J1 + N1 locally and bind-mount into `asp-api`.** Update
  `docker-compose.yml`. Document the bind-mount paths in the demo
  recording guide.
- [ ] **Dry-scan both, fork to add canonical injection patterns where
  needed.** J1 needs a corpus document if it doesn't have one; N1
  likely doesn't need a fork (the architecture already has the right
  shape). Fork is honest — call it out on camera.
- [ ] **Author #17 + #18.** Full `expected_nodes` + `synthetic_nodes`
  + `edges` blocks. Each edge gets a per-target rationale. The seed's
  `expected_nodes` pre-flight will catch any ID typo before write.
- [ ] **Run extract → verify → seed end-to-end against both targets.**
  Frontend at `/graph` must show non-zero attack paths for each.
- [ ] **Capture golden fixtures.** One JSON per target at
  `connectors/github/tests/fixtures/<target>.golden.json`, keyed by
  commit SHA. CI job re-runs the LLM scan against the same commit and
  diffs against the golden — that's the determinism proof.
- [ ] **Update the demo recording guide** with the bind-mount paths
  and stack-substitution narration.

**Decision point (end of week 3):** Are all three stacks producing
defensible attack paths *and* surviving golden-fixture re-runs? Yes
→ week 4. No → tune prompts and verification, slip week 4 by a day or
two.

### Week 4 — Adversarial testing + trust documentation

Goal: end the week with the false-positive rate on non-target repos
verified at zero, and a public-facing document explaining what's
deterministic, what's bounded, and what's deliberately out of scope.

- [ ] **Run the LLM scanner against ~10 random GitHub repos that are
  NOT RAG-with-tools apps.** Vue starter, basic Spring boot CRUD,
  plain Python CLI tool, etc. The scanner should produce *zero*
  `Tool`/`PromptTemplate`/`RAGIndex`/`MemoryStore` nodes. Any false
  positive is a launch blocker.
- [ ] **Tune prompts and verification to drive false positives to
  zero.** Each tuning iteration bumps `prompt_sha`, which is what
  the cache-key story is for — re-running over a commit picks up the
  new behavior cleanly.
- [ ] **Write `docs/llm-scanner.md`** — public-facing trust document.
  Covers: how grounding works, what's deterministic vs probabilistic,
  what the cache guarantees, what failure modes look like, what's
  deliberately NOT automated (security-semantic edges). Links from
  the launch post and the connector README.
- [ ] **Add `prompts/` editing rules to `CONTRIBUTING.md`.** Material
  prompt changes require an ADR. Whitespace/typo fixes do not.
  Either way the cache key bumps.
- [ ] **README capability-matrix audit.** I flagged this earlier —
  several rows (e.g. Cosign-signed images, adversarial self-red-team
  suite) have phase markers I haven't verified are accurate. Audit
  pass to align with reality.

**Decision point (end of week 4):** False positives at zero on the
random-repo sweep? **Yes** → ship Option C as the launch headline.
**No** → demote LLM scanner to a "preview" feature in the launch
post, ship the deterministic static + manifest layer as the headline,
and leave the LLM scanner for the next release. The fallback is real,
documented in the ADR, and not embarrassing — it's the deterministic
multi-stack manifest scanner, which is itself a meaningful upgrade
over Python-only.

### Week 5 — Polish + launch post update + recording

Goal: end the week with everything launch-ready. The recording is the
last thing — it should be the easiest part because the demo has been
exercised end-to-end across all three targets in week 3.

- [ ] **Update `docs/launch-post-draft.md`** with the multi-stack +
  LLM-scanner story. The paragraph in *"What it does today"* about
  the Python connector becomes a paragraph about the multi-stack
  scanner with grounded LLM extraction. The non-determinism caveat
  goes in explicitly per ADR-0005's recommendation: *"the scanner
  uses an LLM under deterministic grounding to extract ontology nodes
  from non-Python codebases. Re-runs against the same commit produce
  the same graph; the cache key includes the model and prompt hash so
  re-scoring requires an explicit version bump."*
- [ ] **Dry-run the demo end-to-end** against all three targets. Time
  it. If any scene runs over budget, decide what to cut.
- [ ] **Re-record the demo** against a non-Python target. Update
  `frontend-graph-view.png` if the screenshot drifted.
- [ ] **Launch checklist:** ADR-0005 status confirmed Accepted, all
  CI green, golden fixtures pass, README + connector README + demo
  recording guide all internally consistent, launch post draft
  reviewed by deciders.

### D-day — Launch

- [ ] Publish launch post.
- [ ] Tag `v0.2.0` (multi-stack + LLM scanner). Version bump captures
  the scope of what changed since v0.1.
- [ ] Cosign-sign container images for the release.
- [ ] Open the repo for issues / PRs.
- [ ] Announce in the venues planned per `for sponsors` section of
  the launch post.

## Post-launch — the existing roadmap, reordered by realism

The launch-post draft already lists the post-launch roadmap; this
section just clarifies the ordering and dependencies based on what
shipping Option C teaches us.

### Phase 1 remainder (the things still marked 🔨 in the README)

1. **Connector interface defined.** Once the LLM scanner ships, the
   "what does a connector look like" question is well-formed —
   manifest pass + LLM pass + writer is the shape. Codify the
   interface so AWS / Azure / GCP connectors can implement it cleanly.
2. **Redpanda event bus + async graph workers.** Moved forward from
   Phase 3 per architectural review. Unblocks the OTel ingestor.
3. **AWS connector** (Bedrock / IAM / S3). Highest-ROI next connector
   by audience size.
4. **OTel → Redpanda → graph workers.** The runtime evidence path that
   turns "we found this attack path statically" into "we observed it
   firing in production."
5. **Trace correlation: TraceSpan ↔ graph nodes.** Closes the loop on
   runtime observability.
6. **Graph schema migrations.** Needed once the ontology has its
   first non-trivial bump.

### Phase 2 — Agents + policy

The launch makes the tri-agent story credible, not yet shipped.
Order matters: Red first (it has the cleanest scope — propose attack
paths against the graph, no writes), then policy bundles, then Blue,
then Green. MCP server (the three named tools) lands alongside Red
because the other-team-agents-querying-our-graph use case is the
clearest external integration point.

### Phase 3 — Compliance + scale

OSCAL component definitions, Probabilistic Mitigation model
(ADR-0002 reserved), VEX generation, horizontal agent scale-out.
75% Agentic Top 10 adversarial coverage as the gate metric.

### Phase 4 — v1.0

JWT-based tenant binding, OIDC/SSO, 5+ community connectors,
three-cloud reference deployment, third-party threat-model review.
**100% OWASP LLM + Agentic Top 10 adversarial coverage** is a release
blocker. SaaS multi-tenancy stays out of scope per ADR-0004.

## Risks I'm watching

1. **LLM hallucinations on non-target repos.** The week-4 sweep is
   the gate. Mitigation is the ADR-0005 grounding contract, which
   I'm confident in; the unknown is how often the model invents
   plausible-but-wrong groundings that pass static checks and slip
   through verification. The fallback is documented and not
   embarrassing.
2. **Cost overrun.** `--max-llm-tokens` is the safety net. Each scan
   costs roughly 2× extraction (extract + verify), which is fine for
   demos and CI golden fixtures but a real budget for ongoing CI on
   PR-driven re-scans. Mitigation: cache hit rate should be high in
   normal use; only commit-bumping PRs miss the cache.
3. **J1 or N1 license/shape blocker on verification.** ~30-minute
   risk; fallback candidates are J2 / N2 and ready to go.
4. **Prompt-sha churn during week 4 tuning.** Each tuning iteration
   invalidates the cache for every target. Acceptable cost; the
   cache is a reproducibility tool, not a budget tool.
5. **Schedule slip cascading.** Week 5 is the buffer for exactly this
   reason — if any of weeks 2/3/4 slip by a day, week 5 absorbs it
   without moving the launch. If week 5 itself slips, the launch
   moves; better than shipping under-rehearsed.

## What I'm explicitly not doing pre-launch

- Vector-DB-aware RAG detection beyond what the manifest parser
  catches (Pinecone/Weaviate/Chroma deps emit a `RAGIndex` node from
  the manifest pass alone, which is enough for v0.2).
- Runtime evidence ingestion. The platform stays graph-from-static-
  scan for the launch.
- Multi-tenant scanning, scale, async workers. Single-repo,
  synchronous, local — same posture as the current Python scanner.
- LLM-authored security-semantic edges. ADR-0005 explicitly forbids
  this. Targets/<x>.yaml profiles stay hand-authored per target.
- More than three stacks. Python, Java, Node. Done. Go.
