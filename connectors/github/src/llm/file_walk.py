"""Repo file enumeration + SHA precompute for the LLM scanner.

Walks the repo, filters out vendored/build directories, applies a size
ceiling, and returns each candidate file with its SHA-256 already
computed. The orchestrator passes the SHA to the extractor and verifier
so the grounding contract can be enforced without re-reading files.
"""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


# ---- Configuration -------------------------------------------------------

# Directories never recursed into. These are the usual suspects for
# vendored or built artifacts that would balloon scan cost without
# producing meaningful nodes.
_SKIP_DIRS: frozenset[str] = frozenset({
    ".git",
    ".cache",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    "target",      # Maven / Cargo
    ".gradle",
    ".idea",
    ".vscode",
    ".next",       # Next.js build output
    "out",
    "coverage",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
})

# Source-file extensions per stack. The orchestrator passes a file to the
# extractor only if its extension is in this set for the relevant stack.
# Markdown and plain text are included because system prompts often live
# in `.md` / `.txt` files.
EXTENSIONS_BY_STACK: dict[str, frozenset[str]] = {
    "python": frozenset({".py", ".md", ".txt", ".yaml", ".yml"}),
    "java": frozenset({
        ".java", ".kt", ".md", ".txt", ".properties",
        ".yaml", ".yml",
    }),
    "node": frozenset({
        ".ts", ".tsx", ".js", ".jsx", ".mts", ".cts",
        ".md", ".txt", ".yaml", ".yml",
    }),
}

# Hard ceiling on individual file size. Bigger files almost certainly
# aren't hand-written source we want grounded; they're generated, vendored,
# or data. 256 KiB is generous.
_MAX_FILE_BYTES = 256 * 1024


# ---- Result type ---------------------------------------------------------


@dataclass(frozen=True)
class WalkedFile:
    """One file the orchestrator may send to the extractor."""

    relative_path: str  # Forward-slash, matches what grounding.file_path uses.
    sha256: str
    content: str
    size_bytes: int


# ---- Walk ----------------------------------------------------------------


def walk_repo(
    repo_path: Path,
    *,
    stack: str,
    file_filter: Callable[[Path], bool] | None = None,
) -> list[WalkedFile]:
    """Return source files from ``repo_path`` for the given ``stack``.

    ``file_filter`` lets callers narrow further (e.g. only files under a
    src/ subdirectory). It receives an absolute path and returns True to
    keep, False to skip.
    """
    if not repo_path.is_dir():
        msg = f"walk_repo: not a directory: {repo_path}"
        raise NotADirectoryError(msg)

    extensions = EXTENSIONS_BY_STACK.get(stack)
    if extensions is None:
        msg = (
            f"walk_repo: unknown stack {stack!r}; "
            f"expected one of {sorted(EXTENSIONS_BY_STACK)}"
        )
        raise ValueError(msg)

    walked: list[WalkedFile] = []
    for root, dirs, files in os.walk(repo_path):
        # Mutate dirs in-place so os.walk doesn't descend into skipped trees.
        dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS)

        for name in sorted(files):
            full = Path(root) / name
            if full.suffix.lower() not in extensions:
                continue
            if file_filter is not None and not file_filter(full):
                continue

            try:
                size = full.stat().st_size
            except OSError as exc:
                log.warning("walk_repo: stat failed for %s: %s", full, exc)
                continue
            if size > _MAX_FILE_BYTES:
                log.info(
                    "walk_repo: skipping oversized file %s (%d bytes)",
                    full, size,
                )
                continue

            try:
                content = full.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                log.warning("walk_repo: read failed for %s: %s", full, exc)
                continue

            sha = hashlib.sha256(
                content.encode("utf-8", errors="replace"),
            ).hexdigest()
            relative = full.relative_to(repo_path).as_posix()
            walked.append(WalkedFile(
                relative_path=relative,
                sha256=sha,
                content=content,
                size_bytes=size,
            ))

    return walked


# ---- Batching ------------------------------------------------------------


def batch_files(
    files: list[WalkedFile],
    *,
    max_chars_per_batch: int = 120_000,
) -> list[list[WalkedFile]]:
    """Group files into context-sized batches for the extractor.

    The default ceiling (~120 KiB of file content per batch) leaves headroom
    for the system prompt + user-prompt scaffolding inside a 128k-token
    context. Bigger contexts could push this higher, but the conservative
    default keeps cost predictable and avoids partial-truncation surprises.
    """
    if max_chars_per_batch <= 0:
        msg = f"max_chars_per_batch must be positive; got {max_chars_per_batch}"
        raise ValueError(msg)

    batches: list[list[WalkedFile]] = []
    current: list[WalkedFile] = []
    current_chars = 0

    for f in files:
        # A single file bigger than the batch ceiling still gets its own
        # batch — better one oversized call than skip the file silently.
        # The walker's _MAX_FILE_BYTES already caps at 256 KiB.
        if current and current_chars + len(f.content) > max_chars_per_batch:
            batches.append(current)
            current = []
            current_chars = 0
        current.append(f)
        current_chars += len(f.content)

    if current:
        batches.append(current)

    return batches
