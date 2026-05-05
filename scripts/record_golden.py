"""Golden-fixture recorder.

Runs the scanner with the given parameters, normalizes the output, and
writes a ``*.golden.json`` file that ``test_golden_fixtures.py`` will
later re-verify against. Recording a golden is a deliberate act — it
captures the scanner's current behaviour as the baseline. Subsequent
re-runs that diverge from the baseline will fail the golden test until
the fixture is re-recorded.

Usage::

    # Manifest-only — fast and cheap, deterministic for every stack.
    python3 scripts/record_golden.py \\
        --repo examples/vulnerable-rag-app \\
        --output connectors/github/tests/fixtures/vulnerable-rag-app.golden.json

    # LLM-augmented — needs an API key. Cache makes re-runs deterministic
    # for the same (commit, scanner_version, adapter, model, prompt_sha).
    ANTHROPIC_API_KEY=sk-ant-... python3 scripts/record_golden.py \\
        --repo examples/vulnerable-rag-app \\
        --enable-llm \\
        --output connectors/github/tests/fixtures/vulnerable-rag-app.llm.golden.json

When you intentionally edit a prompt or bump SCANNER_VERSION, every
LLM-augmented golden in fixtures/ becomes stale and must be re-recorded.
The golden test surfaces drift loudly so you can't forget.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# Make the repo root importable regardless of cwd, so `uv run python3
# scripts/record_golden.py …` works without `PYTHONPATH=.`.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from connectors.github.tests.golden import (
    GOLDEN_SCHEMA_VERSION,
    Golden,
    normalize_scan_result,
    render_golden_json,
)

log = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="record-golden",
        description=(
            "Record a golden scan fixture. The fixture is the determinism "
            "baseline tested by connectors/github/tests/test_golden_fixtures.py."
        ),
    )
    p.add_argument(
        "--repo",
        type=Path,
        required=True,
        help="Repo to scan, relative to the project root.",
    )
    p.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Where to write the golden JSON.",
    )
    p.add_argument(
        "--enable-llm",
        action="store_true",
        default=False,
        help="Layer the LLM scanner on top of the manifest pass.",
    )
    p.add_argument(
        "--llm-provider",
        type=str,
        choices=("anthropic", "openai"),
        default=None,
    )
    p.add_argument("--llm-model", type=str, default=None)
    p.add_argument(
        "--prompts-dir",
        type=Path,
        default=Path("prompts"),
        help="Directory holding extract_*.md prompts.",
    )
    p.add_argument("--max-llm-tokens", type=int, default=200_000)
    p.add_argument(
        "--stack",
        type=str,
        choices=("python", "java", "node"),
        default=None,
    )
    p.add_argument("-v", "--verbose", action="store_true", default=False)
    return p


def _build_adapter(args: argparse.Namespace):
    """Same selection logic used by __main__.py / run_parity_test.py /
    reconcile_target.py — kept in sync intentionally."""
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
                "ERROR: --enable-llm set but no LLM API key found."
            )
    if provider == "anthropic":
        from connectors.github.src.llm.anthropic_adapter import AnthropicAdapter
        return AnthropicAdapter(model_name=args.llm_model)
    if provider == "openai":
        from connectors.github.src.llm.openai_adapter import OpenAIAdapter
        return OpenAIAdapter(model_name=args.llm_model)
    sys.exit(f"ERROR: unknown llm-provider: {provider!r}")


async def _run(args: argparse.Namespace) -> int:
    from connectors.github.src.scanner import (
        scan_repository,
        scan_repository_with_llm,
    )

    if not args.repo.is_dir():
        print(f"ERROR: repo not found: {args.repo}", file=sys.stderr)
        return 2

    print(f"Recording golden for: {args.repo}")
    print(f"Mode: {'manifest + LLM' if args.enable_llm else 'manifest-only'}")

    cache_key = None
    adapter_name = None
    model_name = None
    prompts_dir_str = None

    if args.enable_llm:
        if not args.prompts_dir.is_dir():
            print(
                f"ERROR: --prompts-dir not found: {args.prompts_dir}",
                file=sys.stderr,
            )
            return 2
        adapter = _build_adapter(args)
        adapter_name = adapter.name
        model_name = adapter.model_name
        prompts_dir_str = str(args.prompts_dir)
        print(f"Adapter: {adapter.name} model={adapter.model_name}")

        # Capture the cache key inputs so the golden carries provenance.
        from connectors.github.src.llm import SCANNER_VERSION
        from connectors.github.src.llm.cache import (
            prompt_sha,
            repo_commit_sha,
        )
        from connectors.github.src.llm.prompts import all_extraction_prompt_paths

        cache_key = {
            "repo_commit_sha": repo_commit_sha(args.repo),
            "scanner_version": SCANNER_VERSION,
            "adapter": adapter.name,
            "model_name": adapter.model_name,
            "prompt_sha": prompt_sha(all_extraction_prompt_paths(args.prompts_dir)),
        }

        result = await scan_repository_with_llm(
            args.repo,
            adapter=adapter,
            prompts_dir=args.prompts_dir,
            stack=args.stack,
            max_tokens=args.max_llm_tokens,
            use_cache=True,
        )
    else:
        result = scan_repository(args.repo, stack=args.stack)

    fresh = json.loads(result.to_json())
    normalized = normalize_scan_result(fresh)
    print(
        f"Scan: {normalized['node_count']} nodes, "
        f"{normalized['edge_count']} edges, stack={normalized['stack']}"
    )

    golden = Golden(
        schema_version=GOLDEN_SCHEMA_VERSION,
        repo_path=str(args.repo),
        enable_llm=args.enable_llm,
        adapter_name=adapter_name,
        model_name=model_name,
        prompts_dir=prompts_dir_str,
        cache_key=cache_key,
        normalized_scan=normalized,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_golden_json(golden))
    print(f"Wrote golden: {args.output}")
    return 0


def main() -> int:
    args = _build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-8s %(name)s: %(message)s",
    )
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
