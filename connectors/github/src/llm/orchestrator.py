"""LLM scanner orchestrator — the top-level entry point.

Drives the full extraction pipeline:

    walk repo → cache lookup → for each extraction prompt:
        for each file batch: extract → orchestrator-level reject
    aggregate candidates → verify → cache write → return

The orchestrator returns the *accepted grounded nodes* (list[dict]) plus
a ``ScanReport`` of telemetry. It does NOT produce a full ``ScanResult``
— the dispatcher (``connectors.github.src.scanner.scan_repository``)
merges the LLM-extracted nodes with the deterministic manifest output
to assemble a complete ScanResult.

Key design decisions, all per ADR-0005:

- **Token budget is enforced.** The orchestrator aborts loudly if total
  input+output tokens cross ``max_tokens``. Cost overruns are not
  silently absorbed.
- **Orchestrator-level reject before verifier.** If a candidate node's
  grounding cites a file we didn't send, or claims a SHA we never
  computed, we reject it before the verification call — that's a cheap
  static check and saves an LLM round-trip.
- **Same adapter for extract and verify.** The verifier receives the
  same adapter instance the extractor used. No cross-adapter mixing
  inside a single scan.
- **Cache hit returns immediately.** No LLM calls, no walk re-traversal
  of file content. The cache key composition is the load-bearing
  reproducibility guarantee.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from connectors.github.src.llm import SCANNER_VERSION
from connectors.github.src.llm.cache import (
    CacheKey,
    cache_get,
    cache_put,
    prompt_sha,
    repo_commit_sha,
)
from connectors.github.src.llm.file_walk import (
    WalkedFile,
    batch_files,
    walk_repo,
)
from connectors.github.src.llm.prompts import (
    EXTRACTION_PROMPTS,
    all_extraction_prompt_paths,
    compose_extraction_user_prompt,
    known_file_index,
    load_prompt,
)
from connectors.github.src.llm.protocol import (
    AdapterError,
    StructuredExtractor,
)
from connectors.github.src.llm.schema import (
    EXTRACTION_RESPONSE_SCHEMA,
    GroundingValidationError,
    validate_extraction_response,
)
from connectors.github.src.llm.verifier import verify_nodes

log = logging.getLogger(__name__)

# Default token budget per scan. Generous enough that the bundled demo
# target won't trip it; small enough that a runaway prompt burns out
# fast rather than running up a bill. Override per call.
DEFAULT_MAX_TOKENS = 200_000


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------


@dataclass
class ScanReport:
    """Telemetry for one ``scan_with_llm`` call.

    Returned alongside the accepted nodes so callers can log spend, audit
    rejection counts, and diff against the deterministic scanner output
    in parity tests.
    """

    files_walked: int = 0
    extract_calls: int = 0
    verify_calls: int = 0
    candidates_extracted: int = 0
    candidates_rejected_at_orchestrator: int = 0
    candidates_rejected_at_verifier: int = 0
    candidates_accepted: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_hit: bool = False
    aborted_reason: str | None = None
    rejection_log: list[dict[str, Any]] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def summary(self) -> str:
        if self.cache_hit:
            return (
                f"ScanReport: cache hit — {self.candidates_accepted} nodes, "
                f"0 LLM calls."
            )
        if self.aborted_reason:
            return f"ScanReport: aborted ({self.aborted_reason}). " + self._counts()
        return f"ScanReport: " + self._counts()

    def _counts(self) -> str:
        return (
            f"{self.files_walked} files, {self.extract_calls} extract calls, "
            f"{self.verify_calls} verify calls, "
            f"{self.candidates_extracted} candidates → "
            f"{self.candidates_accepted} accepted "
            f"({self.candidates_rejected_at_orchestrator} static-rejected, "
            f"{self.candidates_rejected_at_verifier} verifier-rejected), "
            f"{self.total_tokens} tokens."
        )


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


async def scan_with_llm(
    repo_path: Path,
    *,
    adapter: StructuredExtractor,
    stack: str,
    prompts_dir: Path,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    use_cache: bool = True,
    file_filter: Callable[[Path], bool] | None = None,
) -> tuple[list[dict[str, Any]], ScanReport]:
    """Run the LLM scanner against ``repo_path``.

    Returns ``(accepted_nodes, report)``. ``accepted_nodes`` are
    grounded-node dicts with the ``grounding`` block intact — callers
    that write to the graph should strip or relocate the grounding
    block before calling ``upsert_node`` if it shouldn't live in the
    graph.
    """
    report = ScanReport()

    # ---- Cache lookup -----------------------------------------------------
    cache_key = _build_cache_key(
        repo_path=repo_path,
        adapter=adapter,
        prompts_dir=prompts_dir,
    )
    if use_cache:
        cached = cache_get(repo_path, cache_key)
        if cached is not None:
            report.cache_hit = True
            accepted = cached.get("accepted_nodes", [])
            report.candidates_accepted = len(accepted)
            return accepted, report

    # ---- Walk the repo ----------------------------------------------------
    files = walk_repo(repo_path, stack=stack, file_filter=file_filter)
    report.files_walked = len(files)
    if not files:
        log.info("scan_with_llm: no source files matched stack=%r", stack)
        _persist_cache_result(repo_path, cache_key, [], use_cache=use_cache)
        return [], report

    # ---- Extract — one prompt at a time, batched files ------------------
    candidates = await _run_extraction(
        files=files,
        adapter=adapter,
        prompts_dir=prompts_dir,
        max_tokens=max_tokens,
        report=report,
    )
    if report.aborted_reason is not None:
        # Don't cache aborted scans — re-running with a higher budget
        # should re-attempt rather than serve a partial result.
        return [], report

    # ---- Verify -----------------------------------------------------------
    verify_report = await verify_nodes(
        repo_path=repo_path,
        candidates=candidates,
        adapter=adapter,
    )
    report.verify_calls = sum(
        1 for o in verify_report.rejected
        if o.rejection_reason
        and not o.rejection_reason.startswith(("file_missing", "sha_drift",
                                               "line_out_of_range"))
    ) + len(verify_report.accepted)
    report.candidates_rejected_at_verifier = len(verify_report.rejected)
    for outcome in verify_report.rejected:
        report.rejection_log.append({
            "stage": "verifier",
            "node_id": outcome.node.get("id"),
            "reason": outcome.rejection_reason,
        })

    accepted = verify_report.accepted
    report.candidates_accepted = len(accepted)

    _persist_cache_result(
        repo_path, cache_key, accepted, use_cache=use_cache,
    )
    return accepted, report


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _build_cache_key(
    *,
    repo_path: Path,
    adapter: StructuredExtractor,
    prompts_dir: Path,
) -> CacheKey:
    return CacheKey(
        repo_commit_sha=repo_commit_sha(repo_path),
        scanner_version=SCANNER_VERSION,
        adapter=adapter.name,
        model_name=adapter.model_name,
        prompt_sha=prompt_sha(all_extraction_prompt_paths(prompts_dir)),
    )


def _persist_cache_result(
    repo_path: Path,
    key: CacheKey,
    accepted: list[dict[str, Any]],
    *,
    use_cache: bool,
) -> None:
    if not use_cache:
        return
    cache_put(repo_path, key, {"accepted_nodes": accepted})


_EXTRACT_SYSTEM_PROMPT = (
    "You extract ontology-typed security nodes from a batch of source "
    "files. Each emitted node MUST include a `grounding` block with the "
    "exact file_path and file_sha256 from the file delimiters in the "
    "input. Cite line ranges that contain the definition, not whole "
    "files. Set `confidence` to 'high' only when the file unambiguously "
    "defines the node; otherwise 'medium' or 'low'. If no nodes apply, "
    "return an empty `nodes` array."
)


async def _run_extraction(
    *,
    files: list[WalkedFile],
    adapter: StructuredExtractor,
    prompts_dir: Path,
    max_tokens: int,
    report: ScanReport,
) -> list[dict[str, Any]]:
    """Drive the extraction loop: per prompt × per batch.

    Mutates ``report`` in place to surface telemetry. Returns the union
    of all extracted-and-statically-accepted candidate nodes; the
    verifier handles the LLM-side second-pass.
    """
    candidates: list[dict[str, Any]] = []
    batches = batch_files(files)
    file_index = known_file_index(files)

    for prompt_def in EXTRACTION_PROMPTS:
        prompt_body = load_prompt(prompts_dir, prompt_def.filename)

        for batch in batches:
            # Compose user prompt for this batch.
            user_prompt = compose_extraction_user_prompt(
                prompt_body=prompt_body,
                files=batch,
            )

            # Pre-call budget check — if even a generous estimate of this
            # call's input would push us over, abort before spending.
            # Char-to-token approximation (4:1) is fine for an upper
            # bound; the post-call counter uses the adapter's exact
            # numbers.
            est_input_tokens = len(user_prompt) // 4
            if report.total_tokens + est_input_tokens > max_tokens:
                report.aborted_reason = (
                    f"max_tokens ({max_tokens}) would be exceeded by next "
                    f"extract call (est {est_input_tokens} input tokens; "
                    f"already spent {report.total_tokens})"
                )
                return candidates

            try:
                result = await adapter.extract(
                    system_prompt=_EXTRACT_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    schema=EXTRACTION_RESPONSE_SCHEMA,
                )
            except AdapterError as exc:
                # Adapter failure during extraction is recorded but
                # doesn't abort the whole scan — other prompt × batch
                # combinations may still succeed. The verifier will
                # validate whatever does come back.
                log.warning(
                    "scan_with_llm: extract failed for prompt=%s batch=%d: %s",
                    prompt_def.filename, len(batch), exc,
                )
                report.rejection_log.append({
                    "stage": "extract",
                    "prompt": prompt_def.filename,
                    "reason": f"adapter_error: {exc}",
                })
                continue

            report.extract_calls += 1
            if result.input_tokens is not None:
                report.input_tokens += result.input_tokens
            if result.output_tokens is not None:
                report.output_tokens += result.output_tokens

            # Hard abort if the actual spend overshoots; better to lose
            # the in-flight result than continue racking up cost.
            if report.total_tokens > max_tokens:
                report.aborted_reason = (
                    f"max_tokens ({max_tokens}) exceeded after extract "
                    f"call ({report.total_tokens} actual)"
                )
                return candidates

            try:
                nodes = validate_extraction_response(result.payload)
            except GroundingValidationError as exc:
                log.warning(
                    "scan_with_llm: malformed extraction response from "
                    "prompt=%s: %s",
                    prompt_def.filename, exc,
                )
                report.rejection_log.append({
                    "stage": "extract",
                    "prompt": prompt_def.filename,
                    "reason": f"malformed_response: {exc}",
                })
                continue

            for node in nodes:
                report.candidates_extracted += 1
                rejection = _orchestrator_static_check(
                    node=node,
                    expected_node_type=prompt_def.target_node_type,
                    file_index=file_index,
                )
                if rejection is not None:
                    report.candidates_rejected_at_orchestrator += 1
                    report.rejection_log.append({
                        "stage": "orchestrator",
                        "prompt": prompt_def.filename,
                        "node_id": node.get("id"),
                        "reason": rejection,
                    })
                    continue
                candidates.append(node)

    return candidates


def _orchestrator_static_check(
    *,
    node: dict[str, Any],
    expected_node_type: str,
    file_index: dict[str, str],
) -> str | None:
    """Return None on accept, or a rejection reason string.

    Catches three classes of LLM error cheaply:
    - emitted node_type doesn't match the prompt's target node type
      (the model returned a Tool when asked to extract PromptTemplates)
    - cited file_path was never in the batch we sent
    - cited file_sha256 disagrees with what we computed at walk time
    """
    if node["node_type"] != expected_node_type:
        return (
            f"wrong_node_type: prompt asked for {expected_node_type!r}, "
            f"model returned {node['node_type']!r}"
        )
    g = node["grounding"]
    expected_sha = file_index.get(g["file_path"])
    if expected_sha is None:
        return f"unknown_file_path: {g['file_path']!r} not in batch"
    if expected_sha != g["file_sha256"]:
        return (
            f"sha_mismatch_at_extract: file {g['file_path']!r} expected "
            f"{expected_sha[:12]}…, got {g['file_sha256'][:12]}…"
        )
    return None
