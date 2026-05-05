"""Stack detector tests — purely static, no project state needed."""

from __future__ import annotations

from pathlib import Path

import pytest

from connectors.github.src.detect import UnknownStackError, detect_stack


def _touch(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


class TestDetectStack:
    def test_detects_python_from_requirements(self, tmp_path: Path) -> None:
        _touch(tmp_path / "requirements.txt", "anthropic>=0.40\n")
        assert detect_stack(tmp_path) == "python"

    def test_detects_python_from_pyproject(self, tmp_path: Path) -> None:
        _touch(tmp_path / "pyproject.toml", "[project]\nname='x'\n")
        assert detect_stack(tmp_path) == "python"

    def test_detects_node(self, tmp_path: Path) -> None:
        _touch(tmp_path / "package.json", '{"name": "x"}')
        assert detect_stack(tmp_path) == "node"

    def test_detects_java_pom(self, tmp_path: Path) -> None:
        _touch(tmp_path / "pom.xml", "<project/>")
        assert detect_stack(tmp_path) == "java"

    def test_detects_java_gradle(self, tmp_path: Path) -> None:
        _touch(tmp_path / "build.gradle", "")
        assert detect_stack(tmp_path) == "java"

    def test_detects_java_gradle_kts(self, tmp_path: Path) -> None:
        _touch(tmp_path / "build.gradle.kts", "")
        assert detect_stack(tmp_path) == "java"

    def test_java_wins_over_node_when_both_present(self, tmp_path: Path) -> None:
        # Spring app with a frontend bundle: pom + package.json. Java first.
        _touch(tmp_path / "pom.xml", "<project/>")
        _touch(tmp_path / "package.json", '{"name": "frontend"}')
        assert detect_stack(tmp_path) == "java"

    def test_node_wins_over_python_when_both_present(self, tmp_path: Path) -> None:
        # Common shape we'll explicitly call out: Python backend +
        # Node/React frontend. Node is picked; user can override.
        _touch(tmp_path / "package.json", '{"name": "frontend"}')
        _touch(tmp_path / "requirements.txt", "fastapi\n")
        assert detect_stack(tmp_path) == "node"

    def test_unknown_stack_raises(self, tmp_path: Path) -> None:
        _touch(tmp_path / "README.md", "# Just a doc")
        with pytest.raises(UnknownStackError, match="No stack markers"):
            detect_stack(tmp_path)

    def test_not_a_directory_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("x")
        with pytest.raises(UnknownStackError, match="Not a directory"):
            detect_stack(f)
