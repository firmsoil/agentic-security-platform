"""CLI entry point for the GitHub connector.

Usage::

    # Dry-run (default) — print ScanResult as JSON, no graph writes.
    python -m connectors.github.src --repo-path ./examples/vulnerable-rag-app

    # Live mode — write to Neo4j.
    python -m connectors.github.src \\
        --repo-path ./examples/vulnerable-rag-app \\
        --neo4j-uri bolt://localhost:7687 \\
        --neo4j-user neo4j \\
        --neo4j-password changeme

    # With LLM extraction (Java/Node need this; Python is optional).
    python -m connectors.github.src \\
        --repo-path ./examples/vulnerable-rag-app \\
        --enable-llm \\
        --neo4j-uri bolt://localhost:7687 \\
        --neo4j-password changeme

    # With a custom tenant ID.
    python -m connectors.github.src \\
        --repo-path ./examples/vulnerable-rag-app \\
        --neo4j-uri bolt://localhost:7687 \\
        --tenant-id my-org
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from connectors.github.src.scanner import scan_repository

log = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="asp-github-scan",
        description="Scan a repository and produce ontology-typed nodes for the Security Graph.",
    )
    p.add_argument(
        "--repo-path",
        type=Path,
        required=True,
        help="Path to the local repository checkout to scan.",
    )
    p.add_argument(
        "--repo-url",
        type=str,
        default=None,
        help=(
            "GitHub URL recorded on the Repository node. Cosmetic only — "
            "scanning still happens against --repo-path."
        ),
    )
    p.add_argument(
        "--stack",
        type=str,
        choices=("python", "java", "node"),
        default=None,
        help=(
            "Override stack detection. Useful for monorepos where "
            "manifests for multiple stacks coexist at the repo root."
        ),
    )
    p.add_argument(
        "--neo4j-uri",
        type=str,
        default=None,
        help="Neo4j bolt URI. If omitted, runs in dry-run mode.",
    )
    p.add_argument(
        "--neo4j-user",
        type=str,
        default="neo4j",
        help="Neo4j username (default: neo4j).",
    )
    p.add_argument(
        "--neo4j-password",
        type=str,
        default="changeme",
        help="Neo4j password.",
    )
    p.add_argument(
        "--neo4j-database",
        type=str,
        default="neo4j",
        help="Neo4j database name (default: neo4j).",
    )
    p.add_argument(
        "--tenant-id",
        type=str,
        default="default",
        help="Tenant ID for multi-tenant scoping (default: 'default').",
    )

    # ---- LLM scanner flags --------------------------------------------------
    llm = p.add_argument_group(
        "LLM scanner",
        description=(
            "Optional. Layers grounded LLM extraction on top of the "
            "manifest pass — required for Tool/PromptTemplate/RAGIndex/"
            "MemoryStore on Java and Node, optional on Python where the "
            "static parsers cover the same surface."
        ),
    )
    llm.add_argument(
        "--enable-llm",
        action="store_true",
        default=False,
        help="Run the LLM scanner after the manifest scan.",
    )
    llm.add_argument(
        "--llm-provider",
        type=str,
        choices=("anthropic", "openai"),
        default=None,
        help=(
            "Adapter to use. Defaults to anthropic if both keys are set; "
            "auto-selected from whichever of ANTHROPIC_API_KEY / "
            "OPENAI_API_KEY is present otherwise."
        ),
    )
    llm.add_argument(
        "--llm-model",
        type=str,
        default=None,
        help=(
            "Override the adapter's default model. Also reads "
            "ASP_LLM_MODEL from the environment."
        ),
    )
    llm.add_argument(
        "--prompts-dir",
        type=Path,
        default=Path("prompts"),
        help=(
            "Directory containing extract_*.md prompts (default: ./prompts). "
            "Part of the LLM scanner cache key."
        ),
    )
    llm.add_argument(
        "--max-llm-tokens",
        type=int,
        default=200_000,
        help=(
            "Hard cap on input+output tokens per scan. The scanner aborts "
            "rather than overspend (default: 200000)."
        ),
    )
    llm.add_argument(
        "--no-llm-cache",
        action="store_true",
        default=False,
        help=(
            "Bypass the filesystem cache. Use for parity tests and "
            "first-run after a prompt edit when you want to confirm "
            "the new prompt actually fired."
        ),
    )

    p.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print the ScanResult as JSON without writing to Neo4j. "
             "Implied when --neo4j-uri is not provided.",
    )
    p.add_argument(
        "-v", "--verbose",
        action="store_true",
        default=False,
        help="Enable debug logging.",
    )
    return p


def _build_adapter(args: argparse.Namespace):
    """Construct a StructuredExtractor from CLI flags + env."""
    provider = args.llm_provider
    has_anthropic = bool(
        os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("ASP_LLM_API_KEY")
    )
    has_openai = bool(
        os.environ.get("OPENAI_API_KEY")
        or os.environ.get("ASP_LLM_API_KEY")
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


async def _scan(args: argparse.Namespace):
    """Return the ScanResult — manifest-only or LLM-augmented per --enable-llm."""
    if not args.enable_llm:
        return scan_repository(
            args.repo_path,
            repo_url=args.repo_url,
            stack=args.stack,
        )

    if not args.prompts_dir.is_dir():
        sys.exit(
            f"ERROR: --prompts-dir not found: {args.prompts_dir}. "
            "Pass --prompts-dir pointing at the prompts/ directory."
        )

    from connectors.github.src.scanner import scan_repository_with_llm

    adapter = _build_adapter(args)
    log.info(
        "LLM scanner enabled: adapter=%s model=%s prompts=%s max_tokens=%d",
        adapter.name, adapter.model_name, args.prompts_dir, args.max_llm_tokens,
    )
    return await scan_repository_with_llm(
        args.repo_path,
        adapter=adapter,
        prompts_dir=args.prompts_dir,
        repo_url=args.repo_url,
        stack=args.stack,
        max_tokens=args.max_llm_tokens,
        use_cache=not args.no_llm_cache,
    )


async def _run_live(args: argparse.Namespace) -> int:
    """Write scan results to a live Neo4j instance."""
    # Lazy imports so dry-run mode works without neo4j driver installed.
    from asp_adapters.graph.neo4j import Neo4jConfig, Neo4jGraphStore
    from asp_core.graph import load_ontology

    from connectors.github.src.writer import write_scan_result

    result = await _scan(args)

    ontology = load_ontology("v1")
    config = Neo4jConfig(
        uri=args.neo4j_uri,
        user=args.neo4j_user,
        password=args.neo4j_password,
        database=args.neo4j_database,
    )
    store = Neo4jGraphStore(config=config, ontology=ontology)
    try:
        await store.connect()
        report = await write_scan_result(store, args.tenant_id, result)
        print(report.summary())
        if result.metadata and "llm_scan" in result.metadata:
            print(f"  LLM scan: {result.metadata['llm_scan']['report']}")
        if not report.ok:
            for err in report.errors:
                print(f"  ERROR: {err}", file=sys.stderr)
            return 1
        return 0
    finally:
        await store.close()


async def _run_dry(args: argparse.Namespace) -> int:
    """Print the ScanResult as JSON without writing to Neo4j."""
    result = await _scan(args)
    print(result.to_json())
    return 0


def main() -> int:
    args = _build_parser().parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-8s %(name)s: %(message)s",
    )

    is_dry_run = args.dry_run or args.neo4j_uri is None
    runner = _run_dry if is_dry_run else _run_live
    return asyncio.run(runner(args))


if __name__ == "__main__":
    sys.exit(main())
