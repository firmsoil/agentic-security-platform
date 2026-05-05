"""file_walk + batch_files tests — pure I/O, no LLM."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from connectors.github.src.llm.file_walk import (
    EXTENSIONS_BY_STACK,
    WalkedFile,
    batch_files,
    walk_repo,
)


def _make(repo: Path, rel: str, content: str = "x") -> Path:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# walk_repo
# ---------------------------------------------------------------------------


class TestWalkRepo:
    def test_returns_python_sources(self, tmp_path: Path):
        _make(tmp_path, "src/app.py", "def f(): pass\n")
        _make(tmp_path, "src/tools.py", "tool = {}\n")
        files = walk_repo(tmp_path, stack="python")
        rels = {f.relative_path for f in files}
        assert rels == {"src/app.py", "src/tools.py"}

    def test_skips_extensions_outside_stack(self, tmp_path: Path):
        _make(tmp_path, "src/app.py", "py")
        _make(tmp_path, "src/app.ts", "ts")
        py_files = {f.relative_path for f in walk_repo(tmp_path, stack="python")}
        ts_files = {f.relative_path for f in walk_repo(tmp_path, stack="node")}
        assert py_files == {"src/app.py"}
        assert ts_files == {"src/app.ts"}

    def test_skips_vendored_and_build_dirs(self, tmp_path: Path):
        _make(tmp_path, "src/keep.py", "keep")
        _make(tmp_path, "node_modules/pkg/index.js", "drop")
        _make(tmp_path, ".venv/lib/x.py", "drop")
        _make(tmp_path, "__pycache__/x.cpython-312.pyc", "drop")
        _make(tmp_path, "dist/build.py", "drop")
        _make(tmp_path, "target/classes/X.class", "drop")
        _make(tmp_path, ".next/cache/x.js", "drop")
        py = {f.relative_path for f in walk_repo(tmp_path, stack="python")}
        assert py == {"src/keep.py"}
        # Even though node_modules/pkg/index.js exists with the right
        # extension for the node stack, the skip-dir rule filters it.
        node = {f.relative_path for f in walk_repo(tmp_path, stack="node")}
        assert node == set()

    def test_skips_oversized_files(self, tmp_path: Path):
        _make(tmp_path, "src/small.py", "x" * 100)
        _make(tmp_path, "src/big.py", "x" * (300 * 1024))  # > 256 KiB
        files = {f.relative_path for f in walk_repo(tmp_path, stack="python")}
        assert files == {"src/small.py"}

    def test_returns_relative_paths_with_forward_slashes(self, tmp_path: Path):
        _make(tmp_path, "a/b/c.py", "x")
        files = walk_repo(tmp_path, stack="python")
        assert files[0].relative_path == "a/b/c.py"  # forward slashes always

    def test_sha_matches_content(self, tmp_path: Path):
        content = "hello\nworld\n"
        _make(tmp_path, "x.py", content)
        files = walk_repo(tmp_path, stack="python")
        assert files[0].sha256 == hashlib.sha256(content.encode()).hexdigest()

    def test_unknown_stack_raises(self, tmp_path: Path):
        with pytest.raises(ValueError, match="unknown stack"):
            walk_repo(tmp_path, stack="rust")

    def test_not_a_dir_raises(self, tmp_path: Path):
        f = tmp_path / "x.txt"
        f.write_text("x")
        with pytest.raises(NotADirectoryError):
            walk_repo(f, stack="python")

    def test_file_filter_narrows(self, tmp_path: Path):
        _make(tmp_path, "src/app.py", "x")
        _make(tmp_path, "tests/test_app.py", "x")
        files = walk_repo(
            tmp_path,
            stack="python",
            file_filter=lambda p: "tests" not in p.parts,
        )
        rels = {f.relative_path for f in files}
        assert rels == {"src/app.py"}

    def test_extensions_per_stack_distinct(self):
        assert ".py" in EXTENSIONS_BY_STACK["python"]
        assert ".java" in EXTENSIONS_BY_STACK["java"]
        assert ".ts" in EXTENSIONS_BY_STACK["node"]
        # Markdown is in all three (system prompts may live in .md).
        for stack in ("python", "java", "node"):
            assert ".md" in EXTENSIONS_BY_STACK[stack]


# ---------------------------------------------------------------------------
# batch_files
# ---------------------------------------------------------------------------


def _wf(rel: str, content: str = "x") -> WalkedFile:
    return WalkedFile(
        relative_path=rel,
        sha256="0" * 64,
        content=content,
        size_bytes=len(content),
    )


class TestBatchFiles:
    def test_empty_input_returns_empty(self):
        assert batch_files([]) == []

    def test_small_files_in_one_batch(self):
        files = [_wf(f"x{i}.py") for i in range(5)]
        batches = batch_files(files)
        assert len(batches) == 1
        assert len(batches[0]) == 5

    def test_splits_when_exceeds_char_ceiling(self):
        # Three files of 50KB each, ceiling 100KB → batches: [a, b], [c]
        a = _wf("a.py", "a" * 50_000)
        b = _wf("b.py", "b" * 50_000)
        c = _wf("c.py", "c" * 50_000)
        batches = batch_files([a, b, c], max_chars_per_batch=100_000)
        assert [len(batch) for batch in batches] == [2, 1]

    def test_oversized_single_file_gets_own_batch(self):
        # A file bigger than the ceiling still ends up in a batch on its
        # own — better one oversized call than skip the file.
        small = _wf("small.py", "x" * 1_000)
        huge = _wf("huge.py", "x" * 200_000)
        batches = batch_files([small, huge], max_chars_per_batch=100_000)
        assert len(batches) == 2
        assert batches[0] == [small]
        assert batches[1] == [huge]

    def test_zero_ceiling_raises(self):
        with pytest.raises(ValueError, match="must be positive"):
            batch_files([_wf("x.py")], max_chars_per_batch=0)

    def test_negative_ceiling_raises(self):
        with pytest.raises(ValueError, match="must be positive"):
            batch_files([_wf("x.py")], max_chars_per_batch=-1)
