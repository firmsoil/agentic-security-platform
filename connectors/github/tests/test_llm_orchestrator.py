"""Orchestrator end-to-end tests using a controllable FakeAdapter.

No real LLM calls. Each test stages canned adapter responses and asserts
the orchestrator wires extraction → static-check → verification → cache
correctly.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest

from connectors.github.src.llm.orchestrator import (
    ScanReport,
    scan_with_llm,
)
from connectors.github.src.llm.protocol import (
    AdapterCallResult,
    AdapterError,
    StructuredExtractor,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A small Python repo with two source files.

    Lives under ``tmp_path/repo`` so the prompts fixture (a sibling) is
    not visible to the file walker.
    """
    rdir = tmp_path / "repo"
    src = rdir / "src"
    src.mkdir(parents=True)
    (src / "tools.py").write_text(
        "EXPORT_TOOL = {\n"
        "    'name': 'export_data',\n"
        "    'description': 'Write memory to disk.',\n"
        "}\n"
    )
    (src / "model.py").write_text(
        "SYSTEM_PROMPT = 'You are a helpful assistant.'\n"
    )
    return rdir


@pytest.fixture
def prompts(tmp_path: Path) -> Path:
    """A prompts/ dir with stub files. Sibling to ``repo`` so the file
    walker doesn't traverse it."""
    pdir = tmp_path / "prompts"
    pdir.mkdir()
    for name in (
        "extract_tools.md",
        "extract_prompt_templates.md",
        "extract_rag_indices.md",
        "extract_memory_stores.md",
    ):
        (pdir / name).write_text(f"# {name}\nstub\n")
    return pdir


@pytest.fixture
def empty_repo(tmp_path: Path) -> Path:
    """An empty repo at a separate location from the prompts fixture."""
    rdir = tmp_path / "empty_repo"
    rdir.mkdir()
    return rdir


def _sha_of(repo: Path, rel: str) -> str:
    return hashlib.sha256((repo / rel).read_bytes()).hexdigest()


def _grounded_node(
    *,
    node_type: str,
    name: str,
    file_path: str,
    file_sha256: str,
    line_start: int = 1,
    line_end: int = 3,
):
    return {
        "node_type": node_type,
        "id": f"{node_type}:{name}",
        "properties": {"name": name},
        "grounding": {
            "file_path": file_path,
            "line_start": line_start,
            "line_end": line_end,
            "file_sha256": file_sha256,
            "evidence": f"file declares {name}",
            "confidence": "high",
        },
    }


class _FakeAdapter:
    """Controllable adapter — extract returns one canned response per
    extract_tools/etc prompt-file basename; verify always accepts unless
    configured otherwise."""

    name = "fake"
    model_name = "fake-model"

    def __init__(
        self,
        *,
        extract_responses: dict[str, list[dict[str, Any]]] | None = None,
        verify_verdict: bool = True,
        token_per_call: int = 100,
        raise_on_extract: bool = False,
    ):
        self._responses = extract_responses or defaultdict(list)
        self._verify_verdict = verify_verdict
        self._token_per_call = token_per_call
        self._raise_on_extract = raise_on_extract
        self.extract_calls: list[dict[str, Any]] = []
        self.verify_calls: list[dict[str, Any]] = []

    async def extract(self, *, system_prompt, user_prompt, schema):
        self.extract_calls.append({"user_prompt": user_prompt})
        if self._raise_on_extract:
            raise AdapterError("simulated provider failure")
        # Match the canned response by which extract_*.md file's body
        # appears in the user prompt. The orchestrator concatenates the
        # prompt body at the top, so a substring search works.
        nodes: list[dict[str, Any]] = []
        for keyword, payload in self._responses.items():
            if keyword in user_prompt:
                nodes.extend(payload)
        return AdapterCallResult(
            payload={"nodes": nodes},
            model_name=self.model_name,
            input_tokens=self._token_per_call,
            output_tokens=self._token_per_call,
        )

    async def verify(self, *, system_prompt, user_prompt, schema):
        self.verify_calls.append({"user_prompt": user_prompt})
        return AdapterCallResult(
            payload={"verified": self._verify_verdict, "reason": "ok"},
            model_name=self.model_name,
            input_tokens=10,
            output_tokens=10,
        )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_pipeline_accepts_grounded_node(repo, prompts):
    sha = _sha_of(repo, "src/tools.py")
    adapter = _FakeAdapter(extract_responses={
        "extract_tools.md": [_grounded_node(
            node_type="Tool",
            name="export_data",
            file_path="src/tools.py",
            file_sha256=sha,
        )],
    })

    accepted, report = await scan_with_llm(
        repo, adapter=adapter, stack="python", prompts_dir=prompts,
    )

    assert len(accepted) == 1
    assert accepted[0]["id"] == "Tool:export_data"
    assert report.candidates_accepted == 1
    assert report.candidates_extracted == 1
    assert report.cache_hit is False
    assert report.aborted_reason is None
    assert report.input_tokens > 0


# ---------------------------------------------------------------------------
# Orchestrator-level static rejections
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rejects_wrong_node_type(repo, prompts):
    """Model returned a Tool when asked for a PromptTemplate."""
    sha = _sha_of(repo, "src/model.py")
    adapter = _FakeAdapter(extract_responses={
        "extract_prompt_templates.md": [_grounded_node(
            node_type="Tool",  # wrong — extract_prompt_templates expects PromptTemplate
            name="bogus",
            file_path="src/model.py",
            file_sha256=sha,
        )],
    })

    accepted, report = await scan_with_llm(
        repo, adapter=adapter, stack="python", prompts_dir=prompts,
    )

    assert accepted == []
    assert report.candidates_rejected_at_orchestrator == 1
    rejection = next(
        r for r in report.rejection_log if r["stage"] == "orchestrator"
    )
    assert "wrong_node_type" in rejection["reason"]


@pytest.mark.asyncio
async def test_rejects_unknown_file_path(repo, prompts):
    """Model cited a file we never sent."""
    adapter = _FakeAdapter(extract_responses={
        "extract_tools.md": [_grounded_node(
            node_type="Tool",
            name="export_data",
            file_path="src/does_not_exist.py",
            file_sha256="0" * 64,
        )],
    })

    accepted, report = await scan_with_llm(
        repo, adapter=adapter, stack="python", prompts_dir=prompts,
    )

    assert accepted == []
    assert report.candidates_rejected_at_orchestrator == 1
    assert "unknown_file_path" in report.rejection_log[0]["reason"]


@pytest.mark.asyncio
async def test_rejects_sha_mismatch_at_extract(repo, prompts):
    """Model invented a SHA different from what we computed at walk time."""
    adapter = _FakeAdapter(extract_responses={
        "extract_tools.md": [_grounded_node(
            node_type="Tool",
            name="export_data",
            file_path="src/tools.py",
            file_sha256="f" * 64,  # wrong
        )],
    })

    accepted, report = await scan_with_llm(
        repo, adapter=adapter, stack="python", prompts_dir=prompts,
    )

    assert accepted == []
    assert report.candidates_rejected_at_orchestrator == 1
    assert "sha_mismatch_at_extract" in report.rejection_log[0]["reason"]


# ---------------------------------------------------------------------------
# Verifier rejections come through to the report
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verifier_rejection_drops_node(repo, prompts):
    sha = _sha_of(repo, "src/tools.py")
    adapter = _FakeAdapter(
        extract_responses={
            "extract_tools.md": [_grounded_node(
                node_type="Tool",
                name="export_data",
                file_path="src/tools.py",
                file_sha256=sha,
            )],
        },
        verify_verdict=False,
    )

    accepted, report = await scan_with_llm(
        repo, adapter=adapter, stack="python", prompts_dir=prompts,
    )

    assert accepted == []
    assert report.candidates_rejected_at_verifier == 1
    assert any(
        r["stage"] == "verifier" for r in report.rejection_log
    )


# ---------------------------------------------------------------------------
# Token budget
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aborts_on_token_overrun(repo, prompts):
    # token_per_call=10000 over four extraction prompts × 1 batch = 40k
    # tokens of output, plus our pre-call estimate of input. With
    # max_tokens=20000 the orchestrator should abort partway through.
    adapter = _FakeAdapter(token_per_call=10_000)
    accepted, report = await scan_with_llm(
        repo, adapter=adapter, stack="python", prompts_dir=prompts,
        max_tokens=20_000,
    )
    assert report.aborted_reason is not None
    assert "max_tokens" in report.aborted_reason
    # Aborted scans produce no accepted nodes and don't write the cache.
    assert accepted == []


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_hit_skips_llm_calls(repo, prompts):
    sha = _sha_of(repo, "src/tools.py")
    adapter1 = _FakeAdapter(extract_responses={
        "extract_tools.md": [_grounded_node(
            node_type="Tool", name="export_data",
            file_path="src/tools.py", file_sha256=sha,
        )],
    })
    accepted1, report1 = await scan_with_llm(
        repo, adapter=adapter1, stack="python", prompts_dir=prompts,
    )
    assert report1.cache_hit is False
    assert len(accepted1) == 1

    # Second call with a different (failing) adapter — but cache hit
    # short-circuits before any adapter call.
    adapter2 = _FakeAdapter(raise_on_extract=True)
    accepted2, report2 = await scan_with_llm(
        repo, adapter=adapter2, stack="python", prompts_dir=prompts,
    )
    assert report2.cache_hit is True
    assert accepted2 == accepted1
    assert adapter2.extract_calls == []
    assert adapter2.verify_calls == []


@pytest.mark.asyncio
async def test_use_cache_false_bypasses_cache(repo, prompts):
    sha = _sha_of(repo, "src/tools.py")
    canned = [_grounded_node(
        node_type="Tool", name="export_data",
        file_path="src/tools.py", file_sha256=sha,
    )]
    adapter1 = _FakeAdapter(extract_responses={"extract_tools.md": canned})
    await scan_with_llm(
        repo, adapter=adapter1, stack="python", prompts_dir=prompts,
    )

    adapter2 = _FakeAdapter(extract_responses={"extract_tools.md": canned})
    _, report2 = await scan_with_llm(
        repo, adapter=adapter2, stack="python", prompts_dir=prompts,
        use_cache=False,
    )
    assert report2.cache_hit is False
    assert adapter2.extract_calls != []


@pytest.mark.asyncio
async def test_aborted_scan_not_cached(repo, prompts):
    adapter1 = _FakeAdapter(token_per_call=10_000)
    _, report1 = await scan_with_llm(
        repo, adapter=adapter1, stack="python", prompts_dir=prompts,
        max_tokens=20_000,
    )
    assert report1.aborted_reason is not None

    # Second call with normal budget should re-attempt rather than serve
    # the aborted partial result.
    sha = _sha_of(repo, "src/tools.py")
    adapter2 = _FakeAdapter(extract_responses={
        "extract_tools.md": [_grounded_node(
            node_type="Tool", name="export_data",
            file_path="src/tools.py", file_sha256=sha,
        )],
    })
    accepted2, report2 = await scan_with_llm(
        repo, adapter=adapter2, stack="python", prompts_dir=prompts,
    )
    assert report2.cache_hit is False
    assert len(accepted2) == 1


# ---------------------------------------------------------------------------
# Adapter failure during extraction is recoverable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_adapter_error_logged_not_fatal(repo, prompts):
    adapter = _FakeAdapter(raise_on_extract=True)
    accepted, report = await scan_with_llm(
        repo, adapter=adapter, stack="python", prompts_dir=prompts,
    )
    # No nodes extracted, but the scan completes with a logged rejection.
    assert accepted == []
    assert report.aborted_reason is None
    assert any(
        r["stage"] == "extract" and "adapter_error" in r["reason"]
        for r in report.rejection_log
    )


# ---------------------------------------------------------------------------
# Empty repo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_repo_returns_empty_quickly(empty_repo, prompts):
    adapter = _FakeAdapter()
    accepted, report = await scan_with_llm(
        empty_repo, adapter=adapter, stack="python", prompts_dir=prompts,
    )
    assert accepted == []
    assert report.files_walked == 0
    assert adapter.extract_calls == []
