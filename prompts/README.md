# prompts/

Prompts shipped under this directory are part of the Agentic Security
Platform's LLM scanner (Option C, week 2). They are licensed
**Apache-2.0**, the same as the rest of the repo. Forks may modify them.

## What these prompts do

The LLM scanner uses these prompts to extract ontology-typed nodes from
source files in non-Python target repositories — `Tool`,
`PromptTemplate`, `RAGIndex`, `MemoryStore`. Every emitted node carries a
**grounding block** (`file_path`, `line_start`, `line_end`,
`file_sha256`, `evidence`, `confidence`). A second LLM call verifies
each grounded claim against the cited code span; any node whose
verification rejects is dropped before write.

The structure is fixed by JSON Schema and enforced via Anthropic
tool-use or OpenAI Structured Outputs (see ADR-0005). The prompts here
guide the model toward correct extraction; they do not attempt to
constrain output shape — the adapter does that.

## Why prompts are part of the cache key

Scan results are cached by
`(repo_commit_sha, scanner_version, adapter, model_name, prompt_sha)`.
That last component is the SHA-256 of the relevant prompt file's text.
Re-scoring an existing scan therefore requires **either** a model bump
**or** a prompt change — both bump the cache key, both invalidate prior
results.

This is what makes the LLM scanner reproducible enough to put behind a
launch demo and a CI pipeline. Treat it like a database migration: any
non-trivial change should be reviewed.

## Editing rules

- **Whitespace and typo fixes** — fine, no ADR needed; will still bump
  the cache key, but that is what we want.
- **Material wording changes** — open an ADR following the
  `docs/adr/0005-…` template explaining the rationale and the expected
  effect on extraction quality.
- **Adding a new prompt for a new node type** — extend the ontology
  first (`packages/asp-core/src/asp_core/graph/ontology/v1/nodes.yaml`),
  open an ADR, then ship the prompt.

## Files (week 2 deliverables — currently stubs)

| File | Purpose |
|---|---|
| `extract_tools.md` | Identify `Tool` nodes from a code span. Per-stack variants live under subdirectories. |
| `extract_prompt_templates.md` | Identify `PromptTemplate` nodes (system prompts, instruction blocks). |
| `extract_rag_indices.md` | Identify `RAGIndex` nodes (vector DB clients, corpus directories, retrieval setup). |
| `extract_memory_stores.md` | Identify `MemoryStore` nodes (in-process state, Redis sessions, conversation buffers). |
| `verify_node.md` | Two-pass verification — confirms a previously extracted node really does live at the cited code span. |
