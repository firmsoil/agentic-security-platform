"""CLI tests using typer's built-in CliRunner."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from asp_cli.main import app


def test_version() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip()  # non-empty


def test_ontology_validate_passes() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["ontology", "validate"])
    assert result.exit_code == 0
    assert "OK" in result.stdout


def test_ontology_show_produces_json() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["ontology", "show"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert "nodes" in parsed and "edges" in parsed


def test_ontology_mappings_filter() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app, ["ontology", "mappings", "--framework", "OWASP_AGENTIC_TOP_10_2026"]
    )
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    # Every returned mapping is from the requested framework.
    assert parsed  # non-empty
    assert all(m["framework"] == "OWASP_AGENTIC_TOP_10_2026" for m in parsed)
    # ASI01 should appear.
    assert any(m["identifier"] == "ASI01" for m in parsed)
