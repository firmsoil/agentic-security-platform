"""LLM-assisted scanner — produces grounded ontology nodes from non-Python repos.

Implements the contract from ADR-0005:
- Two-pass extraction (extract → verify), both through the same adapter.
- Strict JSON Schema enforced via Anthropic tool-use or OpenAI Structured
  Outputs.
- Cache keyed by (repo_commit_sha, scanner_version, adapter, model_name,
  prompt_sha) for reproducibility.

The scanner is a *companion* to the per-stack manifest scanners, not a
replacement: manifest parsing produces ``Repository``, ``Container``,
``Artifact``, ``Model`` deterministically; the LLM scanner adds the
grounded ``Tool`` / ``PromptTemplate`` / ``RAGIndex`` / ``MemoryStore``
nodes that don't fit a pure-AST pass.
"""

# Scanner version is part of the cache key. Bump when the orchestration,
# verification, or schema change in a way that invalidates prior results.
# Bumping requires an ADR for material changes (see prompts/README.md).
SCANNER_VERSION = "0.1.4"

__all__ = ["SCANNER_VERSION"]
