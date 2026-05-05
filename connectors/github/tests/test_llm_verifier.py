"""Verifier tests — covers the static checks (file existence, SHA match,
line range) without any LLM call. The LLM-call branch is gated behind a
fake adapter that returns fixed payloads, so we can exercise verdict
handling without burning API credits."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from connectors.github.src.llm.protocol import (
    AdapterCallResult,
    AdapterError,
)
from connectors.github.src.llm.verifier import (
    VerificationOutcome,
    verify_nodes,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_node(file_path: str, file_sha256: str, **g_overrides):
    grounding = {
        "file_path": file_path,
        "line_start": 1,
        "line_end": 3,
        "file_sha256": file_sha256,
        "evidence": "x",
        "confidence": "high",
    }
    grounding.update(g_overrides)
    return {
        "node_type": "Tool",
        "id": "Tool:export_data",
        "properties": {"name": "export_data"},
        "grounding": grounding,
    }


class _FakeAdapter:
    """Stand-in StructuredExtractor — controllable verify() outcome."""

    name = "fake"
    model_name = "fake-model"

    def __init__(
        self,
        verdict: bool = True,
        reason: str = "ok",
        raise_error: bool = False,
        malformed: bool = False,
    ):
        self.verdict = verdict
        self.reason = reason
        self.raise_error = raise_error
        self.malformed = malformed
        self.calls: list[dict[str, Any]] = []

    async def extract(self, **kwargs) -> AdapterCallResult:  # pragma: no cover
        raise NotImplementedError

    async def verify(self, *, system_prompt, user_prompt, schema) -> AdapterCallResult:
        self.calls.append({
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
        })
        if self.raise_error:
            raise AdapterError("simulated provider failure")
        if self.malformed:
            return AdapterCallResult(
                payload={"verified": "yes"},  # wrong type
                model_name=self.model_name,
            )
        return AdapterCallResult(
            payload={"verified": self.verdict, "reason": self.reason},
            model_name=self.model_name,
        )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A tiny repo with one source file the verifier can re-open."""
    (tmp_path / "src").mkdir()
    src = tmp_path / "src" / "tools.py"
    src.write_text("def export_data():\n    pass\n# end\n")
    return tmp_path


# ---------------------------------------------------------------------------
# Static checks (no LLM call)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_file_missing_rejects_without_calling_llm(repo):
    adapter = _FakeAdapter()
    bad = _make_node("src/does-not-exist.py", "0" * 64)
    report = await verify_nodes(repo_path=repo, candidates=[bad], adapter=adapter)
    assert report.accepted == []
    assert len(report.rejected) == 1
    assert report.rejected[0].rejection_reason.startswith("file_missing")
    assert adapter.calls == [], "adapter must not be called on static failure"


@pytest.mark.asyncio
async def test_sha_drift_rejects_without_calling_llm(repo):
    adapter = _FakeAdapter()
    bad = _make_node("src/tools.py", "f" * 64)  # wrong sha
    report = await verify_nodes(repo_path=repo, candidates=[bad], adapter=adapter)
    assert len(report.rejected) == 1
    assert report.rejected[0].rejection_reason.startswith("sha_drift")
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_line_out_of_range_rejects_without_calling_llm(repo):
    adapter = _FakeAdapter()
    actual_sha = _sha256_of(repo / "src" / "tools.py")
    # The file has 3 lines; ask for lines 100-110.
    bad = _make_node(
        "src/tools.py", actual_sha, line_start=100, line_end=110,
    )
    report = await verify_nodes(repo_path=repo, candidates=[bad], adapter=adapter)
    assert len(report.rejected) == 1
    assert report.rejected[0].rejection_reason.startswith("line_out_of_range")
    assert adapter.calls == []


# ---------------------------------------------------------------------------
# LLM verdict branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_static_pass_then_llm_accept(repo):
    actual_sha = _sha256_of(repo / "src" / "tools.py")
    node = _make_node("src/tools.py", actual_sha)
    adapter = _FakeAdapter(verdict=True, reason="span declares the tool")

    report = await verify_nodes(repo_path=repo, candidates=[node], adapter=adapter)

    assert len(report.accepted) == 1
    assert report.rejected == []
    assert len(adapter.calls) == 1
    # Verifier prompt embeds the cited code.
    assert "def export_data" in adapter.calls[0]["user_prompt"]


@pytest.mark.asyncio
async def test_static_pass_then_llm_reject(repo):
    actual_sha = _sha256_of(repo / "src" / "tools.py")
    node = _make_node("src/tools.py", actual_sha)
    adapter = _FakeAdapter(verdict=False, reason="span declares something else")

    report = await verify_nodes(repo_path=repo, candidates=[node], adapter=adapter)

    assert report.accepted == []
    assert len(report.rejected) == 1
    assert report.rejected[0].rejection_reason.startswith("llm_rejected")


@pytest.mark.asyncio
async def test_adapter_error_treated_as_rejection(repo):
    actual_sha = _sha256_of(repo / "src" / "tools.py")
    node = _make_node("src/tools.py", actual_sha)
    adapter = _FakeAdapter(raise_error=True)

    report = await verify_nodes(repo_path=repo, candidates=[node], adapter=adapter)

    # The adapter failed to ask. We must NOT silently accept un-verified
    # nodes — treat as rejection with adapter_error reason.
    assert report.accepted == []
    assert len(report.rejected) == 1
    assert report.rejected[0].rejection_reason.startswith("adapter_error")


@pytest.mark.asyncio
async def test_malformed_verification_response_rejects(repo):
    actual_sha = _sha256_of(repo / "src" / "tools.py")
    node = _make_node("src/tools.py", actual_sha)
    adapter = _FakeAdapter(malformed=True)

    report = await verify_nodes(repo_path=repo, candidates=[node], adapter=adapter)

    assert report.accepted == []
    assert len(report.rejected) == 1
    assert report.rejected[0].rejection_reason.startswith(
        "malformed_verification_response",
    )


@pytest.mark.asyncio
async def test_report_summary(repo):
    actual_sha = _sha256_of(repo / "src" / "tools.py")
    accepted_node = _make_node("src/tools.py", actual_sha)
    rejected_node = _make_node("src/missing.py", "0" * 64)
    adapter = _FakeAdapter(verdict=True, reason="ok")

    report = await verify_nodes(
        repo_path=repo,
        candidates=[accepted_node, rejected_node],
        adapter=adapter,
    )
    assert "1 accepted" in report.summary()
    assert "1 rejected" in report.summary()
    assert report.total == 2
