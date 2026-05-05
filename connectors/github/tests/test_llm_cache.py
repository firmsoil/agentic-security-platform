"""Cache tests — no API calls, no LLM, deterministic."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from connectors.github.src.llm.cache import (
    CacheKey,
    cache_get,
    cache_put,
    prompt_sha,
    repo_commit_sha,
)


def _make_key(**overrides):
    base = {
        "repo_commit_sha": "a" * 40,
        "scanner_version": "0.1.0",
        "adapter": "anthropic",
        "model_name": "claude-sonnet-4-5",
        "prompt_sha": "b" * 64,
    }
    base.update(overrides)
    return CacheKey(**base)


# ---------------------------------------------------------------------------
# Key composition
# ---------------------------------------------------------------------------


class TestCacheKeyFingerprint:
    def test_same_inputs_same_fingerprint(self):
        k1 = _make_key()
        k2 = _make_key()
        assert k1.fingerprint() == k2.fingerprint()

    def test_fingerprint_is_64_hex(self):
        fp = _make_key().fingerprint()
        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)

    @pytest.mark.parametrize("override", [
        {"repo_commit_sha": "b" * 40},
        {"scanner_version": "0.2.0"},
        {"adapter": "openai"},
        {"model_name": "claude-opus-4"},
        {"prompt_sha": "c" * 64},
    ])
    def test_each_component_changes_fingerprint(self, override):
        # ADR-0005: every component is part of the cache key. Bumping any
        # one of them must change the fingerprint, otherwise we have a
        # silent cache-poisoning hazard.
        baseline = _make_key().fingerprint()
        changed = _make_key(**override).fingerprint()
        assert baseline != changed


# ---------------------------------------------------------------------------
# Read / write round-trip
# ---------------------------------------------------------------------------


class TestCacheGetPut:
    def test_miss_returns_none(self, tmp_path: Path):
        assert cache_get(tmp_path, _make_key()) is None

    def test_put_then_get(self, tmp_path: Path):
        key = _make_key()
        payload = {"nodes": [{"node_type": "Tool", "id": "Tool:x"}]}
        cache_put(tmp_path, key, payload)
        assert cache_get(tmp_path, key) == payload

    def test_different_keys_dont_collide(self, tmp_path: Path):
        k1 = _make_key()
        k2 = _make_key(adapter="openai")
        cache_put(tmp_path, k1, {"a": 1})
        cache_put(tmp_path, k2, {"b": 2})
        assert cache_get(tmp_path, k1) == {"a": 1}
        assert cache_get(tmp_path, k2) == {"b": 2}

    def test_atomic_write_leaves_no_tmp_file(self, tmp_path: Path):
        key = _make_key()
        cache_put(tmp_path, key, {"x": 1})
        cache_dir = key.cache_path(tmp_path).parent
        leftovers = list(cache_dir.glob("*.tmp"))
        assert leftovers == [], f"Stale .tmp files: {leftovers}"

    def test_corrupted_cache_treated_as_miss(self, tmp_path: Path):
        key = _make_key()
        path = key.cache_path(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ this is not valid json")
        assert cache_get(tmp_path, key) is None

    def test_format_version_mismatch_treated_as_miss(self, tmp_path: Path):
        key = _make_key()
        path = key.cache_path(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "cache_format_version": 999,
            "key_fingerprint": key.fingerprint(),
            "key": {},
            "payload": {"x": 1},
        }))
        assert cache_get(tmp_path, key) is None

    def test_fingerprint_mismatch_treated_as_miss(self, tmp_path: Path):
        # Defensive belt-and-braces: the filename already encodes the key,
        # but the body carries it too. If they disagree (manual surgery
        # gone wrong) we treat it as a miss instead of trusting the body.
        key = _make_key()
        path = key.cache_path(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "cache_format_version": 1,
            "key_fingerprint": "f" * 64,
            "key": {},
            "payload": {"x": 1},
        }))
        assert cache_get(tmp_path, key) is None


# ---------------------------------------------------------------------------
# repo_commit_sha
# ---------------------------------------------------------------------------


class TestRepoCommitSha:
    def test_uses_git_when_available(self, tmp_path: Path):
        try:
            subprocess.run(
                ["git", "init", str(tmp_path)],
                check=True, capture_output=True, timeout=10,
            )
            subprocess.run(
                ["git", "-C", str(tmp_path), "config", "user.email", "x@y.z"],
                check=True, capture_output=True, timeout=10,
            )
            subprocess.run(
                ["git", "-C", str(tmp_path), "config", "user.name", "Test"],
                check=True, capture_output=True, timeout=10,
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            pytest.skip("git not available in test environment")

        (tmp_path / "README.md").write_text("hi")
        subprocess.run(
            ["git", "-C", str(tmp_path), "add", "."],
            check=True, capture_output=True, timeout=10,
        )
        subprocess.run(
            ["git", "-C", str(tmp_path), "commit", "-m", "init"],
            check=True, capture_output=True, timeout=10,
        )

        sha = repo_commit_sha(tmp_path)
        assert len(sha) == 40
        assert all(c in "0123456789abcdef" for c in sha)

    def test_falls_back_to_content_hash_without_git(self, tmp_path: Path):
        (tmp_path / "a.txt").write_text("alpha")
        (tmp_path / "b.txt").write_text("beta")

        sha = repo_commit_sha(tmp_path)
        # SHA-256 is 64 hex chars (vs git's 40).
        assert len(sha) == 64
        assert all(c in "0123456789abcdef" for c in sha)

    def test_content_hash_changes_when_file_changes(self, tmp_path: Path):
        (tmp_path / "a.txt").write_text("alpha")
        first = repo_commit_sha(tmp_path)
        (tmp_path / "a.txt").write_text("alpha-modified")
        second = repo_commit_sha(tmp_path)
        assert first != second

    def test_content_hash_skips_cache_dir(self, tmp_path: Path):
        # Writing into .cache/asp-llm-scan/ must not invalidate the very
        # cache key it computes — that would be a self-defeating cycle.
        (tmp_path / "a.txt").write_text("alpha")
        before = repo_commit_sha(tmp_path)
        cache_dir = tmp_path / ".cache" / "asp-llm-scan"
        cache_dir.mkdir(parents=True)
        (cache_dir / "result.json").write_text('{"x": 1}')
        after = repo_commit_sha(tmp_path)
        assert before == after


# ---------------------------------------------------------------------------
# prompt_sha
# ---------------------------------------------------------------------------


class TestPromptSha:
    def test_deterministic_across_input_order(self, tmp_path: Path):
        a = tmp_path / "a.md"; a.write_text("alpha")
        b = tmp_path / "b.md"; b.write_text("beta")
        # Different argument orders must produce identical digests.
        assert prompt_sha([a, b]) == prompt_sha([b, a])

    def test_changes_when_prompt_changes(self, tmp_path: Path):
        a = tmp_path / "a.md"; a.write_text("alpha")
        before = prompt_sha([a])
        a.write_text("alpha-edited")
        assert before != prompt_sha([a])

    def test_changes_when_filename_changes(self, tmp_path: Path):
        # Renaming is a meaningful change — different filename means
        # different prompt role even with the same content.
        a = tmp_path / "a.md"; a.write_text("hi")
        b = tmp_path / "b.md"; b.write_text("hi")
        assert prompt_sha([a]) != prompt_sha([b])
