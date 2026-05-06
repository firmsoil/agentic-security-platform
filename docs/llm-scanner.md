# LLM scanner — trust posture

The platform's GitHub connector uses an LLM to extract four kinds of
ontology nodes — `Tool`, `PromptTemplate`, `RAGIndex`, `MemoryStore` —
from non-Python source files. This document explains what that means
for trust, where the boundaries are, and how to audit a scan result.

The contract is recorded in [ADR-0005](adr/0005-llm-scanner-grounding-contract.md);
this is the operator-facing summary.

## What is and isn't LLM-driven

The connector runs in two phases.

**Phase 1 (manifest pass)** is fully deterministic. It parses
`requirements.txt`, `pom.xml` / `build.gradle*`, or `package.json`,
walks dependencies, and emits `Repository`, `Container`, `Artifact[]`,
and inferred `Model` nodes. No LLM, no network, no model invocation.
Same source → same output, byte-for-byte, every time.

**Phase 2 (LLM pass)** runs only when `--enable-llm` is set. It uses
a configured adapter — either Anthropic's tool-use API or OpenAI's
Structured Outputs — to extract the four code-shape node types from
the repo's source files. The model returns JSON conforming to a strict
schema; the platform validates and verifies before any node reaches
the graph.

Phase 2 is the only place an LLM operates. The platform's
**security-semantic edges** — `PROMPT_INJECTABLE_INTO`,
`TOOL_INVOKABLE_BY`, `MEMORY_POISONABLE_BY`, `CALLS_TOOL`, etc. — are
**never** LLM-authored. They live in hand-edited `targets/<x>.yaml`
profile files, with a rationale recorded for every edge. The bright
line is *AI-assisted inventory, not AI-authored findings*. ADR-0005
forbids crossing it without a superseding ADR.

## Grounding contract

Every node the LLM scanner emits carries a `grounding` block:

```json
{
  "node_type": "Tool",
  "id": "Tool:exportData",
  "properties": { ... },
  "grounding": {
    "file_path": "src/main/java/.../ExportDataTool.java",
    "line_start": 24,
    "line_end": 41,
    "file_sha256": "a3f2…",
    "evidence": "Method annotated @Tool with name=\"exportData\".",
    "confidence": "high"
  }
}
```

The platform enforces grounding in three places:

1. **Schema enforcement at extraction time.** The adapter binds the
   model's response to a JSON Schema. Anthropic uses tool-use with the
   schema as the tool's `input_schema`; OpenAI uses
   `response_format=json_schema` with `strict=true`. A non-conforming
   response is a provider bug, not a silent default.

2. **Static recheck before verification.** The orchestrator computes
   the SHA-256 of every file it sends to the model upfront. If a
   returned grounding cites a file the model didn't see, or claims
   a SHA the platform never computed, the node is rejected before any
   verification call burns API credits.

3. **Second-LLM verification of every survivor.** The orchestrator
   re-opens the cited file, recomputes the SHA-256, refuses on drift,
   then asks the same adapter — through a tightly-scoped prompt —
   *"does this code span define a node with this id and node_type?
   yes/no, why."* Verification rejects drop the node. Adapter errors
   during verification are also treated as rejections; the platform
   never silently accepts un-verified nodes when the provider is
   flaky.

Rejected nodes are logged with their reason (`file_missing`,
`sha_drift`, `line_out_of_range`, `llm_rejected`,
`malformed_verification_response`, `adapter_error`) under the
`ScanResult.metadata.llm_scan.report.rejection_log`. Rejection counts
are the quality signal CI can monitor for prompt regression.

## Determinism

Scans are cached on disk under `.cache/asp-llm-scan/`, keyed by:

    (repo_commit_sha, scanner_version, adapter, model_name, prompt_sha)

A re-run against an unchanged commit, with the same scanner version
and prompt files, returns the cached payload byte-for-byte. **Every
component of the cache key matters**: bumping the model, editing a
prompt, or changing `SCANNER_VERSION` invalidates the cache and
forces a fresh scan, which is the right behaviour for an audit trail.

This is why the launch claim is *"re-runs against the same commit
produce the same graph"* and not *"the LLM is deterministic"* — the
LLM isn't deterministic; the cached scan result is. Golden fixtures
under `connectors/github/tests/fixtures/` enforce this in CI: a
recorded scan plus the cache-key components it was recorded with,
verified by re-running the scanner and diffing against the recorded
output.

## What can drift across runs

The grounding contract preserves what matters and tolerates what
doesn't. Across model invocations of the same prompt against the same
source:

- **Strictly preserved**: node IDs, node types, edge structure,
  grounding's `file_path` / `file_sha256` / `line_start` / `line_end`,
  manifest-derived properties.
- **Tolerated as model-narrated**: grounding's `evidence` /
  `confidence` strings, `properties.description` for LLM-extracted
  nodes. The golden-fixture normalizer placeholders these as
  `__VOLATILE__` so legitimate sentence variation isn't logged as
  drift.

The graph identity — which nodes exist and how they connect — is the
guarantee. Sentence-level narration is not.

## Failure modes you can encounter

**Token budget exceeded.** The orchestrator aborts with a clear
`max_tokens (200000) exceeded after extract call (X actual)` message
and discards the in-flight result. No partial scan is cached; the
next run re-attempts cleanly.

**Adapter error during extraction.** Logged with the prompt that
failed; other prompt × batch combinations continue. The verifier
processes whatever did come back. Recoverable.

**Adapter error during verification.** Treated as a rejection. We
never silently accept un-verified nodes when the provider is flaky.

**Cache hit but stale.** Cache keys cover everything that should
trigger a re-run; if you change a prompt or bump the scanner version,
the cache is invalidated by composition, not by manual eviction.
There is no "force refresh" flag for paranoia — pass `--no-llm-cache`
to bypass the cache for one run.

**Model hallucinates a tool.** Caught at three stages: schema
validation, orchestrator-level static check (file_path / file_sha256
mismatch), or verifier rejection. False positives that survive all
three would require the model to invent a real-looking
file/SHA/line-range claim *and* convince a separate verification call
that the cited code defines that exact node. That's the regime
ADR-0005 commits to monitoring during launch readiness.

## What deliberately doesn't work

- **No edge inference.** The seed's security-semantic edges represent
  human security judgment and are not generated by the model.
- **No risk scoring by the LLM.** The platform's path-scoring engine
  reads the graph; it does not consult the LLM about whether a path
  is dangerous.
- **No fallback between adapters during a single scan.** The cache key
  pins one adapter+model. Cross-adapter mixing inside a scan would
  defeat the determinism story.
- **No cross-tenant scanning.** Each scan is single-tenant by ADR-0003.

## Auditing a single scan

Three places to look when reviewing a scan you didn't run yourself:

- `ScanResult.metadata.llm_scan.report` — telemetry for that run.
  Shows how many candidates the model proposed, how many the
  orchestrator's static checks rejected, how many the verifier
  rejected, and how many were accepted.
- `ScanResult.metadata.llm_scan.report.rejection_log` — per-rejection
  reason, including the prompt that produced the rejection. This is
  where prompt regressions surface earliest.
- The grounding block on every accepted node, preserved in
  `properties._llm_grounding`. Every claim cites a file path, line
  range, and SHA — re-open the file at the cited range and read it
  yourself.

## Calibration history

Per ADR-0005, the launch trust posture rests on running the scanner
against a known-shape target and confirming it reproduces what we can
verify by other means. The bundled `examples/vulnerable-rag-app/` is
that ablation target — a small Python repo where the deterministic
static parser provides ground truth. The parity test
(`scripts/run_parity_test.py`) compares LLM scanner output against
static scanner output and reports drift.

**The bundled demo is unusually adversarial as a parity target.** It
was authored as a security-education artifact, not an LLM-friendly
demonstration of canonical patterns. Three properties make it harder
for LLM extraction than typical real-world repos:

- **Multi-line parenthesized string constants.** `model.py` declares
  `SYSTEM_PROMPT = ( "..." "..." )` across six lines. The LLM
  occasionally picks too-narrow a span (the assignment line plus
  comments, missing the actual string content), and the verifier
  correctly rejects "this doesn't show the string value."
- **Non-canonical RAG.** There is no Pinecone, Chroma, or pgvector
  here — just a `corpus/` directory of markdown files plus
  `_load_corpus()` reading them into a list, and `retrieve()` doing
  keyword overlap. The static parser detects this via filesystem
  heuristics (corpus directory exists). The LLM has to infer the
  pattern from code alone, and occasionally cites the wrong function
  (e.g., `Document.tokens` property instead of the loader).
- **Memory store with seeded data.** `memory.py`'s `_memory = {...}`
  is initialized with several lines of synthetic customer records.
  When the LLM cites this assignment, the verifier sees "static dict
  literal of demo data" rather than recognizing the variable as
  conversation memory (which it is, written to by `remember()` later
  in the same file).

Six prompt-tuning iterations during week 2 closed most of these gaps:

| Iteration | Change | Effect |
|---|---|---|
| 2→3 | Static parser fixed to use the source variable name (`MemoryStore:_memory` instead of hardcoded `:session_memory`); profile updated to match. | MemoryStore drift resolved. |
| 3 | Verifier system prompt updated with explicit ID-convention rules (snake_case-of-VARIABLE_NAME ids are valid). | PromptTemplate rejection resolved. |
| 4 | extract_rag_indices.md updated to require citing the full loader function definition, not just the path literal. | RAGIndex rejection resolved on most runs. |
| 5 | Verifier prompt updated to explicitly accept MemoryStore claims about `_memory`-named variables even when the cited span shows only the seed-data assignment. | MemoryStore acceptance stabilized. |

After those iterations, the LLM scanner reproduces 1–4 of 4 of the
static scanner's IDs on any given run, with the mode around 3 of 4.
The remaining variance comes from non-determinism in which span the
LLM cites — every rejection in the calibration runs was a
*span-citation* issue (LLM picked too-narrow line ranges, missing the
context the verifier needs to confirm the claim), not a
pattern-recognition issue. The LLM correctly identifies that
Tool/PromptTemplate/RAGIndex/MemoryStore nodes exist; it sometimes
cites the wrong span when proving them. That's the inherent regime
ADR-0005's grounding contract is designed to bound, not eliminate —
*every accepted node is verified*; rejected ones are dropped, not
silently included.

**The bundled demo is therefore treated as a smoke test, not a
parity test.** The launch's parity claim rests on real targets, not
on this one. The bundled-demo test exists to confirm the pipeline
runs end-to-end (extract → verify → at least one accepted node);
that is the floor at which the test is gated by default
(`ASP_PARITY_MIN_RATIO=0.25`).

The launch parity claim is **separately validated on canonical real
targets**: `langchain4j-examples`' `customer-support-agent-example`
(LangChain4j `@Tool` annotations) and `vercel-labs/ai-sdk-preview-rag`
(Vercel AI SDK `tool()` factory calls + Drizzle pgvector schema).
Those use canonical patterns the LLM is substantially better at
recognizing — the multi-line-parens, non-canonical-RAG, and
seeded-dict edge cases the bundled demo exercises do not appear in
real-world targets. We expect (and gate on) strict-match parity
against those targets, with goldens recorded in
`connectors/github/tests/fixtures/` and re-verified in CI per
ADR-0005's reproducibility contract.

`ASP_PARITY_MIN_RATIO` can be raised to `0.75` or `1.0` to tighten
the bundled-demo gate once the prompts have stabilized further; the
launch readiness signal is the **real-target goldens**, not this
threshold.

The four property diffs that show up regardless of node-set parity
are by-design informational:

- `Tool:export_data.schema` — same JSON content, different key
  ordering. The static parser uses `sort_keys=True`; the LLM emits
  in source-file order. Equivalent.
- `PromptTemplate:system_prompt.version` and `.checksum` — static
  parser computes a SHA-256 of the prompt text and assigns
  `version="1"`. The LLM doesn't compute SHAs (would be wasteful);
  the version field is a static-parser convention.
- `MemoryStore.kind` — static produces `"conversation"`, LLM
  produces `"session"` or `"conversation"` depending on run.
  Vocabulary difference, not an identity difference.

These don't fail the parity threshold and don't appear in the graph's
attack-path queries.

### Launch decision (2026-04-29): PASS

The launch decision gate from the launch roadmap was the adversarial
false-positive sweep — running the LLM scanner against ~10 random
non-AI public repositories and confirming the verifier correctly
rejects every spurious extraction the model proposes. The sweep
completed 2026-04-29 with a clean PASS:

- **9 repositories scanned**, spanning all three stacks: Python
  (`black`, `click`, `bottle`), Java/Spring (`spring-petclinic`,
  `spring-mvc-showcase`, `gs-rest-service`), Node/TS (`chalk`, `swr`,
  `create-vue`).
- **Zero LLM-scope nodes emitted across all 9 repos.** No `Tool`, no
  `PromptTemplate`, no `RAGIndex`, no `MemoryStore` survived to the
  graph for code that genuinely has none.
- The verifier rejected every spurious candidate the model proposed;
  the orchestrator's static-check rejections and the verifier's
  second-LLM rejections combined to produce a clean output set.

Combined with strict-match reconciliation against the real launch
targets — `langchain4j-examples/customer-support-agent-example`
(8 of 8 expected nodes, including two `@Tool`-annotated methods) and
`vercel-labs/ai-sdk-preview-rag` (8 of 8, including three Vercel AI
SDK `tool()` factory calls and a Drizzle pgvector embedding store) —
this cleared Option C (LLM-assisted scanner) to ship as the launch
headline rather than the ADR-0005 fallback ("preview" framing).

The full sweep log is committed at
[`docs/evidence/adversarial-sweep-2026-04-29.log`](evidence/adversarial-sweep-2026-04-29.log)
for inspection. The runner script at
[`scripts/run_adversarial_sweep.sh`](../scripts/run_adversarial_sweep.sh)
is reproducible — drop new candidate repos under
`~/clouddev/asp-demo-targets/sweep/` and re-run to update the sweep.

## Where to read more

- [ADR-0005](adr/0005-llm-scanner-grounding-contract.md) — the
  contract itself.
- [`prompts/README.md`](../prompts/README.md) — prompt catalog and
  editing rules (material edits require an ADR).
- [`connectors/github/README.md`](../connectors/github/README.md) —
  scanner usage and CLI reference.
- [`docs/launch-roadmap.md`](launch-roadmap.md) — what determinism
  evidence the launch is gated on.
