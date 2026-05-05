"""Stack detector — sniff a repo checkout to choose which scanner to run.

Pure static. Looks at filenames at the repo root only; never opens a file.
Returns one of ``'python' | 'java' | 'node'`` or raises ``UnknownStackError``.

Detection precedence is deliberate:

    1. Java first — pom.xml or build.gradle* are unambiguous.
    2. Node second — package.json is also unambiguous on its own.
    3. Python third — accepts requirements.txt OR pyproject.toml.

The most common ambiguous case is a Python repo with a Node-side build for
its frontend. The user can override with ``--stack`` if the heuristic
picks wrong.
"""

from __future__ import annotations

from pathlib import Path

# File markers per stack. First match wins, top-down.
_STACK_MARKERS: list[tuple[str, list[str]]] = [
    ("java", ["pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle",
              "settings.gradle.kts"]),
    ("node", ["package.json"]),
    ("python", ["pyproject.toml", "requirements.txt", "setup.py", "Pipfile"]),
]


class UnknownStackError(ValueError):
    """Raised when no manifest file matches any known stack."""


def detect_stack(repo_path: Path) -> str:
    """Return the stack name for a repo checkout.

    Raises ``UnknownStackError`` when no marker file is present at the
    repo root. Subdirectory markers are intentionally ignored — Java
    monorepos that nest pom files under modules need ``--stack java``
    passed explicitly to avoid surprising selection.
    """
    if not repo_path.is_dir():
        msg = f"Not a directory: {repo_path}"
        raise UnknownStackError(msg)

    for stack, markers in _STACK_MARKERS:
        for marker in markers:
            if (repo_path / marker).is_file():
                return stack

    msg = (
        f"No stack markers found at {repo_path}. Expected one of: "
        f"{[m for _, ms in _STACK_MARKERS for m in ms]}. "
        "Pass --stack <python|java|node> to override."
    )
    raise UnknownStackError(msg)
