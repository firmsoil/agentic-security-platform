"""Prompt loading + extraction-prompt composition.

The four extraction prompts live under ``prompts/`` and are part of the
LLM scanner's cache key (``prompt_sha`` in ``cache.CacheKey``). This
module reads them and composes the user-prompt body that includes the
walked files plus their precomputed SHAs.

By keeping the prompt-composition code here and the prompt *content* in
``prompts/<extract_*>.md``, prompt iterations don't require Python edits
— they bump ``prompt_sha`` on the next scan and re-trigger the LLM pass
through the cache.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from connectors.github.src.llm.file_walk import WalkedFile


# ---------------------------------------------------------------------------
# Prompt catalog
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExtractionPrompt:
    """One extraction prompt — one node type the LLM scanner emits."""

    node_type: str       # "Tool" / "PromptTemplate" / "RAGIndex" / "MemoryStore"
    filename: str        # File under prompts/ (relative to prompts_dir)
    target_node_type: str  # ID prefix the model must use for emitted nodes


# All four extraction prompts the LLM scanner uses. Order matches the
# typical cost: tools tend to dominate, prompt templates next, then RAG
# indices, then memory stores.
EXTRACTION_PROMPTS: tuple[ExtractionPrompt, ...] = (
    ExtractionPrompt("Tool", "extract_tools.md", "Tool"),
    ExtractionPrompt(
        "PromptTemplate", "extract_prompt_templates.md", "PromptTemplate",
    ),
    ExtractionPrompt("RAGIndex", "extract_rag_indices.md", "RAGIndex"),
    ExtractionPrompt("MemoryStore", "extract_memory_stores.md", "MemoryStore"),
)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_prompt(prompts_dir: Path, filename: str) -> str:
    """Read a prompt file. Raises FileNotFoundError if missing."""
    path = prompts_dir / filename
    if not path.is_file():
        msg = (
            f"Prompt file missing: {path}. The LLM scanner expects every "
            f"file in EXTRACTION_PROMPTS to exist under prompts/."
        )
        raise FileNotFoundError(msg)
    return path.read_text(encoding="utf-8")


def all_extraction_prompt_paths(prompts_dir: Path) -> list[Path]:
    """All prompt file paths, used to compute ``prompt_sha`` for the cache key."""
    return [prompts_dir / p.filename for p in EXTRACTION_PROMPTS]


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


_FILES_HEADER = (
    "## Files in this batch\n\n"
    "Each file is delimited with `--- BEGIN FILE: <path> SHA: <sha> ---` "
    "and `--- END FILE ---`. When you ground a node in a file, the "
    "`grounding.file_path` MUST exactly match the path on the BEGIN line, "
    "and `grounding.file_sha256` MUST be the SHA on the BEGIN line "
    "verbatim.\n\n"
)


def compose_extraction_user_prompt(
    *,
    prompt_body: str,
    files: Iterable[WalkedFile],
) -> str:
    """Build the user-prompt body for one extraction call.

    The composition is deliberately mechanical so the model sees a
    predictable structure: prompt body first, then a clearly delimited
    file dump. The delimiters double as anti-injection guards — text
    inside file content can't break the structure because the closing
    delimiter is on its own line.
    """
    parts = [prompt_body.rstrip(), "\n\n", _FILES_HEADER]
    for f in files:
        parts.append(
            f"--- BEGIN FILE: {f.relative_path} SHA: {f.sha256} ---\n"
        )
        parts.append(f.content)
        if not f.content.endswith("\n"):
            parts.append("\n")
        parts.append("--- END FILE ---\n\n")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Sanity check on returned grounding
# ---------------------------------------------------------------------------


def known_file_index(files: Iterable[WalkedFile]) -> dict[str, str]:
    """Map relative_path -> sha256 for the files in a batch.

    Used by the orchestrator to reject candidate nodes whose grounding
    cites a file we never sent or whose SHA disagrees with what we
    computed at walk time.
    """
    return {f.relative_path: f.sha256 for f in files}
