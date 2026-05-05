"""Node manifest parser tests — package.json."""

from __future__ import annotations

import json
from pathlib import Path

from connectors.github.src.stacks.node.parsers import parse_package_json


class TestParsePackageJson:
    def test_extracts_runtime_and_dev_deps(self, tmp_path: Path) -> None:
        path = tmp_path / "package.json"
        path.write_text(json.dumps({
            "name": "demo",
            "dependencies": {
                "@anthropic-ai/sdk": "^0.30.0",
                "next": "^15.0.0",
            },
            "devDependencies": {
                "typescript": "^5.5.0",
            },
        }))
        deps = {d["name"]: d for d in parse_package_json(path)}
        assert "@anthropic-ai/sdk" in deps
        assert deps["@anthropic-ai/sdk"]["version"] == "^0.30.0"
        assert "next" in deps
        assert "typescript" in deps

    def test_includes_peer_and_optional(self, tmp_path: Path) -> None:
        path = tmp_path / "package.json"
        path.write_text(json.dumps({
            "name": "demo",
            "peerDependencies": {"react": "^18.0.0"},
            "optionalDependencies": {"fsevents": "^2.0.0"},
        }))
        deps = {d["name"] for d in parse_package_json(path)}
        assert "react" in deps
        assert "fsevents" in deps

    def test_handles_no_deps_at_all(self, tmp_path: Path) -> None:
        path = tmp_path / "package.json"
        path.write_text('{"name": "empty"}')
        assert parse_package_json(path) == []

    def test_unparsable_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "package.json"
        path.write_text("{ not json")
        assert parse_package_json(path) == []

    def test_non_object_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "package.json"
        path.write_text('["array", "not", "object"]')
        assert parse_package_json(path) == []
