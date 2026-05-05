"""Auto-discovering golden-fixture test.

Walks ``connectors/github/tests/fixtures/*.golden.json`` at collection
time and parametrizes one test per fixture. Each test re-runs the
scanner with the fixture's recorded parameters and asserts the
normalized output matches the fixture.

Manifest-only fixtures run without an API key. LLM-augmented fixtures
skip when no key is set, with the standard fall-through message.

Adding a new fixture is a no-test-change workflow:

    python3 scripts/record_golden.py \\
        --repo examples/vulnerable-rag-app \\
        --output connectors/github/tests/fixtures/vulnerable-rag-app.golden.json

Commit the JSON. The next pytest run picks it up automatically.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from connectors.github.tests.golden import (
    Golden,
    compare_against_golden,
    parse_golden_json,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _discover_fixtures() -> list[tuple[Path, Golden]]:
    if not _FIXTURES_DIR.is_dir():
        return []
    out: list[tuple[Path, Golden]] = []
    for path in sorted(_FIXTURES_DIR.glob("*.golden.json")):
        try:
            golden = parse_golden_json(path.read_text())
        except (OSError, ValueError) as exc:
            # A malformed fixture should fail loudly at collection time
            # rather than silently skip — wrap as a synthetic test.
            out.append((path, exc))  # type: ignore[arg-type]
            continue
        out.append((path, golden))
    return out


_FIXTURES = _discover_fixtures()


def _has_llm_key() -> bool:
    return bool(
        os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("ASP_LLM_API_KEY")
    )


@pytest.mark.parametrize(
    ("fixture_path", "golden"),
    _FIXTURES,
    ids=[p.name for p, _ in _FIXTURES] or ["no-fixtures-yet"],
)
@pytest.mark.asyncio
async def test_fixture_matches_fresh_scan(fixture_path, golden):
    """Re-run the scan and assert the output matches the recorded golden."""
    if isinstance(golden, Exception):
        pytest.fail(f"Failed to parse fixture {fixture_path.name}: {golden}")

    if golden.enable_llm and not _has_llm_key():
        pytest.skip(
            f"{fixture_path.name} is an LLM-augmented fixture and no API key "
            "is set. Export ANTHROPIC_API_KEY or OPENAI_API_KEY to run."
        )

    repo = _REPO_ROOT / golden.repo_path
    if not repo.is_dir():
        pytest.skip(
            f"{fixture_path.name} references {golden.repo_path}, which "
            "does not exist in this checkout. (Targets cloned outside the "
            "repo are environment-bound; CI will need them mounted.)"
        )

    # Lazy imports so this module loads even without LLM SDKs.
    from connectors.github.src.scanner import (
        scan_repository,
        scan_repository_with_llm,
    )

    if not golden.enable_llm:
        result = scan_repository(repo)
    else:
        # Build the adapter from the fixture's recorded provider+model.
        if golden.adapter_name == "anthropic":
            from connectors.github.src.llm.anthropic_adapter import AnthropicAdapter
            adapter = AnthropicAdapter(model_name=golden.model_name)
        elif golden.adapter_name == "openai":
            from connectors.github.src.llm.openai_adapter import OpenAIAdapter
            adapter = OpenAIAdapter(model_name=golden.model_name)
        else:
            pytest.fail(
                f"{fixture_path.name}: unknown adapter "
                f"{golden.adapter_name!r}"
            )

        prompts_dir = (
            _REPO_ROOT / golden.prompts_dir if golden.prompts_dir else None
        )
        result = await scan_repository_with_llm(
            repo,
            adapter=adapter,
            prompts_dir=prompts_dir,
            use_cache=True,  # cache is the determinism mechanism for LLM goldens
        )

    fresh = json.loads(result.to_json())
    diff = compare_against_golden(golden=golden, fresh_scan=fresh)

    if not diff.matched:
        pytest.fail(
            f"{fixture_path.name} drift detected.\n\n"
            f"{diff.format_report()}\n\n"
            "If this drift is intentional (you bumped the scanner, "
            "edited a prompt, or the source repo changed), re-record "
            "the fixture with `python3 scripts/record_golden.py "
            f"--repo {golden.repo_path} --output {fixture_path}`."
        )
