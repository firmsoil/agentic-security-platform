"""Filesystem cache for LLM scan results.

Per ADR-0005, scans are cached by

    (repo_commit_sha, scanner_version, adapter, model_name, prompt_sha)

— so re-running an LLM scan against the same commit, same adapter,
same model, and same prompts returns the same graph. Bumping any of
those bumps the cache key and forces a re-scan.

The cache is stored as one JSON file per key under
``<repo>/.cache/asp-llm-scan/``. Hits are pure file reads. Misses run
the scanner and write the result. Concurrent writers are not supported
— callers should serialize scans against the same key (the orchestrator
does this).

The repo_commit_sha is computed from ``git rev-parse HEAD`` if the path
is a git working tree; otherwise we fall back to a deterministic hash
of every file's content under the repo. The fallback is slower but lets
the cache work for unpacked tarballs and on-the-fly clones (e.g. CI
fixtures stored without ``.git``).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_CACHE_DIRNAME = ".cache/asp-llm-scan"
_CACHE_FORMAT_VERSION = 1


@dataclass(frozen=True)
class CacheKey:
    """The five components that uniquely identify a cached scan."""

    repo_commit_sha: str
    scanner_version: str
    adapter: str
    model_name: str
    prompt_sha: str

    def fingerprint(self) -> str:
        """Stable 64-char hex digest of all five components.

        We sort and concatenate explicitly rather than hashing a dict so
        the digest stays stable across Python versions and dict iteration
        orders.
        """
        parts = [
            f"commit={self.repo_commit_sha}",
            f"scanner={self.scanner_version}",
            f"adapter={self.adapter}",
            f"model={self.model_name}",
            f"prompts={self.prompt_sha}",
        ]
        joined = "\n".join(parts).encode()
        return hashlib.sha256(joined).hexdigest()

    def cache_path(self, repo_path: Path) -> Path:
        """Filesystem path the cached scan lives at, under the repo."""
        return (
            repo_path / _CACHE_DIRNAME / f"{self.fingerprint()}.json"
        )


# ---------------------------------------------------------------------------
# Repo commit identification
# ---------------------------------------------------------------------------


def repo_commit_sha(repo_path: Path) -> str:
    """Return a stable identifier for the repo's current state.

    Tries ``git rev-parse HEAD`` first; falls back to hashing every
    tracked file's content if that fails.
    """
    git_dir = repo_path / ".git"
    if git_dir.exists():
        try:
            result = subprocess.run(
                ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            sha = result.stdout.strip()
            if sha and all(c in "0123456789abcdef" for c in sha):
                return sha
        except (subprocess.SubprocessError, OSError) as exc:
            log.warning("git rev-parse failed for %s: %s", repo_path, exc)

    return _content_hash(repo_path)


def _content_hash(repo_path: Path) -> str:
    """Fallback identifier — SHA-256 of every regular file's content.

    Skips ``.git`` and ``.cache`` so cache writes don't invalidate the
    cache key. Sorts paths for determinism.
    """
    digest = hashlib.sha256()
    skip_dirs = {".git", ".cache", "node_modules", ".venv", "__pycache__"}
    paths: list[Path] = []
    for root, dirs, files in os.walk(repo_path):
        # Mutate dirs in-place so os.walk doesn't descend into skipped trees.
        dirs[:] = sorted(d for d in dirs if d not in skip_dirs)
        for name in sorted(files):
            paths.append(Path(root) / name)
    for path in paths:
        rel = path.relative_to(repo_path).as_posix()
        digest.update(b"PATH:")
        digest.update(rel.encode())
        digest.update(b"\n")
        try:
            with open(path, "rb") as fh:
                while chunk := fh.read(65536):
                    digest.update(chunk)
        except OSError:
            digest.update(b"<unreadable>")
        digest.update(b"\n")
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Prompt hashing
# ---------------------------------------------------------------------------


def prompt_sha(prompt_paths: list[Path]) -> str:
    """SHA-256 over the concatenated content of every prompt file.

    Sort the inputs for determinism — callers shouldn't have to think
    about ordering. Each file is prefixed with its path so reordering the
    files-on-disk would change the digest even if total bytes match.
    """
    digest = hashlib.sha256()
    for path in sorted(prompt_paths, key=lambda p: p.as_posix()):
        digest.update(b"PROMPT:")
        digest.update(path.name.encode())
        digest.update(b"\n")
        digest.update(path.read_bytes())
        digest.update(b"\n")
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Read / write
# ---------------------------------------------------------------------------


def cache_get(repo_path: Path, key: CacheKey) -> dict[str, Any] | None:
    """Return the cached payload for ``key``, or None on miss."""
    path = key.cache_path(repo_path)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Cache read failed at %s: %s; treating as miss", path, exc)
        return None
    if not isinstance(data, dict):
        log.warning("Cache file %s contained non-dict; treating as miss", path)
        return None
    if data.get("cache_format_version") != _CACHE_FORMAT_VERSION:
        log.warning(
            "Cache file %s has format version %r; expected %r — treating as miss",
            path, data.get("cache_format_version"), _CACHE_FORMAT_VERSION,
        )
        return None
    if data.get("key_fingerprint") != key.fingerprint():
        # Defensive — the filename should already encode the key, but the
        # body carries it too so manual cache surgery is auditable.
        log.warning(
            "Cache file %s has fingerprint mismatch; treating as miss", path,
        )
        return None
    return data.get("payload")


def cache_put(
    repo_path: Path,
    key: CacheKey,
    payload: dict[str, Any],
) -> Path:
    """Write ``payload`` to the cache for ``key``. Returns the file path."""
    path = key.cache_path(repo_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "cache_format_version": _CACHE_FORMAT_VERSION,
        "key_fingerprint": key.fingerprint(),
        "key": dataclasses.asdict(key),
        "payload": payload,
    }
    # Write atomically — partial writes during a crash would silently
    # poison the cache.
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(body, indent=2, sort_keys=True))
    tmp.replace(path)
    return path
