# ADR 0005 — LLM scanner grounding contract

- **Status**: Accepted
- **Date**: 2026-04-26
- **Deciders**: Founding maintainers
- **Consulted**: Launch postponement decision (4–6 week slip from 2026-04-26 to ship Option C MVP), prior conversations on Options A (manual profiles only), B (per-stack static parsers), and C (LLM-assisted multi-stack scanner)
- **Superseded by**: —

## Context

The platform's GitHub connector ships as a Python-only static scanner. To support the launch claim "graph-native security for AI-native applications" across the ecosystems where agentic apps actually live (Python, Java/Spring, Node/TypeScript), we need to extract ontology nodes — `Tool`, `PromptTemplate`, `RAGIndex`, `MemoryStore` — from source files we have no AST for and no patience to write three full ASTs for before launch.

Three options were considered. **Option A** (hand-author `targets/<x>.yaml` with all nodes synthetic) makes the launch demo dishonest — the audience figures out within thirty seconds that no scanning is happening. **Option B** (one full static scanner per ecosystem) is engineering-heavy enough that the launch ships with one ecosystem, breaking the cross-stack claim. **Option C** (LLM-assisted extraction with grounding) supports the cross-stack claim with a smaller engineering investment, **provided** the LLM is constrained tightly enough that the output is reproducible and trustworthy.

This ADR records the contract that "tightly enough" means.

## Decision

Every node emitted by the LLM scanner carries a **grounding block**:

```json
{
  "node_type": "Tool",
  "id": "Tool:exportData",
  "properties": {"name": "exportData", "scope": "filesystem_write"},
  "grounding": {
    "file_path": "src/main/java/com/example/tools/ExportDataTool.java",
    "line_start": 24,
    "line_end": 41,
    "file_sha256": "a3f2…",
    "evidence": "Method annotated @Tool with name=\"exportData\"; schema declares filesystem_write scope.",
    "confidence": "high"
  }
}
```

A two-pass extraction enforces the contract. **Pass 1** (extraction) walks the repo, batches files into the LLM's context, and asks for grounded ontology nodes. **Pass 2** (verification) re-opens each emitted node's `file_path`, recomputes the SHA-256, refuses on drift, then asks the same model — through a deliberately narrow prompt — *"does this code span define a node with this id and node\_type? yes/no, why."* Verification rejects are dropped before any graph write. Rejection counts are logged loudly; they are the quality signal that gates launch readiness.

Both passes go through a **single-provider adapter chosen at config time, never per-request**. Two adapters exist behind a `StructuredExtractor` Protocol:

- `AnthropicAdapter` — uses Anthropic tool-use to bind the response to a JSON Schema.
- `OpenAIAdapter` — uses OpenAI Structured Outputs (`response_format=json_schema`) for the same effect.

There is one schema, shared between adapters and applied to both passes. CI exercises both adapters at parity so the OSS claim "use either provider" stays honest.

The cache key for any scan is:

    (repo_commit_sha, scanner_version, adapter, model_name, prompt_sha)

`prompt_sha` is the SHA-256 of the relevant prompt file under `prompts/`. Re-running a scan against the same commit — same model, same prompt — returns the same graph.

## Rationale

**Why grounding at all.** Without it, the LLM scanner is a freeform generator and the platform inherits every objection that AI-security tools deserve. With grounding plus verification, the LLM is acting as a *classifier* over real code spans the verification step re-checks. That is a regime current models handle well enough to ship.

**Why a second LLM call for verification rather than a regex.** Java annotations and TS template literals defeat regex verification on day one. A second LLM call narrowly prompted ("does this code span define this exact node? yes/no") is a far more constrained problem than the original extraction, and the false-positive rate drops accordingly. The 2× spend per scan is acceptable because scans are cached and the launch budget already absorbs it.

**Why structured outputs from both major providers, not a single one.** The launch is open-source. Tying the scanner to one provider makes the OSS posture worse and gives reviewers a free attack on the project's neutrality. Two adapters behind one Protocol costs roughly an extra week of work and resolves the objection cleanly.

**Why prompts in-repo, Apache-2.0.** Consistent with the OSS thesis. Good prompts in this domain are not a moat — they are the kind of artifact that benefits from open improvement. Pinning them to the cache key turns prompt edits into intentional version bumps rather than silent quality regressions.

**Why we are explicitly NOT having the LLM author security-semantic edges.** The seed's edges (`PROMPT_INJECTABLE_INTO`, `TOOL_INVOKABLE_BY`, `MEMORY_POISONABLE_BY`, `CALLS_TOOL`) represent human security judgment. Letting an LLM write them would collapse "AI-assisted inventory" (which is defensible) into "AI-authored security findings" (which is not). The seed continues to require a per-target `targets/<x>.yaml` profile with a rationale per edge.

## Consequences

- **Reproducibility.** Same `(commit, model, prompt)` tuple → same graph. CI golden fixtures keyed by this tuple catch drift between releases.
- **Cost.** Each fresh scan hits the API twice (extraction + verification). With caching, day-to-day cost is dominated by PR-driven re-scans against new commits. A `--max-llm-tokens` flag will abort on excess.
- **Trust posture.** The launch post must be explicit about the contract — non-determinism is bounded, grounding is verified, no findings are AI-authored. Hiding any of that would invite the strongest possible critique from a security audience.
- **Bright line for future work.** Future contributors looking to extend automation should re-read this ADR. Any proposal to have the LLM emit edges, score paths, or generate findings without grounding requires a superseding ADR.

## Alternatives reconsidered

**Option A (hand-authored profiles only).** Rejected. Demo is dishonest and the OSS story is weaker.

**Option B (full per-stack static scanners).** Deferred. Worth doing post-launch for the ecosystems that prove most valuable. The Option B directory layout (`stacks/<lang>/`) is already in place from this work, so future scanners drop into the existing dispatcher without further restructuring.

**Single-provider adapter.** Rejected per "Why structured outputs from both major providers" above.

**Skip verification to halve LLM spend.** Rejected. Verification is the load-bearing piece of the trust story; cutting it would invalidate every other guarantee in this ADR.

## References

- `prompts/README.md` — prompt catalog and editing rules.
- `connectors/github/src/types.py` — `ScanResult` shape (stack-agnostic; LLM scanner output conforms).
- `targets/vulnerable-rag-app.yaml` — example profile demonstrating the per-target judgment layer that the seed still requires.
- `docs/launch-post-draft.md` — must be updated with the grounding-contract paragraph before launch.
