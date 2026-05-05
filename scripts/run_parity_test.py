"""Ad-hoc parity-test runner.

Usage::

    # With Anthropic (default)
    ANTHROPIC_API_KEY=sk-ant-... python3 scripts/run_parity_test.py

    # Force the OpenAI adapter
    OPENAI_API_KEY=sk-... ASP_LLM_PROVIDER=openai python3 scripts/run_parity_test.py

    # Pin a specific model
    ANTHROPIC_API_KEY=... ASP_LLM_MODEL=claude-sonnet-4-5 python3 scripts/run_parity_test.py

    # Different target repo (default is examples/vulnerable-rag-app)
    python3 scripts/run_parity_test.py --repo path/to/some/repo

Exits 0 on strict-match parity, 1 otherwise. Property diffs are printed
but do not affect the exit code.

This is a thin wrapper over ``connectors.github.tests.parity`` — the
same logic the pytest test consumes — so the runner's verdict matches
what CI will report.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Make the repo root importable regardless of cwd, so `uv run python3
# scripts/run_parity_test.py …` works without `PYTHONPATH=.`.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run-parity-test",
        description=(
            "Compare the LLM scanner's output to the Python static scanner "
            "on a target repo. Strict-match parity is required for launch "
            "readiness; property diffs are informational."
        ),
    )
    p.add_argument(
        "--repo",
        type=Path,
        default=Path("examples/vulnerable-rag-app"),
        help="Path to the repo to scan (default: examples/vulnerable-rag-app).",
    )
    p.add_argument(
        "--prompts-dir",
        type=Path,
        default=Path("prompts"),
        help="Directory holding the four extract_*.md prompts (default: prompts/).",
    )
    p.add_argument(
        "--use-cache",
        action="store_true",
        default=False,
        help=(
            "Allow the LLM scanner's filesystem cache to serve a hit. "
            "Off by default — parity runs should be fresh."
        ),
    )
    p.add_argument("-v", "--verbose", action="store_true", default=False)
    return p


def _build_adapter():
    """Same selection logic as the pytest test, kept in sync intentionally."""
    provider = os.environ.get("ASP_LLM_PROVIDER", "").lower()
    has_anthropic = bool(
        os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ASP_LLM_API_KEY")
    )
    has_openai = bool(
        os.environ.get("OPENAI_API_KEY") or os.environ.get("ASP_LLM_API_KEY")
    )
    if not (has_anthropic or has_openai):
        sys.exit(
            "ERROR: parity test requires an API key. Set ANTHROPIC_API_KEY, "
            "OPENAI_API_KEY, or ASP_LLM_API_KEY."
        )
    if provider == "openai" or (provider == "" and not has_anthropic and has_openai):
        from connectors.github.src.llm.openai_adapter import OpenAIAdapter
        return OpenAIAdapter()
    from connectors.github.src.llm.anthropic_adapter import AnthropicAdapter
    return AnthropicAdapter()


async def _run(args: argparse.Namespace) -> int:
    from connectors.github.src.llm.orchestrator import scan_with_llm
    from connectors.github.src.scanner import scan_repository
    from connectors.github.tests.parity import (
        compute_parity_diff,
        filter_to_llm_scope,
    )

    if not args.repo.is_dir():
        print(f"ERROR: repo not found: {args.repo}", file=sys.stderr)
        return 2
    if not args.prompts_dir.is_dir():
        print(
            f"ERROR: prompts directory not found: {args.prompts_dir}",
            file=sys.stderr,
        )
        return 2

    adapter = _build_adapter()
    print(f"Adapter: {adapter.name} model={adapter.model_name}")
    print(f"Target:  {args.repo}")
    print(f"Prompts: {args.prompts_dir}")
    print()

    # Ground truth.
    static_result = scan_repository(args.repo, stack="python")
    static_filtered = filter_to_llm_scope(list(static_result.nodes))
    print(
        f"Static scanner produced {len(static_filtered)} LLM-scope nodes:"
    )
    for n in sorted(static_filtered, key=lambda n: n["id"]):
        print(f"  - {n['id']}")
    print()

    # LLM scan.
    accepted, report = await scan_with_llm(
        args.repo,
        adapter=adapter,
        stack="python",
        prompts_dir=args.prompts_dir,
        use_cache=args.use_cache,
    )
    print(report.summary())
    if report.aborted_reason:
        print(f"\nABORTED: {report.aborted_reason}", file=sys.stderr)
        return 1

    print()
    print(f"LLM scanner accepted {len(accepted)} nodes:")
    for n in sorted(accepted, key=lambda n: n["id"]):
        print(f"  - {n['id']}  ({n['grounding']['confidence']})")
    print()

    diff = compute_parity_diff(static_filtered, accepted)
    print(diff.format_report())
    print()

    if diff.is_strict_match:
        print("Strict-match parity: ✓")
        return 0

    print("Strict-match parity: FAILED", file=sys.stderr)
    return 1


def main() -> int:
    args = _build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-8s %(name)s: %(message)s",
    )
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
