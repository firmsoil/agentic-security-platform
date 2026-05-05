"""Predicted-IDs reconciliation runner.

Compares a target profile's ``expected_nodes`` against the dispatcher's
actual scan output (manifest + LLM if --enable-llm equivalent). Reports
which PREDICTED IDs were confirmed, which drifted (likely renames),
which are missing entirely, and which actual IDs the profile doesn't
reference yet.

Usage::

    # Reconcile J1 against a local clone
    ANTHROPIC_API_KEY=sk-ant-... python3 scripts/reconcile_target.py \\
        --target targets/customer-support-agent.yaml \\
        --repo /targets/customer-support-agent-example \\
        --enable-llm

    # Manifest-only reconciliation (faster; useful for Repository/
    # Container/Artifact/Model checks before paying for the LLM pass)
    python3 scripts/reconcile_target.py \\
        --target targets/customer-support-agent.yaml \\
        --repo /targets/customer-support-agent-example

Exit codes:
  0 = clean reconciliation (every expected_node confirmed, no unclaimed)
  1 = drift / missing / unclaimed (the user has YAML edits to make)
  2 = setup error (profile not found, repo not found, missing API key
      when --enable-llm is set, etc.)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Make the repo root importable regardless of cwd, so `uv run python3
# scripts/reconcile_target.py …` works without `PYTHONPATH=.`.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

log = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="reconcile-target",
        description=(
            "Diff a target profile's expected_nodes against the actual "
            "dispatcher scan output. Reports confirmed / drifted / "
            "missing / unclaimed IDs and suggests one-line YAML edits."
        ),
    )
    p.add_argument(
        "--target",
        type=Path,
        required=True,
        help="Path to a target profile YAML (e.g. targets/customer-support-agent.yaml).",
    )
    p.add_argument(
        "--repo",
        type=Path,
        required=True,
        help="Path to the cloned repo to scan.",
    )
    p.add_argument(
        "--enable-llm",
        action="store_true",
        default=False,
        help=(
            "Run the LLM scanner after the manifest pass. Required to "
            "reconcile Tool/PromptTemplate/RAGIndex/MemoryStore predictions "
            "on Java and Node targets."
        ),
    )
    p.add_argument(
        "--llm-provider",
        type=str,
        choices=("anthropic", "openai"),
        default=None,
        help="Adapter to use. Auto-selected from env keys if omitted.",
    )
    p.add_argument(
        "--llm-model",
        type=str,
        default=None,
        help="Override the adapter's default model.",
    )
    p.add_argument(
        "--prompts-dir",
        type=Path,
        default=Path("prompts"),
        help="Directory containing extract_*.md prompts (default: ./prompts).",
    )
    p.add_argument(
        "--max-llm-tokens",
        type=int,
        default=200_000,
        help="Hard cap on LLM tokens per scan (default: 200000).",
    )
    p.add_argument(
        "--no-llm-cache",
        action="store_true",
        default=False,
        help="Bypass the LLM scanner's filesystem cache.",
    )
    p.add_argument(
        "--stack",
        type=str,
        choices=("python", "java", "node"),
        default=None,
        help="Override stack detection.",
    )
    p.add_argument("-v", "--verbose", action="store_true", default=False)
    return p


def _build_adapter(args: argparse.Namespace):
    """Same adapter selection as __main__.py and run_parity_test.py — kept
    in sync intentionally so all three never disagree."""
    provider = args.llm_provider
    has_anthropic = bool(
        os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ASP_LLM_API_KEY")
    )
    has_openai = bool(
        os.environ.get("OPENAI_API_KEY") or os.environ.get("ASP_LLM_API_KEY")
    )
    if provider is None:
        if has_anthropic:
            provider = "anthropic"
        elif has_openai:
            provider = "openai"
        else:
            sys.exit(
                "ERROR: --enable-llm set but no LLM API key found. "
                "Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or ASP_LLM_API_KEY."
            )
    if provider == "anthropic":
        from connectors.github.src.llm.anthropic_adapter import AnthropicAdapter
        return AnthropicAdapter(model_name=args.llm_model)
    if provider == "openai":
        from connectors.github.src.llm.openai_adapter import OpenAIAdapter
        return OpenAIAdapter(model_name=args.llm_model)
    sys.exit(f"ERROR: unknown llm-provider: {provider!r}")


async def _run(args: argparse.Namespace) -> int:
    # Lazy imports — keeps failures localized to the point of use.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from seed_graph import TargetProfile

    from connectors.github.src.scanner import (
        scan_repository,
        scan_repository_with_llm,
    )
    from connectors.github.tests.reconcile import reconcile

    if not args.target.is_file():
        print(f"ERROR: target profile not found: {args.target}", file=sys.stderr)
        return 2
    if not args.repo.is_dir():
        print(f"ERROR: repo not found: {args.repo}", file=sys.stderr)
        return 2

    try:
        profile = TargetProfile.load(args.target)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: profile load failed: {exc}", file=sys.stderr)
        return 2

    print(f"Profile: {profile.name}")
    print(f"Repo:    {args.repo}")

    # Run the scanner.
    if args.enable_llm:
        if not args.prompts_dir.is_dir():
            print(
                f"ERROR: --prompts-dir not found: {args.prompts_dir}",
                file=sys.stderr,
            )
            return 2
        adapter = _build_adapter(args)
        print(f"Adapter: {adapter.name} model={adapter.model_name}")
        print()
        result = await scan_repository_with_llm(
            args.repo,
            adapter=adapter,
            prompts_dir=args.prompts_dir,
            stack=args.stack,
            max_tokens=args.max_llm_tokens,
            use_cache=not args.no_llm_cache,
        )
        if result.metadata and "llm_scan" in result.metadata:
            scan_report = result.metadata["llm_scan"]["report"]
            if scan_report.get("aborted_reason"):
                print(
                    f"\nWARNING: LLM scan aborted: "
                    f"{scan_report['aborted_reason']}",
                    file=sys.stderr,
                )
                print(
                    "  Reconciliation will only see manifest nodes; expect "
                    "many MISSING entries for LLM-scope predictions.",
                    file=sys.stderr,
                )
            print(
                f"LLM scan: {scan_report['candidates_accepted']} accepted, "
                f"{scan_report['candidates_rejected_at_orchestrator']} static-rejected, "
                f"{scan_report['candidates_rejected_at_verifier']} verifier-rejected, "
                f"{scan_report['total_tokens']} tokens."
            )
            print()
    else:
        print("(manifest-only — pass --enable-llm to include LLM-scope nodes)")
        print()
        result = scan_repository(args.repo, stack=args.stack)

    # Reconcile.
    report = reconcile(
        expected=profile.expected_nodes(),
        actual_nodes=list(result.nodes),
    )
    print(report.format_report())
    return 0 if report.is_clean else 1


def main() -> int:
    args = _build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-8s %(name)s: %(message)s",
    )
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
